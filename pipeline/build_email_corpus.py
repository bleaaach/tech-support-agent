"""从 ZOHO 历史邮件单元构建训练语料。

输入: cleaned_ZOHO-email_units/cleaned_email_units/email_units.jsonl
输出 (写入 data/ 目录):
  - few_shot_examples.json: 按 QuestionType 分组的 few-shot 样例
  - historical_replies.jsonl: 全部 agent 回复 (供 RAG 方向 B embedding)
  - qa_pairs.jsonl: (customer 问 → agent 答) 配对 (供 B 方向检索端)

用法:
  python -m pipeline.build_email_corpus
"""
import json
import logging
import re
from collections import defaultdict
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


# ---- QuestionType 关键词分类规则 ----
# 与 agent/router.py 中的 QuestionType 对应
_QTYPE_KEYWORDS: dict[str, list[str]] = {
    "troubleshooting": [
        "error", "fail", "not work", "no work", "doesn't work", "does not work",
        "boot", "brick", "crash", "stuck", "hang", "freeze",
        "broken", "issue", "problem", "trouble", "difficulty",
        "can't", "cannot", "could not", "unable", "no image", "no display",
        "no video", "no sound", "no power", "no led", "not detected",
        "not recognized", "not showing", "not booting", "blackscreen", "blue screen",
    ],
    "param_query": [
        "spec", "specification", "dimension", "weight", "size",
        "power consumption", "watt", "voltage", "current",
        "what is", "what are", "how much", "how many", "how big", "how heavy",
        "datasheet", "drawing", "schematic", "connector", "pinout",
    ],
    "compatibility": [
        "support", "compatible", "compatibility", "jetpack", "version",
        "driver", "module", "peripheral", "camera", "sensor",
        "works with", "work with", "support which", "support what",
        "j401", "j4012", "j501", "j5012", "orin nano", "orin nx", "agx orin",
    ],
    "howto": [
        "how to", "how do", "how can", "tutorial", "guide", "steps",
        "instruction", "manual", "configure", "install", "setup",
        "flash", "boot", "deploy", "connect", "use", "get started",
    ],
    "transfer": [
        "order", "refund", "invoice", "warranty", "rma", "distributor",
        "digikey", "mouser", "arrow", "ship", "shipping", "tracking",
        "return", "replace", "replacement", "missing part", "missing",
        "purchase", "buy", "price", "quote", "quotation", "proforma",
        "commercial", "sales", "bulk", "distributor",
    ],
}

# 短问题（如纯问候）→ general
_GENERAL_HINTS = {"hi", "hello", "hey", "good morning", "good afternoon"}


def classify_message(text: str) -> str:
    """根据文本内容判断 QuestionType。

    注意: 这里用于 customer 消息分类, agent 回复不直接分类, 而是通过
    ticket_id 关联到前序 customer 问题。
    """
    if not text:
        return "general"
    t = text.lower().strip()
    # 纯问候
    if any(t.startswith(g) for g in _GENERAL_HINTS) and len(t) < 60:
        return "general"

    # 关键词命中: 优先级 transfer > troubleshooting > howto > compatibility > param_query > general
    priority = ["transfer", "troubleshooting", "howto", "compatibility", "param_query"]
    for qtype in priority:
        for kw in _QTYPE_KEYWORDS[qtype]:
            if kw in t:
                return qtype
    return "general"


# ---- 清洗函数 ----
_SIGNATURE_PATTERNS = [
    re.compile(r"^--+$", re.MULTILINE),
    re.compile(r"^Sent from my iPhone", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^Get Outlook for", re.IGNORECASE | re.MULTILINE),
]

# 已知样板签名块 (Seeed Tech Support 团队的固定签名)
_SEEED_SIGNATURE_MARKERS = [
    "Seeed Technical Support Team",
    "Seeed TechSupport Team",
    "Seeed Studio Technical Support Team",
    "Follow us on LinkedIn",
    "Our working hours are",
]


def _is_seeed_signature(text: str) -> bool:
    return any(marker in text for marker in _SEEED_SIGNATURE_MARKERS)


def _strip_signature(text: str) -> str:
    """剥离 Seeed 团队签名块 (LLM 仍会自己生成签名)。"""
    if not text:
        return text
    lines = text.splitlines()
    cut_at = None
    for i, line in enumerate(lines):
        if "----" in line and i > 0 and len(line) >= 3:
            cut_at = i
            break
    if cut_at is not None:
        return "\n".join(lines[:cut_at]).rstrip()
    return text


def _strip_quoted_history(text: str) -> str:
    """剥离 > 开头的引用行 (常见于 reply)。"""
    if not text:
        return text
    out_lines = []
    for line in text.splitlines():
        if line.lstrip().startswith(">"):
            break
        if "wrote:" in line and line.lstrip().startswith("On ") and "@" in line:
            break
        if re.match(r"^-+\s*Original Message\s*-+\s*$", line, re.IGNORECASE):
            break
        if re.match(r"^-+\s*Forwarded message\s*-+\s*$", line, re.IGNORECASE):
            break
        out_lines.append(line)
    return "\n".join(out_lines).rstrip()


def _normalize(text: str) -> str:
    """统一空白字符。"""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_reply(text: str) -> str:
    """清理 agent 回复: 去签名块、去引用行。"""
    t = _normalize(text)
    t = _strip_quoted_history(t)
    t = _strip_signature(t)
    return _normalize(t)


# ---- 加载 ----
def load_email_units(jsonl_path: Path) -> list[dict]:
    log.info(f"Loading email units from {jsonl_path}")
    units = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                units.append(json.loads(line))
            except json.JSONDecodeError as e:
                log.warning(f"Skip malformed line: {e}")
    log.info(f"Loaded {len(units)} email units")
    return units


# ---- 过滤 & 配对 ----
def filter_agent_replies(units: list[dict]) -> list[dict]:
    """筛选 agent 回复 (sender_role=agent, message_clean 非空, 长度≥20)。"""
    out = []
    for u in units:
        if u.get("sender_role") != "agent":
            continue
        raw = u.get("message_clean", "") or u.get("message_no_quote", "")
        if not raw:
            continue
        cleaned = clean_reply(raw)
        if len(cleaned) < 20:
            continue
        u_out = dict(u)
        u_out["message_cleaned"] = cleaned
        out.append(u_out)
    log.info(f"Filtered to {len(out)} agent replies (>=20 chars, cleaned)")
    return out


def build_qa_pairs(units: list[dict], agent_replies: list[dict]) -> list[dict]:
    """构建 (customer 问 → agent 答) 配对。

    配对规则: 同一 ticket_id 内, agent 回复前最近的 customer 消息作为"问题"。
    """
    # 按 ticket_id 分组, 按 reply_index_asc 排序
    by_ticket: dict[str, list[dict]] = defaultdict(list)
    for u in units:
        tid = u.get("ticket_id") or u.get("ticket_dir", "")
        if tid:
            by_ticket[tid].append(u)
    for tid in by_ticket:
        by_ticket[tid].sort(key=lambda x: x.get("reply_index_asc", 0))

    # 收集 agent 回复的 (ticket_id, reply_index_asc) 集合, 用于配对
    agent_index = {(u.get("ticket_id", ""), u.get("reply_index_asc", -1)) for u in agent_replies}

    pairs = []
    for tid, group in by_ticket.items():
        # 在每个 ticket 中, 找到 agent 回复, 然后回溯最近 customer 消息
        last_customer_msg = None
        for u in group:
            role = u.get("sender_role", "")
            text = u.get("message_clean", "") or u.get("message_no_quote", "")
            text = _normalize(text)
            text = _strip_quoted_history(text)
            text = _normalize(text)

            if role == "customer":
                if len(text) >= 10:
                    last_customer_msg = {
                        "content": text,
                        "subject": u.get("ticket_subject", ""),
                        "ticket_number": u.get("ticket_number", ""),
                    }
            elif role == "agent":
                key = (u.get("ticket_id", ""), u.get("reply_index_asc", -1))
                if key not in agent_index:
                    continue
                cleaned = clean_reply(u.get("message_clean", "") or u.get("message_no_quote", ""))
                if len(cleaned) < 20:
                    continue
                if not last_customer_msg:
                    continue
                pairs.append({
                    "ticket_id": u.get("ticket_id", ""),
                    "ticket_number": u.get("ticket_number", ""),
                    "ticket_subject": u.get("ticket_subject", ""),
                    "ticket_assignee": u.get("ticket_assignee", ""),
                    "ticket_status": u.get("ticket_status", ""),
                    "question": last_customer_msg["content"],
                    "question_subject": last_customer_msg["subject"],
                    "answer": cleaned,
                    "qtype": classify_message(last_customer_msg["content"]),
                    "assignee": u.get("sender_name", ""),
                })
    log.info(f"Built {len(pairs)} Q-A pairs")
    return pairs


# ---- Few-shot 样例 ----
def build_few_shot_examples(
    qa_pairs: list[dict],
    per_type: int = 4,
    min_answer_len: int = 80,
    max_answer_len: int = 600,
) -> dict[str, list[dict]]:
    """按 qtype 挑选高质量 few-shot 样例。

    质量标准:
      - 答案长度 80-600 字符 (太短 = 没内容, 太长 = 噪声)
      - 答案不以"Hi Dear" 之外的诡异开头
      - 优先选 longer answers (信息更丰富)
    """
    by_type: dict[str, list[dict]] = defaultdict(list)
    for p in qa_pairs:
        ans = p["answer"]
        if not (min_answer_len <= len(ans) <= max_answer_len):
            continue
        if len(p["question"]) < 20:
            continue
        by_type[p["qtype"]].append(p)

    out: dict[str, list[dict]] = {}
    for qtype, items in by_type.items():
        # 按答案长度降序, 选前 N 条
        items.sort(key=lambda x: len(x["answer"]), reverse=True)
        selected = []
        for it in items:
            sample = {
                "question": it["question"],
                "answer": it["answer"],
                "ticket_number": it["ticket_number"],
                "assignee": it["assignee"],
            }
            selected.append(sample)
            if len(selected) >= per_type:
                break
        out[qtype] = selected
        log.info(f"  {qtype}: {len(selected)} few-shot examples")
    return out


# ---- 主流程 ----
def main(
    input_path: str = "cleaned_ZOHO-email_units/cleaned_email_units/email_units.jsonl",
    output_dir: str = "data",
    per_type: int = 4,
) -> None:
    project_root = Path(__file__).parent.parent
    input_p = project_root / input_path
    out_p = project_root / output_dir
    out_p.mkdir(parents=True, exist_ok=True)

    # 1) 加载
    units = load_email_units(input_p)

    # 2) 筛选 agent 回复
    agent_replies = filter_agent_replies(units)

    # 3) 构建 Q-A 配对
    qa_pairs = build_qa_pairs(units, agent_replies)

    # 4) Few-shot 样例
    few_shot = build_few_shot_examples(qa_pairs, per_type=per_type)

    # 5) 写出
    # 5a) few_shot_examples.json
    few_shot_path = out_p / "few_shot_examples.json"
    with open(few_shot_path, "w", encoding="utf-8") as f:
        json.dump(few_shot, f, ensure_ascii=False, indent=2)
    log.info(f"Wrote {few_shot_path}")

    # 5b) historical_replies.jsonl (供 RAG B 方向 embedding)
    hist_path = out_p / "historical_replies.jsonl"
    with open(hist_path, "w", encoding="utf-8") as f:
        for u in agent_replies:
            rec = {
                "id": f"{u.get('ticket_id', '')}_{u.get('reply_index_asc', -1)}",
                "ticket_id": u.get("ticket_id", ""),
                "ticket_number": u.get("ticket_number", ""),
                "ticket_subject": u.get("ticket_subject", ""),
                "ticket_assignee": u.get("ticket_assignee", ""),
                "ticket_status": u.get("ticket_status", ""),
                "agent_name": u.get("sender_name", ""),
                "content": u["message_cleaned"],
                "raw": u.get("message_clean", ""),
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    log.info(f"Wrote {hist_path} ({len(agent_replies)} records)")

    # 5c) qa_pairs.jsonl (供 RAG B 方向 query 端 - 用 customer 问做检索)
    qa_path = out_p / "qa_pairs.jsonl"
    with open(qa_path, "w", encoding="utf-8") as f:
        for p in qa_pairs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    log.info(f"Wrote {qa_path} ({len(qa_pairs)} records)")

    # 6) 统计摘要
    log.info("=" * 60)
    log.info("Summary")
    log.info("=" * 60)
    log.info(f"  Total email units:        {len(units)}")
    log.info(f"  Agent replies (filtered): {len(agent_replies)}")
    log.info(f"  Q-A pairs:                {len(qa_pairs)}")
    log.info(f"  Few-shot by type:")
    for qtype, items in few_shot.items():
        log.info(f"    - {qtype}: {len(items)}")
    log.info(f"  Q-A pairs by qtype:")
    type_counts: dict[str, int] = defaultdict(int)
    for p in qa_pairs:
        type_counts[p["qtype"]] += 1
    for qtype, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
        log.info(f"    - {qtype}: {cnt}")


if __name__ == "__main__":
    main()
