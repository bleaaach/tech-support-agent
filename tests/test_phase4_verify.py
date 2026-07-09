"""改造前后对比验证脚本。

Phase 4 验证:
  1) RAG-2 历史回复检索是否触发 (zoho_historical collection 已 ingest 1176 条)
  2) 历史回复是否被注入到 prompt
  3) 邮件格式与 few-shot 风格是否对齐
  4) 多类型问题覆盖 (compatibility / troubleshooting / howto / param_query / transfer)
"""
import json
import urllib.request
import sys


def post_chat(message: str, session_id: str = "verify-1") -> dict:
    req = urllib.request.Request(
        "http://localhost:8000/chat",
        data=json.dumps({"message": message, "session_id": session_id}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read())


def check_email_format(ans: str) -> dict:
    return {
        "starts_with_hi": ans.lstrip().startswith("Hi"),
        "has_question_section": "## Your Question" in ans,
        "has_reply_section": "## Our Reply" in ans,
        "has_reference_docs": "## Reference Documentation" in ans or "## Reference" in ans,
        "has_signature": "Best Regards" in ans or "Seeed Technical Support" in ans,
        "has_working_hours": "GMT+8" in ans or "working hours" in ans.lower(),
    }


def main():
    test_cases = [
        ("compatibility", "reComputer J4012 supports which JetPack version?"),
        ("troubleshooting", "My reComputer won't boot, LED is off"),
        ("howto", "How to flash JetPack 6.0 to reComputer J4012?"),
        ("param_query", "What is the power consumption of reComputer J4012?"),
        ("transfer", "I want to buy 100 units, can you give me a quote?"),
        ("real-world", "I tried to install CUDA but got 'package not found' error, what should I do?"),
    ]

    print("=" * 80)
    print("Phase 4 验证: 改造后的邮件输出质量 (deepseek-v4-pro + RAG-1 + RAG-2 + few-shot)")
    print("=" * 80)

    all_pass = True
    for tag, q in test_cases:
        print()
        print(f"[{tag}] Q: {q}")
        try:
            r = post_chat(q)
        except Exception as e:
            print(f"  ERROR: {e}")
            all_pass = False
            continue

        fmt = check_email_format(r.get("answer", ""))
        hist_count = sum(1 for s in r.get("sources", []) if s.get("category") == "historical_reply")
        wiki_count = len(r.get("sources", [])) - hist_count

        print(f"  Type: {r.get('question_type')}")
        print(f"  Format OK: {fmt}")
        print(f"  Sources: wiki={wiki_count}, historical={hist_count}")
        print(f"  Ref URLs: {len(r.get('resource_urls', []))}, Img URLs: {len(r.get('image_urls', []))}")

        # preview
        ans_preview = r.get("answer", "")[:300].replace("\n", " ")
        print(f"  Answer preview: {ans_preview}...")

        # 关键检查
        if not all(fmt.values()):
            print(f"  FORMAT FAIL")
            all_pass = False
        else:
            print(f"  ✓ format pass")

    print()
    print("=" * 80)
    print("OVERALL:", "PASS" if all_pass else "FAIL")
    print("=" * 80)
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()