#!/usr/bin/env python3
"""调试 Qdrant upsert 请求"""
import sys, os, json
sys.path.insert(0, '/home/seeed/tech-support-agent')

from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

# Patch httpx to print request body
import httpx
orig = httpx.Client.send

def patched_send(self, request):
    print(f"=== httpx REQUEST ===", file=sys.stderr)
    print(f"Method: {request.method}", file=sys.stderr)
    print(f"URL: {request.url}", file=sys.stderr)
    print(f"Headers: {dict(request.headers)}", file=sys.stderr)
    print(f"Body: {request.content}", file=sys.stderr)
    print(f"======================", file=sys.stderr)
    return orig(self, request)

httpx.Client.send = patched_send

client = QdrantClient(host="localhost", port=6333)
pt = PointStruct(id="debug001", vector=[0.01]*1024, payload={"doc_id":"test"})
try:
    result = client.upsert("jetson_wiki", points=[pt])
    print("SUCCESS:", result)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
