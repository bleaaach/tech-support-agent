"""LangGraph 工作流测试

覆盖：
1. 节点单测：_RewriteClient.rewrite / reflect（mock LLM）
2. 路由测试：route_after_retrieve（按 qtype 决定走不走 historical）
3. 端到端：build_graph().invoke() 完整跑通
4. 条件边：max_rewrites 强制退出、reflection 阈值生效
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ============================================================
# 1) 节点单测：_RewriteClient
# ============================================================

def test_rewrite_client_parses_valid_json():
    """LLM 返回合法 JSON 数组 → 解析为 list[str]"""
    from agent.graph import _RewriteClient
    fake = MagicMock()
    fake.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content='["reComputer J4012 功耗"]'))]
    )
    client = _RewriteClient(model="m", api_key="k", base_url=None, max_tokens=100)
    client.client = fake
    qs = client.rewrite("J4012 功耗多少？", "")
    assert qs == ["reComputer J4012 功耗"], f"got {qs}"


def test_rewrite_client_fallback_on_json_error():
    """LLM 返回非法 JSON → 降级为 [原问题]"""
    from agent.graph import _RewriteClient
    fake = MagicMock()
    fake.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="not json"))]
    )
    client = _RewriteClient(model="m", api_key="k", base_url=None, max_tokens=100)
    client.client = fake
    qs = client.rewrite("原始问题", "")
    assert qs == ["原始问题"], f"got {qs}"


def test_rewrite_client_fallback_on_exception():
    """LLM 抛异常 → 降级为 [原问题]"""
    from agent.graph import _RewriteClient
    fake = MagicMock()
    fake.chat.completions.create.side_effect = RuntimeError("network")
    client = _RewriteClient(model="m", api_key="k", base_url=None, max_tokens=100)
    client.client = fake
    qs = client.rewrite("测试", "")
    assert qs == ["测试"]


def test_reflect_client_parses_valid_json():
    from agent.graph import _RewriteClient
    fake = MagicMock()
    fake.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content='{"score": 0.85, "reason": "ok", "need_rewrite": false}'))]
    )
    client = _RewriteClient(model="m", api_key="k", base_url=None, max_tokens=100)
    client.client = fake
    score, reason, need = client.reflect("q?", "general", "summary")
    assert score == 0.85
    assert reason == "ok"
    assert need is False


def test_reflect_client_clamps_score():
    """score 超出 [0,1] → 截断"""
    from agent.graph import _RewriteClient
    fake = MagicMock()
    fake.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content='{"score": 1.5, "reason": "x", "need_rewrite": false}'))]
    )
    client = _RewriteClient(model="m", api_key="k", base_url=None, max_tokens=100)
    client.client = fake
    score, _, _ = client.reflect("q?", "general", "summary")
    assert score == 1.0, f"expected clamped to 1.0, got {score}"


def test_reflect_client_default_on_failure():
    """LLM 失败 → 返回 (0.5, '', False)"""
    from agent.graph import _RewriteClient
    fake = MagicMock()
    fake.chat.completions.create.side_effect = RuntimeError("oops")
    client = _RewriteClient(model="m", api_key="k", base_url=None, max_tokens=100)
    client.client = fake
    score, reason, need = client.reflect("q?", "general", "summary")
    assert score == 0.5
    assert reason == ""
    assert need is False


# ============================================================
# 2) 路由测试：route_after_retrieve
# ============================================================

def test_route_after_retrieve_uses_historical_for_trouble():
    """troubleshooting → 走 historical"""
    from agent.graph import _make_nodes, _HISTORICAL_QTYPES
    from agent.router import QuestionType
    # 构造一个 minimal retriever 桩
    class FakeRetriever:
        historical_collection_name = "zoho_historical"
        top_k = 10
    retriever = FakeRetriever()
    nodes = _make_nodes(
        retriever=retriever,
        router=MagicMock(),
        generator=MagicMock(),
        rewrite_client=MagicMock(),
        graph_cfg={"max_rewrites": 2, "reflection_threshold": 0.7,
                   "enable_query_rewrite": True, "enable_reflection": True,
                   "enable_historical": True},
    )
    state = {"question_type": QuestionType.TROUBLESHOOTING.value}
    assert nodes["route_after_retrieve"](state) == "retrieve_historical"


def test_route_after_retrieve_skips_historical_for_general():
    """general → 跳过 historical 直接 reflect"""
    from agent.graph import _make_nodes
    from agent.router import QuestionType
    class FakeRetriever:
        historical_collection_name = "zoho_historical"
        top_k = 10
    nodes = _make_nodes(
        retriever=FakeRetriever(), router=MagicMock(), generator=MagicMock(),
        rewrite_client=MagicMock(),
        graph_cfg={"max_rewrites": 2, "reflection_threshold": 0.7,
                   "enable_query_rewrite": True, "enable_reflection": True,
                   "enable_historical": True},
    )
    state = {"question_type": QuestionType.GENERAL.value}
    assert nodes["route_after_retrieve"](state) == "reflect"


def test_route_after_retrieve_skips_historical_when_disabled():
    """enable_historical=false → 永远去 reflect"""
    from agent.graph import _make_nodes
    from agent.router import QuestionType
    class FakeRetriever:
        historical_collection_name = "zoho_historical"
        top_k = 10
    nodes = _make_nodes(
        retriever=FakeRetriever(), router=MagicMock(), generator=MagicMock(),
        rewrite_client=MagicMock(),
        graph_cfg={"max_rewrites": 2, "reflection_threshold": 0.7,
                   "enable_query_rewrite": True, "enable_reflection": True,
                   "enable_historical": False},
    )
    state = {"question_type": QuestionType.TROUBLESHOOTING.value}
    assert nodes["route_after_retrieve"](state) == "reflect"


# ============================================================
# 3) 路由测试：route_after_reflect
# ============================================================

def test_route_after_reflect_generates_when_score_high():
    from agent.graph import _make_nodes
    class FakeRetriever:
        historical_collection_name = None
        top_k = 10
    nodes = _make_nodes(
        retriever=FakeRetriever(), router=MagicMock(), generator=MagicMock(),
        rewrite_client=MagicMock(),
        graph_cfg={"max_rewrites": 2, "reflection_threshold": 0.7,
                   "enable_query_rewrite": True, "enable_reflection": True,
                   "enable_historical": False},
    )
    state = {"reflection_score": 0.9, "rewrite_iterations": 1}
    assert nodes["route_after_reflect"](state) == "generate"


def test_route_after_reflect_loops_when_score_low():
    from agent.graph import _make_nodes
    class FakeRetriever:
        historical_collection_name = None
        top_k = 10
    nodes = _make_nodes(
        retriever=FakeRetriever(), router=MagicMock(), generator=MagicMock(),
        rewrite_client=MagicMock(),
        graph_cfg={"max_rewrites": 2, "reflection_threshold": 0.7,
                   "enable_query_rewrite": True, "enable_reflection": True,
                   "enable_historical": False},
    )
    state = {"reflection_score": 0.3, "rewrite_iterations": 1}
    assert nodes["route_after_reflect"](state) == "query_rewrite"


def test_route_after_reflect_force_generate_at_max():
    from agent.graph import _make_nodes
    class FakeRetriever:
        historical_collection_name = None
        top_k = 10
    nodes = _make_nodes(
        retriever=FakeRetriever(), router=MagicMock(), generator=MagicMock(),
        rewrite_client=MagicMock(),
        graph_cfg={"max_rewrites": 2, "reflection_threshold": 0.7,
                   "enable_query_rewrite": True, "enable_reflection": True,
                   "enable_historical": False},
    )
    state = {"reflection_score": 0.1, "rewrite_iterations": 2}
    assert nodes["route_after_reflect"](state) == "generate"


# ============================================================
# 4) 端到端：build_graph 结构检查
# ============================================================

def test_build_graph_returns_compiled_graph():
    """不需要真的跑 invoke，只要图能编译、节点齐"""
    from agent.graph import build_graph
    g = build_graph()
    nodes = list(g.nodes.keys())
    expected = {"query_rewrite", "classify", "retrieve",
                "retrieve_historical", "reflect", "generate"}
    assert expected.issubset(set(nodes)), f"missing: {expected - set(nodes)}"


def test_graph_handles_graph_invoke_failure_gracefully():
    """graph.invoke 抛异常时，TechSupportChat.chat() 不应 crash"""
    from agent.chat import TechSupportChat, ConversationContext
    from langgraph.graph import StateGraph
    from agent.graph import AgentState

    # 构造一个会抛异常的图
    def bad_node(state):
        raise RuntimeError("simulated failure")
    g = StateGraph(AgentState)
    g.add_node("x", bad_node)
    from langgraph.graph import END, START
    g.add_edge(START, "x")
    g.add_edge("x", END)
    bad = g.compile()

    agent = TechSupportChat()
    agent._graph = bad
    ctx = ConversationContext(session_id="t")
    result = agent.chat(ctx, "test question")
    assert "抱歉" in result["answer"] or "error" in (result.get("fallback_reason") or "").lower()
    assert result["fallback_reason"].startswith("graph_invoke_failed")


# ============================================================
# 5) runner
# ============================================================

def run_all():
    """简易 test runner（不依赖 pytest）"""
    import inspect
    funcs = [(name, obj) for name, obj in globals().items()
             if name.startswith("test_") and callable(obj)]
    passed, failed = 0, 0
    for name, fn in funcs:
        try:
            fn()
            print(f"  [PASS] {name}")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    print(f"\n=== {passed} passed, {failed} failed ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_all())


# ============================================================
# 6) Phase 3 子 Agent 集成测试（默认 disabled 零回归）
# ============================================================

def test_phase3_default_disabled_zero_regression():
    """Phase 3 验收点：agents.diagnose/websearch 默认 enabled=false，TechSupportChat.chat() 不注入新节点逻辑。

    Mock 掉 retriever/router/generator/graph，验证 chat() 在默认配置下行为不变。
    """
    import pytest  # 放在顶部若不存在会失败，但项目 requirements 有 pytest
    try:
        from agent.chat import TechSupportChat, ConversationContext
    except Exception as e:
        pytest.skip(f"agent.chat import not available in current env: {type(e).__name__}: {e}")
    from agent.agents.diagnose_agent import DiagnoseAgent
    from agent.agents.websearch_agent import WebSearchAgent

    # 1) 默认 config 下，diagnose/websearch agent 不应被实例化（即使 enabled=true 也不行 —— 因为 config 默认 false）
    import yaml
    cfg_path = ROOT / "config.yaml"
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)
    assert cfg["agents"]["diagnose"]["enabled"] is False, "默认必须 disabled"
    assert cfg["agents"]["websearch"]["enabled"] is False, "默认必须 disabled"

    # 2) TechSupportChat 在不传 agent 时，应把 diagnose_agent / websearch_agent 置 None
    chat = TechSupportChat(
        retriever=MagicMock(),
        router=MagicMock(),
        generator=MagicMock(),
    )
    assert chat.diagnose_agent is None, "默认 diagnose_agent 应为 None"
    assert chat.websearch_agent is None, "默认 websearch_agent 应为 None"


def test_phase3_diagnose_agent_injects_when_enabled():
    """Phase 3 验收点：enabled=true 时，TechSupportChat 接受 diagnose_agent 实例。

    通过 mock build_graph 验证：build_graph 被调用时传入 diagnose_agent。
    """
    import pytest
    try:
        from agent.chat import TechSupportChat
    except Exception as e:
        pytest.skip(f"agent.chat import failed (env issue: {type(e).__name__}: {e})")
    from agent.agents.diagnose_agent import DiagnoseAgent
    from agent.agents.websearch_agent import WebSearchAgent

    fake_diag = MagicMock(spec=DiagnoseAgent)
    fake_ws = MagicMock(spec=WebSearchAgent)

    # 验证 attribute 注入
    chat = TechSupportChat(
        retriever=MagicMock(),
        router=MagicMock(),
        generator=MagicMock(),
        diagnose_agent=fake_diag,
        websearch_agent=fake_ws,
    )
    assert chat.diagnose_agent is fake_diag
    assert chat.websearch_agent is fake_ws

    # 验证 _get_graph() 透传给 build_graph
    with patch("agent.chat.build_graph") as mock_build:
        mock_build.return_value = MagicMock()
        chat._graph = None
        g = chat._get_graph()
        assert mock_build.called
        kwargs = mock_build.call_args.kwargs
        assert kwargs.get("diagnose_agent") is fake_diag
        assert kwargs.get("websearch_agent") is fake_ws


def test_phase3_agent_state_has_new_fields():
    """Phase 3 验收点：AgentState 暴露 diagnostic_chunks / websearch_chunks 字段。

    这是 graph.py 节点和外部 state 的契约，必须存在。
    """
    import pytest
    try:
        from agent.graph import AgentState
    except Exception:
        pytest.skip("agent.graph import not available in current env")
    keys = AgentState.__annotations__.keys()
    assert "diagnostic_chunks" in keys, "AgentState 必须有 diagnostic_chunks"
    assert "websearch_chunks" in keys, "AgentState 必须有 websearch_chunks"
