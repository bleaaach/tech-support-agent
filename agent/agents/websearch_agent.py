"""网络搜索 Agent：Wiki 检索的兜底，执行 Tavily Search API。

设计详见 docs/MULTI_AGENT_INTEGRATION_PLAN.md §四。

实现决策（v1.0）：
- 原计划用 DeepSeek Anthropic web_search server tool 实现 LLM 自主联网。
- 实测发现：本项目使用的 AI 网关（47.236.182.242）仅透传 protocol，
  不真正执行 server-side tool（不会回填 tool_result）。
- 因此 websearch_agent 改为：单纯执行 Tavily Search API（可被外部 LLM 决策后调用），
  是否触发由 graph.py 的 reflect 节点或其他 LLM 决策决定。

触发条件（由外部节点控制）：
    - enabled=True
    - wiki_chunks 为空 或 reflect.score < trigger_on_reflect_score_below
    - 或 graph.py 显式调用 run()

输出：构造 websearch_chunks（注入 wiki_chunks，prepend，次于 diagnostic_chunks）
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# .env 加载（与其他模块一致）
_env_path = Path(__file__).parent.parent.parent / ".env"
if _env_path.exists():
    with open(_env_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


@dataclass
class WebSearchOutput:
    """WebSearchAgent.run() 的返回结构（与 graph 节点契约对齐）"""

    websearch_chunks: list[dict] = field(default_factory=list)
    provider_used: str = ""           # "tavily" | ""
    search_latency_ms: int = 0
    fallback_reason: str = ""         # 若不可用


class WebSearchAgent:
    """网络搜索 Agent：执行 Tavily Search API

    用法：
        agent = WebSearchAgent.from_config({
            "enabled": True,
            "max_results": 3,
            "allowed_domains": ["wiki.seeedstudio.com"],
        })
        out = agent.run(query="Jetson Orin NX JetPack 6.2")
        # out.websearch_chunks 可注入 graph 的 wiki_chunks
    """

    DEFAULT_MAX_RESULTS = 3
    TAVILY_BASE_URL = "https://api.tavily.com"
    TAVILY_TIMEOUT = 15

    def __init__(
        self,
        enabled: bool = False,
        max_results: int = DEFAULT_MAX_RESULTS,
        allowed_domains: list[str] | None = None,
        trigger_on_empty_wiki_chunks: bool = True,
        trigger_on_reflect_score_below: float = 0.4,
        tavily_cfg: dict | None = None,
    ):
        self.enabled = enabled
        self.max_results = max_results
        self.allowed_domains = allowed_domains or []
        self.trigger_on_empty_wiki_chunks = trigger_on_empty_wiki_chunks
        self.trigger_on_reflect_score_below = trigger_on_reflect_score_below
        self.tavily_cfg = tavily_cfg or {}

    # ---------- 工厂方法 ----------
    @classmethod
    def from_config(cls, cfg: dict) -> "WebSearchAgent":
        """从 config.yaml 风格的 dict 构造（兼容 None / 缺字段）"""
        return cls(
            enabled=cfg.get("enabled", False),
            max_results=cfg.get("max_results", cls.DEFAULT_MAX_RESULTS),
            allowed_domains=cfg.get("allowed_domains", []),
            trigger_on_empty_wiki_chunks=cfg.get("trigger_on_empty_wiki_chunks", True),
            trigger_on_reflect_score_below=cfg.get(
                "trigger_on_reflect_score_below", 0.4
            ),
            tavily_cfg=cfg.get("tavily", {}),
        )

    # ---------- 公开方法 ----------
    def should_trigger(
        self,
        wiki_chunks: list | None = None,
        reflect_score: float | None = None,
    ) -> tuple[bool, str]:
        """判断是否应该触发搜索

        Returns:
            (should_run, reason)
        """
        if not self.enabled:
            return False, "agent disabled"

        wiki_empty = wiki_chunks is None or len(wiki_chunks) == 0
        low_score = (
            reflect_score is not None
            and reflect_score < self.trigger_on_reflect_score_below
        )

        if self.trigger_on_empty_wiki_chunks and wiki_empty:
            return True, "wiki_chunks empty"
        if low_score:
            return True, f"reflect_score {reflect_score:.2f} < {self.trigger_on_reflect_score_below}"
        return False, "trigger conditions not met"

    def available(self) -> tuple[bool, str]:
        """检查 Tavily 是否可用（API key 是否配置）"""
        if not self.enabled:
            return False, "agent disabled"
        api_key = self._get_tavily_api_key()
        if not api_key:
            return False, "TAVILY_API_KEY not set"
        return True, "tavily ready"

    def run(
        self,
        query: str,
        max_results: int | None = None,
        allowed_domains: list[str] | None = None,
    ) -> WebSearchOutput:
        """主入口：执行搜索 → 解析 → 构造 websearch_chunks

        Args:
            query: 已重写后的查询
            max_results: 覆盖默认 max_results（一般不传）
            allowed_domains: 覆盖默认 allowed_domains（一般不传）

        异常被全部捕获，返回空 WebSearchOutput，不影响上层流程。
        """
        if not self.enabled:
            return WebSearchOutput(fallback_reason="agent disabled")

        n = max_results if max_results is not None else self.max_results
        domains = allowed_domains if allowed_domains is not None else self.allowed_domains

        api_key = self._get_tavily_api_key()
        if not api_key:
            return WebSearchOutput(
                fallback_reason="TAVILY_API_KEY not configured. Set TAVILY_API_KEY env var or config.yaml tavily.api_key."
            )

        try:
            chunks, latency = self._search_tavily(query, n, domains, api_key)
            logger.info(
                f"[websearch] tavily returned {len(chunks)} chunks, latency={latency}ms"
            )
            return WebSearchOutput(
                websearch_chunks=chunks,
                provider_used="tavily",
                search_latency_ms=latency,
            )
        except Exception as e:
            logger.warning(f"[websearch] tavily failed: {e}")
            return WebSearchOutput(fallback_reason=f"tavily failed: {e!s}")

    # ---------- 后端：Tavily ----------
    def _get_tavily_api_key(self) -> str:
        cfg_key = self.tavily_cfg.get("api_key", "")
        if cfg_key and not cfg_key.startswith("${"):
            return cfg_key
        return os.environ.get("TAVILY_API_KEY", "")

    def _search_tavily(
        self, query: str, n: int, domains: list[str], api_key: str
    ) -> tuple[list[dict], int]:
        """调用 Tavily Search API

        详见 https://docs.tavily.com/documentation/api-reference/endpoint/search
        """
        try:
            import requests
        except ImportError:
            raise RuntimeError("requests library not installed")

        base_url = self.tavily_cfg.get("base_url", self.TAVILY_BASE_URL)
        search_depth = self.tavily_cfg.get("search_depth", "basic")

        payload: dict[str, Any] = {
            "query": query,
            "max_results": n,
            "search_depth": search_depth,
            "include_answer": False,
            "include_raw_content": True,
        }
        if domains:
            payload["include_domains"] = domains

        start = time.time()
        resp = requests.post(
            f"{base_url}/search",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=self.TAVILY_TIMEOUT,
        )
        latency_ms = int((time.time() - start) * 1000)

        if resp.status_code != 200:
            raise RuntimeError(
                f"Tavily API returned {resp.status_code}: {resp.text[:200]}"
            )

        data = resp.json()
        chunks: list[dict] = []
        for r in data.get("results", [])[:n]:
            chunks.append(
                self._format_chunk(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    content=(r.get("raw_content") or r.get("content") or "")[:2000],
                    score=r.get("score", 0.7),
                )
            )
        return chunks, latency_ms

    # ---------- 内部 ----------
    @staticmethod
    def _format_chunk(title: str, url: str, content: str, score: float) -> dict:
        """构造统一格式的 websearch chunk（兼容 graph.wiki_chunks 的结构）"""
        chunk_text_parts = [f"[来源: tavily]"]
        if title:
            chunk_text_parts.append(f"**{title}**")
        if url:
            chunk_text_parts.append(f"URL: {url}")
        if content:
            chunk_text_parts.append("")
            chunk_text_parts.append(content)
        chunk_text = "\n".join(chunk_text_parts)

        return {
            "chunk_text": chunk_text,
            "title": title or url,
            "wiki_url": url,
            "category": "websearch",
            "doc_id": f"websearch_{hash(url) & 0xFFFFFFFF}",
            "score": score,
            "image_urls": [],
            "resource_urls": [],
            "_websearch_meta": {
                "source": "tavily",
                "url": url,
            },
        }


# ============================================================
# Standalone 入口（便于 Phase 2 验证，Phase 3 由 graph.py 调用）
# ============================================================

def _cli():
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="WebSearch Agent CLI — Tavily 联网搜索"
    )
    parser.add_argument("--query", "-q", required=True, help="搜索 query")
    parser.add_argument("--max-results", "-n", type=int, default=3)
    args = parser.parse_args()

    agent = WebSearchAgent.from_config(
        {
            "enabled": True,
            "max_results": args.max_results,
            "allowed_domains": [
                "wiki.seeedstudio.com",
                "seeedstudio.com",
                "developer.nvidia.com",
                "forums.developer.nvidia.com",
            ],
        }
    )
    out = agent.run(args.query)
    print(json.dumps(
        {
            "provider_used": out.provider_used,
            "latency_ms": out.search_latency_ms,
            "chunks_count": len(out.websearch_chunks),
            "fallback_reason": out.fallback_reason,
            "first_chunk_preview": (
                {
                    "title": out.websearch_chunks[0]["title"],
                    "url": out.websearch_chunks[0]["wiki_url"],
                    "text_preview": out.websearch_chunks[0]["chunk_text"][:300],
                }
                if out.websearch_chunks
                else None
            ),
        },
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    _cli()