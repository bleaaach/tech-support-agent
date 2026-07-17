"""WebSearch Agent 单元测试

覆盖：
1. 触发条件判断（enabled / wiki_chunks / reflect_score）
2. 可用性检查（TAVILY_API_KEY）
3. Tavily API 调用（mock requests）
4. 异常降级（无 key / API 错误 / 网络超时）
5. chunk 格式转换（与 graph.wiki_chunks 结构兼容）
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ============================================================
# 1) 触发条件判断
# ============================================================

def test_should_trigger_when_wiki_empty():
    """wiki_chunks 为空 + trigger_on_empty_wiki_chunks=True → 应触发"""
    from agent.agents import WebSearchAgent
    agent = WebSearchAgent.from_config({"enabled": True, "trigger_on_empty_wiki_chunks": True})
    should, reason = agent.should_trigger(wiki_chunks=[], reflect_score=None)
    assert should is True
    assert "empty" in reason.lower()


def test_should_not_trigger_when_wiki_ok_and_score_ok():
    """wiki_chunks 有内容 + reflect_score 高 → 不触发"""
    from agent.agents import WebSearchAgent
    agent = WebSearchAgent.from_config(
        {"enabled": True, "trigger_on_empty_wiki_chunks": True, "trigger_on_reflect_score_below": 0.4}
    )
    should, reason = agent.should_trigger(wiki_chunks=["c1", "c2"], reflect_score=0.8)
    assert should is False
    assert "not met" in reason.lower()


def test_should_trigger_when_score_low():
    """reflect_score 低 → 触发"""
    from agent.agents import WebSearchAgent
    agent = WebSearchAgent.from_config({"enabled": True, "trigger_on_reflect_score_below": 0.4})
    should, reason = agent.should_trigger(wiki_chunks=["c1"], reflect_score=0.3)
    assert should is True
    assert "0.30" in reason


def test_disabled_agent_never_triggers():
    """enabled=false → 永不触发"""
    from agent.agents import WebSearchAgent
    agent = WebSearchAgent.from_config({"enabled": False})
    should, reason = agent.should_trigger(wiki_chunks=[], reflect_score=0.0)
    assert should is False
    assert "disabled" in reason.lower()


# ============================================================
# 2) 可用性检查
# ============================================================

def test_available_without_api_key():
    """无 TAVILY_API_KEY → available=False"""
    from agent.agents import WebSearchAgent
    with patch.dict("os.environ", {}, clear=True):
        agent = WebSearchAgent.from_config({"enabled": True})
        available, reason = agent.available()
        assert available is False
        assert "TAVILY_API_KEY" in reason


def test_available_with_api_key():
    """有 TAVILY_API_KEY → available=True"""
    from agent.agents import WebSearchAgent
    with patch.dict("os.environ", {"TAVILY_API_KEY": "tvly-test123"}):
        agent = WebSearchAgent.from_config({"enabled": True})
        available, reason = agent.available()
        assert available is True


# ============================================================
# 3) Tavily API 调用（mock requests）
# ============================================================

def test_search_tavily_success():
    """Tavily 200 响应 → 正确解析 chunks"""
    from agent.agents import WebSearchAgent

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "results": [
            {
                "title": "Jetson Orin NX JetPack 6.2 - Seeed Wiki",
                "url": "https://wiki.seeedstudio.com/Jetson_Orin_NX_JetPack_6.2",
                "raw_content": "JetPack 6.2 brings new features...",
                "score": 0.92,
            },
            {
                "title": "NVIDIA Jetson JetPack Documentation",
                "url": "https://developer.nvidia.com/embedded/jetpack",
                "raw_content": "JetPack SDK is the most comprehensive...",
                "score": 0.85,
            },
        ]
    }

    with patch.dict("os.environ", {"TAVILY_API_KEY": "tvly-test"}):
        with patch("requests.post", return_value=fake_resp) as mock_post:
            agent = WebSearchAgent.from_config({"enabled": True})
            out = agent.run("Jetson Orin NX JetPack 6.2 release")

            assert out.provider_used == "tavily"
            assert len(out.websearch_chunks) == 2
            assert mock_post.called

            chunk = out.websearch_chunks[0]
            assert chunk["title"] == "Jetson Orin NX JetPack 6.2 - Seeed Wiki"
            assert chunk["wiki_url"].startswith("https://wiki.seeedstudio.com/")
            assert chunk["category"] == "websearch"
            assert chunk["score"] == 0.92
            assert "tavily" in chunk["chunk_text"]


def test_search_tavily_with_domain_filter():
    """allowed_domains 传递到 Tavily payload"""
    from agent.agents import WebSearchAgent

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {"results": []}

    with patch.dict("os.environ", {"TAVILY_API_KEY": "tvly-test"}):
        with patch("requests.post", return_value=fake_resp) as mock_post:
            agent = WebSearchAgent.from_config(
                {
                    "enabled": True,
                    "allowed_domains": ["wiki.seeedstudio.com"],
                }
            )
            agent.run("test")

            # 检查调用 payload 含 include_domains
            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            assert payload["include_domains"] == ["wiki.seeedstudio.com"]


def test_search_tavily_empty_results():
    """Tavily 返回空结果 → chunks 为空 + provider_used=tavily，fallback_reason 留空（无错误）"""
    from agent.agents import WebSearchAgent

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {"results": []}

    with patch.dict("os.environ", {"TAVILY_API_KEY": "tvly-test"}):
        with patch("requests.post", return_value=fake_resp):
            agent = WebSearchAgent.from_config({"enabled": True})
            out = agent.run("test")

            assert out.provider_used == "tavily"
            assert out.websearch_chunks == []
            assert out.fallback_reason == ""  # 空结果不算错误


# ============================================================
# 4) 异常降级
# ============================================================

def test_run_without_api_key_returns_empty():
    """无 API key → 返回空 + 友好提示，不抛异常"""
    from agent.agents import WebSearchAgent
    with patch.dict("os.environ", {}, clear=True):
        agent = WebSearchAgent.from_config({"enabled": True})
        out = agent.run("test query")
        assert out.websearch_chunks == []
        assert "TAVILY_API_KEY" in out.fallback_reason


def test_tavily_api_error_returns_empty():
    """Tavily 返回 500 → 捕获异常，返回空"""
    from agent.agents import WebSearchAgent

    fake_resp = MagicMock()
    fake_resp.status_code = 500
    fake_resp.text = "Internal Server Error"

    with patch.dict("os.environ", {"TAVILY_API_KEY": "tvly-test"}):
        with patch("requests.post", return_value=fake_resp):
            agent = WebSearchAgent.from_config({"enabled": True})
            out = agent.run("test")
            assert out.websearch_chunks == []
            assert "500" in out.fallback_reason


def test_tavily_network_timeout():
    """网络超时 → 捕获异常，返回空"""
    import requests
    from agent.agents import WebSearchAgent

    with patch.dict("os.environ", {"TAVILY_API_KEY": "tvly-test"}):
        with patch(
            "requests.post",
            side_effect=requests.Timeout("timed out"),
        ):
            agent = WebSearchAgent.from_config({"enabled": True})
            out = agent.run("test")
            assert out.websearch_chunks == []
            assert "failed" in out.fallback_reason.lower()


def test_disabled_agent_run():
    """enabled=false run → 立即返回空"""
    from agent.agents import WebSearchAgent
    agent = WebSearchAgent.from_config({"enabled": False})
    out = agent.run("test")
    assert out.websearch_chunks == []
    assert "disabled" in out.fallback_reason.lower()


# ============================================================
# 5) chunk 格式
# ============================================================

def test_chunk_format_compatible_with_wiki_chunks():
    """websearch_chunks 的字段与 graph wiki_chunks 兼容"""
    from agent.agents import WebSearchAgent

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "results": [
            {
                "title": "Test",
                "url": "https://example.com/test",
                "content": "Some content",
                "score": 0.75,
            }
        ]
    }

    with patch.dict("os.environ", {"TAVILY_API_KEY": "tvly-test"}):
        with patch("requests.post", return_value=fake_resp):
            agent = WebSearchAgent.from_config({"enabled": True})
            out = agent.run("test")
            chunk = out.websearch_chunks[0]

            # 必须字段（与 QdrantRetriever 返回的 RetrievedChunk 对齐）
            required_fields = {
                "chunk_text", "title", "wiki_url", "category",
                "doc_id", "score", "image_urls", "resource_urls",
            }
            assert required_fields.issubset(chunk.keys()), \
                f"missing fields: {required_fields - chunk.keys()}"


def test_chunk_text_truncation():
    """长内容被截断到 2000 字"""
    from agent.agents import WebSearchAgent

    long_content = "x" * 5000
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "results": [{"title": "T", "url": "https://e.com", "raw_content": long_content, "score": 0.5}]
    }

    with patch.dict("os.environ", {"TAVILY_API_KEY": "tvly-test"}):
        with patch("requests.post", return_value=fake_resp):
            agent = WebSearchAgent.from_config({"enabled": True})
            out = agent.run("test")
            # raw_content 部分不应超过 2000 + 一些 prefix
            assert len(out.websearch_chunks[0]["chunk_text"]) < 2200


# ============================================================
# 6) CLI 入口
# ============================================================

def test_cli_invocation(capsys):
    """CLI 入口能跑通（无 key 走降级路径）"""
    import subprocess

    result = subprocess.run(
        ["python3", "-m", "agent.agents.websearch_agent",
         "--query", "Jetson Orin NX JetPack 6.2",
         "--max-results", "2"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    out = result.stdout
    assert "provider_used" in out
    assert "chunks_count" in out


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))