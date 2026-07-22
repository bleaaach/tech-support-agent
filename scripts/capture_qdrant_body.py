#!/usr/bin/env python3
"""捕获 qdrant_client 发送的原始请求体"""
import sys, os
sys.path.insert(0, '/home/seeed/tech-support-agent')
os.environ['QDRANT_FALLBACK_LOCAL'] = '0'

import json, httpx

# 捕获原始请求
class DebugTransport(httpx.BaseTransport):
    def __init__(self, wrapped):
        self.wrapped = wrapped
        
    def handle_request(self, request):
        body = request.content.decode('utf-8', errors='replace')
        if 'points' in request.url.path:
            print("=== CAPTURED UPSERT REQUEST ===", file=sys.stderr)
            print(f"URL: {request.url}", file=sys.stderr)
            print(f"Body ({len(body)} bytes):", file=sys.stderr)
            print(body[:2000], file=sys.stderr)
            print("=== END ===", file=sys.stderr)
        return self.wrapped.handle_request(request)

# Patch httpx
original_transport = None

from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

# 创建一个临时 transport 来捕获
import httpx
orig_send = httpx.Client.send

def patched_send(self, request):
    body = request.content.decode('utf-8', errors='replace')
    if 'points' in str(request.url):
        print("=== UPSERT REQUEST BODY ===", file=sys.stderr)
        print(f"URL: {request.url}", file=sys.stderr)
        print(f"Body:\n{body[:3000]}", file=sys.stderr)
        print("=== END ===", file=sys.stderr)
    return orig_send(self, request)

httpx.Client.send = patched_send

client = QdrantClient(host="localhost", port=6333)
pt = PointStruct(id="debug1", vector=[0.01]*1024, payload={"doc_id": "d1", "title": "T"})
try:
    client.upsert("jetson_wiki", points=[pt])
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
