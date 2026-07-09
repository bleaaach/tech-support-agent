"""质量验证: 用 #343221 (overcurrent 真实工单) 做 blind test, 对比 LLM 回复 vs 真实 ZOHO 回复。"""
import json
import sys
import urllib.request


def post_chat(message: str) -> dict:
    req = urllib.request.Request(
        "http://localhost:8000/chat",
        data=json.dumps({"message": message, "session_id": "blind-343221"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


GROUND_TRUTH = {
    "ticket": "#343221",
    "category": "howto",
    "question_gist": "Jetson 显示 'system throttled due to over-current' (连了摄像头+键鼠)",
    "real_answer": """Dear Line,

The camera, mouse, and keyboard you have connected should not cause the device to enter an overcurrent protection state.

My initial guess is that the notification you're seeing might be a system message indicating that the device is running at a high temperature.
Please help confirming three things:
1. Your device model (SKU would be better) and the JetPack version installed on the device (cat /etc/nv_tegra_release)
2. A photo of the notification when it appears
3. If convenient, please use the jtop tool to verify whether the device is actually experiencing frequency throttling.""",
}


def parse_mail(ans: str) -> dict:
    """提取邮件结构化字段"""
    out = {}
    out["opens_with_greeting"] = "Hi" in ans.split("\n")[0:3][0] if "\n" in ans else ans.startswith("Hi") or "Hi" in ans[:50]
    out["mentions_sku"] = "SKU" in ans
    out["mentions_jetpack"] = "JetPack" in ans or "jetpack" in ans
    out["mentions_jtop"] = "jtop" in ans
    out["mentions_cat_release"] = "/etc/nv_tegra_release" in ans or "nv_tegra_release" in ans
    out["mentions_throttling"] = "throttl" in ans.lower()
    out["mentions_temperature_or_overcurrent"] = "temperatur" in ans.lower() or "over-current" in ans.lower() or "overcurrent" in ans.lower()
    out["requests_screenshot"] = "screenshot" in ans.lower() or "photo" in ans.lower() or "screenshot" in ans.lower() or "picture" in ans.lower()
    out["mentions_power_draw_cause_or_not"] = "5W" in ans or "power" in ans.lower() or "camera" in ans.lower()
    out["has_numbered_steps"] = any(f"{i}." in ans for i in range(1, 5)) or any(f"\n{i}." in ans for i in range(1, 5))
    out["has_seeed_signature"] = "Best Regards" in ans or "Seeed Technical Support" in ans
    return out


def main():
    # 用 paraphrase 触发, 避免直接拿 few-shot 抄
    test_question = (
        "Hi, I connected an IMX477 camera and a wireless keyboard/mouse to my reComputer J4012. "
        "After boot I see 'System throttled due to Over-current' on the screen. "
        "Could you tell me what's wrong and what to check?"
    )

    print("=" * 80)
    print(f"Blind test vs ticket {GROUND_TRUTH['ticket']}")
    print("=" * 80)
    print()
    print("Q:", test_question)
    print()
    print("-" * 80)
    print("REAL ZOHO agent reply:")
    print("-" * 80)
    print(GROUND_TRUTH["real_answer"])
    print()
    print("-" * 80)

    print("Getting LLM reply...")
    try:
        r = post_chat(test_question)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    llm_answer = r["answer"]
    print()
    print("-" * 80)
    print(f"LLM reply (type={r['question_type']}, sources={len(r.get('sources', []))}):")
    print("-" * 80)
    # safe print: encode to utf-8 and write to stdout as bytes
    sys.stdout.buffer.write(llm_answer.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.flush()

    # 显式求值但不作 noop
    _p = Path("data")  # placeholder to keep linter happy
    out_path = Path(__file__).resolve().parent.parent / "data" / "_llm_reply_343221.txt"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(llm_answer)
    sys.stdout.buffer.write(f"[saved] {out_path}\n".encode("utf-8"))

    # 结构化对比
    real_struct = parse_mail(GROUND_TRUTH["real_answer"])
    llm_struct = parse_mail(llm_answer)

    print("=" * 80)
    print("STRUCTURAL COMPARISON")
    print("=" * 80)
    print(f"{'指标':<40} {'Real':<8} {'LLM':<8}")
    print("-" * 60)
    for k in real_struct:
        print(f"{k:<40} {str(real_struct[k]):<8} {str(llm_struct[k]):<8}")

    # 评分
    matched = sum(1 for k in real_struct if real_struct[k] == llm_struct[k])
    total = len(real_struct)
    score = matched / total * 100
    print("-" * 60)
    print(f"结构匹配率: {matched}/{total} = {score:.0f}%")

    print()
    print("=" * 80)
    print("QUALITY NOTES")
    print("=" * 80)
    notes = []
    if llm_struct["mentions_sku"] and llm_struct["mentions_jtop"]:
        notes.append("✅ 关键诊断信息齐全 (SKU + jtop)")
    elif llm_struct["mentions_sku"] or llm_struct["mentions_jtop"]:
        notes.append("⚠️ 只复现了部分诊断项")
    else:
        notes.append("❌ 缺失关键诊断引导 (SKU / jtop)")

    if llm_struct["has_seeed_signature"]:
        notes.append("✅ 邮件签名块正确")
    else:
        notes.append("❌ 缺少 Seeed 签名")

    if llm_struct["has_numbered_steps"]:
        notes.append("✅ 步骤式结构")
    else:
        notes.append("⚠️ 没有编号步骤")

    if llm_struct["mentions_temperature_or_overcurrent"]:
        notes.append("✅ 复现了真因假设 (温度/电流)")
    else:
        notes.append("⚠️ 未复现真因假设")

    for n in notes:
        sys.stdout.buffer.write(n.encode("utf-8"))
        sys.stdout.buffer.write(b"\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()