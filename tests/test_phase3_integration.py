"""Phase 3 子 Agent 集成测试（直接测节点/路由函数，绕开 chat.py / retriever.py 依赖）

环境限制说明：
- 项目当前 Python 3.8 + openai 1.109 + typing_extensions，触发 `list[str]` PEP 585 不可用
- retriever.py 在 Py3.8 上无法 import（'type' object is not subscriptable）
- chat.py 链式导入 retriever.py，故也无法 import
- 但 graph.py 中的纯函数（node_diagnose / node_websearch / route_after_*）只依赖 _make_nodes
  返回的闭包 + 外部传入的 agent 实例，不依赖 retriever

本测试直接调 _make_nodes 工厂的产物，跳过 chat.py 中间层。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _try_import_graph():
    """Import agent.graph（必须 Py3.9+ 才走得通；Py3.8 跳过）"""
    import pytest
    try:
        # 修补 typing.Annotated（PEP 593 requires Py3.9+，Py3.8 backport）
        import typing
        if not hasattr(typing, "Annotated"):
            class _Annotated:
                def __class_getitem__(cls, params):
                    return params
            typing.Annotated = _Annotated

        # mock langgraph 和 openai（避免 langgraph 未装 + openai 在 Py3.8 链崩）
        import types
        fake_lg = types.ModuleType("langgraph.graph")
        class _FakeEND: pass
        class _FakeSTART: pass
        class _FakeStateGraph:
            def __init__(self, *a, **kw): pass
            def add_node(self, *a, **kw): pass
            def add_edge(self, *a, **kw): pass
            def add_conditional_edges(self, *a, **kw): pass
            def compile(self): return self
        fake_lg.END = _FakeEND
        fake_lg.START = _FakeSTART
        fake_lg.StateGraph = _FakeStateGraph
        fake_pkg = types.ModuleType("langgraph"); fake_pkg.graph = fake_lg
        sys.modules["langgraph"] = fake_pkg
        sys.modules["langgraph.graph"] = fake_lg

        # mock openai（避免 Py3.8 链崩）
        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = MagicMock()
        sys.modules["openai"] = fake_openai

        from agent.graph import _make_nodes, AgentState
        return _make_nodes, AgentState
    except Exception as e:
        pytest.skip(f"无法 import agent.graph（环境问题: {type(e).__name__}: {e}）")


# ============================================================
# 核心测试
# ============================================================

def test_t8_diagnose_node_no_agent_returns_empty():
    """T8.1：diagnose_agent=None 时，node_diagnose 返回空 diagnostic_chunks，不影响主流程"""
    _make_nodes, AgentState = _try_import_graph()

    # 构造最小化的依赖
    fake_retriever = MagicMock()
    fake_router = MagicMock()
    fake_generator = MagicMock()
    fake_rewrite_client = MagicMock()

    nodes = _make_nodes(fake_retriever, fake_router, fake_generator,
                        fake_rewrite_client, {}, None,
                        diagnose_agent=None, websearch_agent=None)

    state = {"user_message": "J401 报 cti error 1", "question_type": "troubleshooting"}
    result = nodes["node_diagnose"](state)
    assert result == {"diagnostic_chunks": []}


def test_t8_websearch_node_no_agent_returns_empty():
    """T8.2：websearch_agent=None 时，node_websearch 返回空 websearch_chunks"""
    _make_nodes, AgentState = _try_import_graph()

    nodes = _make_nodes(MagicMock(), MagicMock(), MagicMock(), MagicMock(),
                        {}, None, diagnose_agent=None, websearch_agent=None)

    state = {"user_message": "test", "wiki_chunks": [], "reflection_score": 0.2}
    result = nodes["node_websearch"](state)
    assert result == {"websearch_chunks": []}


def test_t9_diagnose_agent_enabled_returns_chunks():
    """T9.1：diagnose_agent 启用时，node_diagnose 调用 agent.run() 并返回 diagnostic_chunks"""
    _make_nodes, AgentState = _try_import_graph()

    # mock DiagnoseAgent 实例
    fake_diag = MagicMock()
    fake_diag.run.return_value = MagicMock(
        diagnostic_chunks=[
            {"chunk_text": "诊断: cti error 1 是 cgroup 配置问题",
             "title": "Jetson cgroup 故障",
             "wiki_url": "https://wiki.seeedstudio.com/jetson-cgroup",
             "category": "troubleshooting",
             "doc_id": "diag_001",
             "score": 1.0,
             "image_urls": [],
             "resource_urls": []}
        ],
        matched_error_codes=[MagicMock(code="cti error 1")],
        fallback_reason="",
    )

    nodes = _make_nodes(MagicMock(), MagicMock(), MagicMock(), MagicMock(),
                        {}, None, diagnose_agent=fake_diag, websearch_agent=None)

    state = {"user_message": "J401 报 cti error 1", "question_type": "troubleshooting"}
    result = nodes["node_diagnose"](state)

    assert fake_diag.run.called
    assert len(result["diagnostic_chunks"]) == 1
    assert result["diagnostic_chunks"][0]["doc_id"] == "diag_001"


def test_t9_websearch_agent_triggered_on_empty_wiki():
    """T9.2：websearch_agent 启用 + wiki_chunks 为空 + reflect_score 低 → 触发 websearch.run()"""
    _make_nodes, AgentState = _try_import_graph()

    fake_ws = MagicMock()
    fake_ws.should_trigger.return_value = (True, "wiki_chunks is empty")
    fake_ws.run.return_value = MagicMock(
        websearch_chunks=[{"chunk_text": "Tavily result", "score": 0.8,
                           "title": "external", "wiki_url": "", "category": "websearch",
                           "doc_id": "ws_001", "image_urls": [], "resource_urls": []}],
        provider_used="tavily",
        search_latency_ms=120,
        fallback_reason="",
    )

    nodes = _make_nodes(MagicMock(), MagicMock(), MagicMock(), MagicMock(),
                        {}, None, diagnose_agent=None, websearch_agent=fake_ws)

    state = {
        "user_message": "J401 蓝牙怎么配对",
        "rewritten_queries": ["J401 蓝牙"],
        "wiki_chunks": [],
        "reflection_score": 0.2,
    }
    result = nodes["node_websearch"](state)

    assert fake_ws.should_trigger.called
    assert fake_ws.run.called
    assert fake_ws.run.call_args[0][0] == "J401 蓝牙"  # 用 rewritten_queries[0]
    assert len(result["websearch_chunks"]) == 1


def test_t9_websearch_agent_skipped_when_wiki_ok():
    """T9.3：wiki_chunks 满 + reflect_score 高 → should_trigger 返回 False，跳过 websearch"""
    _make_nodes, AgentState = _try_import_graph()

    fake_ws = MagicMock()
    fake_ws.should_trigger.return_value = (False, "wiki sufficient")

    nodes = _make_nodes(MagicMock(), MagicMock(), MagicMock(), MagicMock(),
                        {}, None, diagnose_agent=None, websearch_agent=fake_ws)

    state = {
        "user_message": "test",
        "rewritten_queries": ["q1"],
        "wiki_chunks": [{"doc_id": "1", "chunk_text": "ok", "score": 0.9,
                          "title": "", "wiki_url": "", "category": "",
                          "image_urls": [], "resource_urls": []}],
        "reflection_score": 0.85,
    }
    result = nodes["node_websearch"](state)

    assert not fake_ws.run.called  # 关键：websearch 没跑
    assert result == {"websearch_chunks": []}


def test_t10_route_after_classify_default_goes_to_retrieve():
    """T10.1：diagnose_agent=None 时，route_after_classify 永远返回 retrieve（零回归）"""
    _make_nodes, AgentState = _try_import_graph()

    nodes = _make_nodes(MagicMock(), MagicMock(), MagicMock(), MagicMock(),
                        {}, None, diagnose_agent=None, websearch_agent=None)

    for qtype in ["troubleshooting", "howto", "compatibility", "general"]:
        state = {"question_type": qtype}
        assert nodes["route_after_classify"](state) == "retrieve", f"qtype={qtype} 应直接 retrieve"


def test_t10_route_after_classify_enabled_troubleshooting_goes_to_diagnose():
    """T10.2：diagnose_agent 启用且 qtype=troubleshooting → 路由到 diagnose"""
    _make_nodes, AgentState = _try_import_graph()

    fake_diag = MagicMock()
    fake_diag.trigger_qtypes = ["troubleshooting"]

    nodes = _make_nodes(MagicMock(), MagicMock(), MagicMock(), MagicMock(),
                        {}, None, diagnose_agent=fake_diag, websearch_agent=None)

    assert nodes["route_after_classify"]({"question_type": "troubleshooting"}) == "diagnose"
    # 其他 qtype 仍走 retrieve
    assert nodes["route_after_classify"]({"question_type": "howto"}) == "retrieve"


def test_t10_route_after_diagnose_skip_retrieve_when_chunks_exist():
    """T10.3：diagnostic_chunks 非空 → route_after_diagnose 跳 retrieve 直进 reflect"""
    _make_nodes, AgentState = _try_import_graph()

    nodes = _make_nodes(MagicMock(), MagicMock(), MagicMock(), MagicMock(),
                        {}, None, diagnose_agent=None, websearch_agent=None)

    # 有 chunks → reflect
    assert nodes["route_after_diagnose"]({"diagnostic_chunks": [{"chunk_text": "x"}]}) == "reflect"
    # 没 chunks → retrieve
    assert nodes["route_after_diagnose"]({"diagnostic_chunks": []}) == "retrieve"


def test_t10_route_after_historical_default_goes_to_reflect():
    """T10.4：websearch_agent=None → route_after_historical 永远 reflect（零回归）"""
    _make_nodes, AgentState = _try_import_graph()

    nodes = _make_nodes(MagicMock(), MagicMock(), MagicMock(), MagicMock(),
                        {}, None, diagnose_agent=None, websearch_agent=None)

    # 即使 wiki 空 + score 低，也直 reflect
    state = {"wiki_chunks": [], "reflection_score": 0.1}
    assert nodes["route_after_historical"](state) == "reflect"


def test_t10_route_after_historical_enabled_routes_to_websearch():
    """T10.5：websearch_agent 启用 + 触发条件成立 → 路由到 websearch"""
    _make_nodes, AgentState = _try_import_graph()

    fake_ws = MagicMock()
    fake_ws.should_trigger.return_value = (True, "wiki_chunks is empty")

    nodes = _make_nodes(MagicMock(), MagicMock(), MagicMock(), MagicMock(),
                        {}, None, diagnose_agent=None, websearch_agent=fake_ws)

    state = {"wiki_chunks": [], "reflection_score": 0.1}
    assert nodes["route_after_historical"](state) == "websearch"
    # should_trigger 被调用且传入了 wiki_chunks + reflect_score
    fake_ws.should_trigger.assert_called_once_with(
        wiki_chunks=[], reflect_score=0.1
    )


def test_t10_agent_state_has_phase3_fields():
    """T10.6：AgentState 暴露 diagnostic_chunks / websearch_chunks（节点与状态契约）"""
    _make_nodes, AgentState = _try_import_graph()

    keys = AgentState.__annotations__.keys()
    assert "diagnostic_chunks" in keys, "AgentState 必须有 diagnostic_chunks 字段"
    assert "websearch_chunks" in keys, "AgentState 必须有 websearch_chunks 字段"


def test_t8_default_config_disabled():
    """T8.3：config.yaml 中 agents.diagnose/websearch 默认 enabled=false（零回归兜底）"""
    import yaml
    cfg_path = ROOT / "config.yaml"
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)
    assert cfg["agents"]["diagnose"]["enabled"] is False, "diagnose 必须默认 disabled"
    assert cfg["agents"]["websearch"]["enabled"] is False, "websearch 必须默认 disabled"


# ============================================================
# Runner
# ============================================================

def run_all():
    import inspect
    funcs = [(name, obj) for name, obj in globals().items()
             if name.startswith("test_") and callable(obj)]
    passed, failed, skipped = 0, 0, 0
    for name, fn in funcs:
        try:
            fn()
            print(f"  [PASS] {name}")
            passed += 1
        except Exception as e:
            if "SKIPPED" in str(type(e).__name__) or "Skipped" in str(type(e).__name__):
                print(f"  [SKIP] {name}: {e}")
                skipped += 1
            else:
                print(f"  [FAIL] {name}: {e}")
                import traceback
                traceback.print_exc()
                failed += 1
    print(f"\n=== {passed} passed, {failed} failed, {skipped} skipped ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_all())
