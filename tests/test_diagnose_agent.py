"""Diagnose Agent 单元测试

覆盖：
1. 错误码 regex 匹配（含大小写不敏感、多码、跨模式）
2. qtype 触发过滤
3. enabled 开关
4. chunk_text 构造（排查步骤 / 参考文档渲染）
5. YAML 配置加载与编译
6. 异常降级（Qdrant 不可用、YAML 不存在）
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ============================================================
# 1) 错误码 regex 匹配
# ============================================================

def test_match_mc_err_with_hex_address():
    """MC_ERR 后跟 hex 地址 → 应匹配"""
    from agent.agents import DiagnoseAgent
    agent = DiagnoseAgent.from_config({"enabled": True})
    agent._qdrant_retriever = False  # 跳过 Qdrant
    out = agent.run("dmesg 显示 MC_ERR 0x14，重启也没用", qtype="troubleshooting")
    codes = [m.code for m in out.matched_error_codes]
    assert "MC_ERR" in codes, f"expected MC_ERR, got {codes}"
    assert out.diagnostic_chunks, "expected at least 1 chunk"
    assert "MC_ERR" in out.diagnostic_chunks[0]["chunk_text"]


def test_match_mc_err_with_decimal():
    """MC_ERR 后跟十进制 → 应匹配"""
    from agent.agents import DiagnoseAgent
    agent = DiagnoseAgent.from_config({"enabled": True})
    agent._qdrant_retriever = False
    out = agent.run("MC_ERR 20", qtype="troubleshooting")
    codes = [m.code for m in out.matched_error_codes]
    assert "MC_ERR" in codes


def test_match_xusb_case_insensitive():
    """tegra_xusb 大小写不敏感 → 都应匹配"""
    from agent.agents import DiagnoseAgent
    agent = DiagnoseAgent.from_config({"enabled": True})
    agent._qdrant_retriever = False
    for variant in ["TEGRA_XUSB FAIL", "tegra_xusb fail", "Tegra_xUsb disconnect"]:
        out = agent.run(variant, qtype="troubleshooting")
        codes = [m.code for m in out.matched_error_codes]
        assert "TEGRA_XUSB" in codes, f"variant {variant!r} did not match: {codes}"


def test_match_multiple_codes_in_one_message():
    """同一条消息含多个错误码 → 都应识别"""
    from agent.agents import DiagnoseAgent
    agent = DiagnoseAgent.from_config({"enabled": True})
    agent._qdrant_retriever = False
    out = agent.run(
        "tegraflash FAIL 烧录不上，dmesg 显示 MC_ERR 0x14",
        qtype="troubleshooting",
    )
    codes = {m.code for m in out.matched_error_codes}
    assert "FLASH" in codes
    assert "MC_ERR" in codes


def test_match_i2c_timeout():
    """i2c timeout → 应匹配"""
    from agent.agents import DiagnoseAgent
    agent = DiagnoseAgent.from_config({"enabled": True})
    agent._qdrant_retriever = False
    out = agent.run("i2c-1: timeout 摄像头没反应", qtype="troubleshooting")
    codes = [m.code for m in out.matched_error_codes]
    assert "I2C" in codes


def test_match_camera_ioctl():
    """V4L2 / Camera ioctl fail → 应匹配"""
    from agent.agents import DiagnoseAgent
    agent = DiagnoseAgent.from_config({"enabled": True})
    agent._qdrant_retriever = False
    out = agent.run("V4L2 ioctl fail 摄像头初始化失败", qtype="troubleshooting")
    codes = [m.code for m in out.matched_error_codes]
    assert "CAM_ERR_IOCTL" in codes, f"got {codes}"


def test_no_match_for_irrelevant_text():
    """无关消息 → 不应匹配任何错误码"""
    from agent.agents import DiagnoseAgent
    agent = DiagnoseAgent.from_config({"enabled": True})
    agent._qdrant_retriever = False
    out = agent.run("reComputer J4012 的 JetPack 版本是多少？", qtype="troubleshooting")
    assert out.matched_error_codes == []
    assert out.diagnostic_chunks == []
    assert out.fallback_hint  # 应该有提示信息


# ============================================================
# 2) qtype 触发过滤
# ============================================================

def test_non_trigger_qtype_returns_empty():
    """非 trigger qtype → 返回空 + 提示"""
    from agent.agents import DiagnoseAgent
    agent = DiagnoseAgent.from_config({"enabled": True})
    agent._qdrant_retriever = False
    out = agent.run("MC_ERR 0x14", qtype="howto")
    assert out.matched_error_codes == []
    assert "qtype" in out.fallback_hint


def test_trigger_qtypes_can_be_customized():
    """trigger_qtypes 可配置"""
    from agent.agents import DiagnoseAgent
    agent = DiagnoseAgent.from_config(
        {"enabled": True, "trigger_qtypes": ["howto", "general"]}
    )
    agent._qdrant_retriever = False
    out = agent.run("MC_ERR 0x14", qtype="howto")
    assert "MC_ERR" in [m.code for m in out.matched_error_codes]


# ============================================================
# 3) enabled 开关
# ============================================================

def test_disabled_agent_returns_empty():
    """enabled=false → 完全不工作"""
    from agent.agents import DiagnoseAgent
    agent = DiagnoseAgent.from_config({"enabled": False})
    out = agent.run("MC_ERR 0x14", qtype="troubleshooting")
    assert out.matched_error_codes == []
    assert "disabled" in out.fallback_hint.lower()


# ============================================================
# 4) chunk_text 构造
# ============================================================

def test_chunk_text_includes_troubleshooting_steps():
    """chunk_text 应包含排查步骤"""
    from agent.agents import DiagnoseAgent
    agent = DiagnoseAgent.from_config({"enabled": True})
    agent._qdrant_retriever = False
    out = agent.run("MC_ERR 0x14", qtype="troubleshooting")
    text = out.diagnostic_chunks[0]["chunk_text"]
    assert "排查步骤" in text
    assert "tegrastats" in text


def test_chunk_text_severity_in_metadata():
    """chunk_text 应标注严重程度"""
    from agent.agents import DiagnoseAgent
    agent = DiagnoseAgent.from_config({"enabled": True})
    agent._qdrant_retriever = False
    out = agent.run("MC_ERR 0x14", qtype="troubleshooting")
    meta = out.diagnostic_chunks[0]["_diagnose_meta"]
    assert meta["severity"] == "critical"
    assert meta["code"] == "MC_ERR"


def test_chunk_text_sorted_by_severity():
    """多码时 chunks 应按严重程度排序（critical 在前）"""
    from agent.agents import DiagnoseAgent
    agent = DiagnoseAgent.from_config({"enabled": True})
    agent._qdrant_retriever = False
    out = agent.run(
        "MC_ERR 0x14 同时 ETH0 link down",
        qtype="troubleshooting",
    )
    if len(out.diagnostic_chunks) >= 2:
        first_sev = out.diagnostic_chunks[0]["_diagnose_meta"]["severity"]
        assert first_sev == "critical", f"first chunk should be critical, got {first_sev}"


# ============================================================
# 5) YAML 加载与异常降级
# ============================================================

def test_yaml_loads_all_10_codes():
    """默认 YAML 应加载 10 个错误码"""
    from agent.agents import DiagnoseAgent
    agent = DiagnoseAgent.from_config({"enabled": True})
    assert len(agent._code_patterns) == 10, \
        f"expected 10 patterns, got {len(agent._code_patterns)}"


def test_yaml_not_found_graceful():
    """YAML 不存在 → 仍能构造 agent，但 patterns 为空"""
    from agent.agents import DiagnoseAgent
    agent = DiagnoseAgent(
        enabled=True,
        error_codes_db="data/nonexistent.yaml",
    )
    assert agent._code_patterns == []
    # 运行也不报错
    out = agent.run("MC_ERR 0x14", qtype="troubleshooting")
    assert out.matched_error_codes == []


def test_qdrant_unavailable_graceful():
    """Qdrant 不可用 → chunks 仍能构造（仅元数据）"""
    from agent.agents import DiagnoseAgent
    agent = DiagnoseAgent.from_config({"enabled": True})
    # 强制 Qdrant 不可用
    agent._qdrant_retriever = False
    out = agent.run("MC_ERR 0x14", qtype="troubleshooting")
    assert len(out.diagnostic_chunks) == 1
    # 没有 wiki_url 兜底，但 chunk_text 完整
    assert "排查步骤" in out.diagnostic_chunks[0]["chunk_text"]


# ============================================================
# 6) 端到端：__main__ CLI 入口
# ============================================================

def test_cli_invocation(capsys):
    """CLI 入口能跑通"""
    import subprocess

    result = subprocess.run(
        ["python3", "-m", "agent.agents.diagnose_agent",
         "--message", "MC_ERR 0x14 怎么处理？",
         "--qtype", "troubleshooting",
         "--no-qdrant"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    out = result.stdout
    assert "MC_ERR" in out
    assert "matched_codes" in out


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))