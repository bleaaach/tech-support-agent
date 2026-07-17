"""FastAPI Agent 服务"""
from __future__ import annotations
import os
from pathlib import Path

# 加载 .env（uvicorn 进程需要）
# 使用 os.environ[k]=v 强制覆盖，shell 中残留的旧值不会凌驾 .env
_dotenv_path = Path(__file__).parent.parent / ".env"
if _dotenv_path.exists():
    with open(_dotenv_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

import asyncio
import uuid
import logging
from contextlib import asynccontextmanager
from typing import Any, Optional, List, Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from concurrent.futures import ThreadPoolExecutor

from .chat import TechSupportChat, ConversationContext
from .router import QuestionType
from .email_renderer import render_email

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ---- 会话存储（生产环境换 Redis）----
_sessions: Dict[str, ConversationContext] = {}
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="agent-worker")

# ---- 配置加载 ----
_api_cfg: dict = {
    "host": "0.0.0.0",
    "port": 8000,
    "cors_origins": ["http://localhost:3000", "http://localhost:8501"],
}
try:
    from .config import get_config
    _cfg = get_config()
    _api_cfg = _cfg.get("api", _api_cfg)
except Exception:
    _cfg = {}


def get_or_create_session(session_id: Optional[str], category: str = "") -> tuple[str, ConversationContext]:
    if session_id and session_id in _sessions:
        ctx = _sessions[session_id]
        if category:
            ctx.category = category
        return session_id, ctx
    new_id = session_id or str(uuid.uuid4())
    ctx = ConversationContext(session_id=new_id, category=category)
    _sessions[new_id] = ctx
    return new_id, ctx


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    category: str = ""
    raw: bool = False  # True = 返回纯文本，不走邮件模板


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    sources: List[dict]
    question_type: str
    image_urls: List[str]
    resource_urls: List[str]
    needs_followup: bool
    followup_hint: str


class HistoryRequest(BaseModel):
    session_id: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Tech Support Agent starting...")
    yield
    log.info("Tech Support Agent shutting down...")


app = FastAPI(
    title="Seeed Tech Support Agent",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_api_cfg.get("cors_origins", ["*"]),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 懒加载 Agent
_agent: Optional[TechSupportChat] = None


def get_agent() -> TechSupportChat:
    global _agent
    if _agent is None:
        _agent = TechSupportChat()
    return _agent


def _sync_chat(agent: TechSupportChat, ctx: ConversationContext, message: str, raw: bool) -> dict:
    """同步 agent.chat() 包装，run_in_executor 需要可调用对象。"""
    result = agent.chat(ctx, message)

    if not raw:
        from .router import QuestionType
        qtype_str = result.get("question_type", "general")
        try:
            qtype = QuestionType(qtype_str)
        except ValueError:
            qtype = QuestionType.GENERAL
        from .email_renderer import render_email
        rendered = render_email(
            question=message,
            answer=result["answer"],
            sources=result["sources"],
            image_urls=result.get("image_urls", []),
            resource_urls=result.get("resource_urls", []),
            qtype=qtype,
            answer_language=result.get("answer_language", "zh"),
        )
        result["answer"] = rendered

    return result


@app.get("/", response_class=HTMLResponse)
async def root():
    return """<html><head><title>Seeed Tech Support Agent</title></head>
<body><h1>Seeed Tech Support Agent</h1>
<p>API is running. POST to /chat with JSON body.</p>
<h2>Example</h2>
<pre>curl -X POST http://localhost:8000/chat \\
  -H "Content-Type: application/json" \\
  -d '{"message": "reComputer J401 supports which JetPack version?"}'</pre>
</body></html>"""


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")

    sid, ctx = get_or_create_session(req.session_id, req.category)
    agent = get_agent()

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        _executor,
        _sync_chat,
        agent, ctx, req.message, req.raw
    )

    return ChatResponse(
        session_id=sid,
        answer=result["answer"],
        sources=result["sources"],
        question_type=result["question_type"],
        image_urls=result.get("image_urls", []),
        resource_urls=result.get("resource_urls", []),
        needs_followup=result.get("needs_followup", False),
        followup_hint=result.get("followup_hint", ""),
    )


@app.post("/history")
async def get_history(req: HistoryRequest) -> Dict[str, Any]:
    if req.session_id not in _sessions:
        raise HTTPException(status_code=404, detail="session not found")
    ctx = _sessions[req.session_id]
    return {
        "session_id": req.session_id,
        "category": ctx.category,
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "timestamp": m.timestamp,
                "sources": m.sources,
                "question_type": m.question_type,
            }
            for m in ctx.messages
        ],
    }


@app.post("/reset")
async def reset_session(req: HistoryRequest) -> Dict[str, str]:
    if req.session_id in _sessions:
        del _sessions[req.session_id]
    return {"status": "ok", "message": f"Session {req.session_id} cleared"}


@app.get("/health")
async def health():
    try:
        agent = get_agent()
        count = agent.retriever.count()
        return {"status": "healthy", "chunks_indexed": count}
    except Exception as e:
        return {"status": "degraded", "error": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "agent.main:app",
        host=_api_cfg.get("host", "0.0.0.0"),
        port=_api_cfg.get("port", 8000),
        reload=False,
    )
