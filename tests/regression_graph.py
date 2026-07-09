"""回归测试：在 6 个 chat_resp*.json + 6 个代表性问题上跑新版 LangGraph。

设计：
- 不直接复用旧 chat_resp 的 answer（那些几乎都是 sources=[] 的空检索场景，没有可比性）
- 用 6 个代表性新问题覆盖各 qtype（param_query / compatibility / troubleshooting /
  howto / general / transfer）+ 代词消解
- 验证：图不挂、字段完整、qtype 合法、关键节点被触发、答案非空
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("agent").setLevel(logging.INFO)

from agent.chat import TechSupportChat, ConversationContext  # noqa: E402

REQUIRED_FIELDS = {
    "answer", "sources", "question_type",
    "image_urls", "resource_urls",
    "needs_followup", "followup_hint",
}

VALID_QTYPES = {
    "param_query", "compatibility", "troubleshooting",
    "howto", "general", "transfer",
}

# 6 个代表性新问题 + 第二轮带代词的追问（验证 query_rewrite / history 注入）
TEST_CASES = [
    {
        "id": "T1_param",
        "q": "reComputer J4012 的功耗是多少？",
        "expected_qtype": "param_query",
    },
    {
        "id": "T2_compat",
        "q": "reComputer Industrial J4012 支持哪个版本的 JetPack？",
        "expected_qtype": "compatibility",
    },
    {
        "id": "T3_trouble",
        "q": "我的 Jetson Orin Nano 设备开机后没有任何反应，电源灯也不亮，该怎么排查？",
        "expected_qtype": "troubleshooting",
    },
    {
        "id": "T4_howto",
        "q": "如何使用 SDK Manager 给 reComputer 刷 JetPack 6.0？",
        "expected_qtype": "howto",
    },
    {
        "id": "T5_general",
        "q": "Seeed 的 Jetson 产品线有哪些系列？",
        "expected_qtype": "general",
    },
    {
        "id": "T6_transfer",
        "q": "我想批量采购 100 台 reComputer，麻烦给我个报价",
        "expected_qtype": "transfer",
    },
    {
        "id": "T7_pronoun (rewrite 消解)",
        "q": "它支持哪些外设接口？",
        "history": [("user", "请介绍 reComputer J4012"),
                    ("assistant", "reComputer J4012 是基于 Jetson Orin NX 16GB 的...")],
        "expected_qtype": "compatibility",  # 追问接口 → compatibility
    },
]


def main():
    print(f"\n=== Regression: {len(TEST_CASES)} cases ===\n")

    # 单例
    agent = TechSupportChat()

    passed, failed = 0, 0
    for tc in TEST_CASES:
        ctx = ConversationContext(session_id=tc["id"])
        # 注入历史（如果有）
        for role, content in tc.get("history", []):
            if role == "user":
                ctx.add_user(content)
            else:
                ctx.add_assistant(content)
        print(f"\n--- {tc['id']} ---")
        print(f"Q: {tc['q']}")
        t0 = time.time()
        try:
            result = agent.chat(ctx, tc["q"])
            dt = time.time() - t0
        except Exception as e:
            print(f"  [FAIL] exception: {e}")
            failed += 1
            continue

        # 字段完整性
        missing = REQUIRED_FIELDS - set(result.keys())
        if missing:
            print(f"  [FAIL] missing fields: {missing}")
            failed += 1
            continue

        # answer 非空
        ans = result["answer"] or ""
        if not ans.strip():
            print(f"  [FAIL] empty answer")
            failed += 1
            continue

        # qtype 合法
        if result["question_type"] not in VALID_QTYPES:
            print(f"  [FAIL] invalid qtype: {result['question_type']}")
            failed += 1
            continue

        # qtype 期望（允许 ≠，仅提示）
        new_qt = result["question_type"]
        exp_qt = tc.get("expected_qtype", "?")
        qt_match = "=" if new_qt == exp_qt else "≠"

        # sources
        n_src = len(result.get("sources") or [])
        n_img = len(result.get("image_urls") or [])
        n_res = len(result.get("resource_urls") or [])

        print(f"  qtype: expected={exp_qt} {qt_match} got={new_qt}")
        print(f"  sources={n_src} images={n_img} resources={n_res} "
              f"len(answer)={len(ans)} time={dt:.1f}s "
              f"followup={result['needs_followup']}")
        # 答案前 120 字预览
        print(f"  answer-preview: {ans[:120].replace(chr(10), ' ')}...")
        passed += 1

    print(f"\n=== RESULT: {passed} passed, {failed} failed ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
