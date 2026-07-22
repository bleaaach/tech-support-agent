"""LLM answer generator"""
from __future__ import annotations
import json
import logging
import os
from pathlib import Path
from typing import Any

from openai import OpenAI

from .retriever import RetrievedChunk
from .router import QuestionType
from .source_processor import process_sources

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a professional Jetson technical support engineer. Answer based ONLY on the provided documents.

LANGUAGE RULE (MUST FOLLOW):
- If the user's question contains ANY English words or sentences -> reply in ENGLISH only
- If the user's question is entirely in Chinese -> reply in CHINESE only
- All headings, body text, and closing sentences MUST match the question language
- NEVER mix languages in a single reply
- Example CORRECT: English question -> English answer (all English)
- Example WRONG: English question -> Chinese answer (NEVER do this)

Email body format:
- Write only the email body, go straight to the point (greeting is in the template)
- Do NOT write "Dear XXX" or "Thank you for contacting..." (template handles it)
- Do NOT write "Best regards" etc. at the end (template handles it)
- Keep concise, professional CS style

Troubleshooting questions:
- Briefly explain possible cause
- Give 2-4 key troubleshooting steps
- Ask for diagnostic info (logs, command output)
- List once, do not repeat

Device model follow-up:
- If user does NOT mention a specific device model (e.g. reComputer J4012, A206, R301, etc.)
  -> Add this line BEFORE the template closing signature:
    English: "Could you please let us know your device model and product name? (e.g. reComputer J4012, A206, R301, etc.)"
    Chinese: "请问您使用的是哪款设备？（例如：reComputer J4012、A206、R301 等）"
- If user already provided the device model, no need to ask
"""


def detect_language(text: str, question: str = "") -> str:
    """Detect language from text, returns 'zh' or 'en'.

    STRICT RULE: Always use the QUESTION language, never the answer language.
    Reason: LLM generation may occasionally ignore the system prompt language rule,
    but the question's original language is the ground truth for what the user expects.
    Heuristic: zh-char ratio > 15% => Chinese, else English.
    """
    # Priority: question language > text language
    # (text is LLM answer which may be wrong language, question is ground truth)
    for src in [question, text]:
        if not src:
            continue
        zh_chars = sum(1 for c in src if "\u4e00" <= c <= "\u9fff")
        total = len(src)
        if total == 0:
            continue
        if zh_chars / total > 0.15:
            return "zh"
    return "en"


_FEW_SHOT_DATA = None
_FEW_SHOT_MAX_CHARS_PER_SAMPLE = 200


def get_few_shot_data():
    global _FEW_SHOT_DATA
    if _FEW_SHOT_DATA is not None:
        return _FEW_SHOT_DATA
    project_root = Path(__file__).parent.parent
    fs_path = project_root / "data" / "few_shot_examples.json"
    if not fs_path.exists():
        logger.warning(f"Few-shot file not found: {fs_path}")
        _FEW_SHOT_DATA = {}
        return _FEW_SHOT_DATA
    try:
        with open(fs_path, encoding="utf-8") as f:
            _FEW_SHOT_DATA = json.load(f)
        logger.info(f"Loaded few-shot examples for {len(_FEW_SHOT_DATA)} qtypes from {fs_path}")
    except Exception as e:
        logger.error(f"Failed to load few-shot examples: {e}")
        _FEW_SHOT_DATA = {}
    return _FEW_SHOT_DATA


def build_few_shot_block(qtype, n=3):
    data = get_few_shot_data()
    if not data:
        return ""
    items = data.get(qtype.value, [])[:n]
    if not items:
        return ""
    blocks = ["=== Historical ticket examples (style/structure reference only, do not copy) ==="]
    for i, item in enumerate(items, 1):
        question = item.get("question", "").strip()
        answer = item.get("answer", "").strip()
        if len(answer) > _FEW_SHOT_MAX_CHARS_PER_SAMPLE:
            answer = answer[:_FEW_SHOT_MAX_CHARS_PER_SAMPLE].rstrip() + "..."
        blocks.append(
            f"\n--- Example {i} ---\n"
            f"Customer question: {question}\n"
            f"Historical reply: {answer}\n"
        )
    blocks.append("=== End of examples ===\n")
    return "\n".join(blocks)


def build_context(chunks):
    if not chunks:
        return "（No relevant documents retrieved）"
    lines = []
    for i, c in enumerate(chunks, 1):
        lines.append(f"--- Document {i} ---")
        lines.append(f"Title: {c.title}")
        lines.append(f"Category: {c.category}")
        lines.append(f"Source: {c.wiki_url}")
        if c.image_urls:
            lines.append(f"Related images: {', '.join(c.image_urls[:3])}")
        if c.resource_urls:
            lines.append(f"Related resources: {', '.join(c.resource_urls[:3])}")
        lines.append(f"Content: {c.chunk_text}")
        lines.append("")
    return "\n".join(lines)


def build_user_message(
    question, history, qtype, context, historical_replies=None
):
    type_hints = {
        QuestionType.PARAM_QUERY: "This is a parameter query. Please list specific parameters clearly.",
        QuestionType.COMPATIBILITY: "This is a compatibility question. Focus on specific models/versions/conditions.",
        QuestionType.TROUBLESHOOTING: "This is troubleshooting. Guide user step-by-step, ask for key status info.",
        QuestionType.HOWTO: "This is a how-to question. Give clear step-by-step instructions.",
        QuestionType.TRANSFER: "This needs transfer. Politely redirect to the right department.",
        QuestionType.GENERAL: "Give a professional, friendly answer.",
    }
    hint = type_hints.get(qtype, "")

    parts = []
    if history:
        parts.append(f"=== Conversation History ===\n{history}\n")
    parts.append(f"=== Current User Question ===\n{question}\n")
    parts.append(f"=== Question Type Hint ===\n{hint}\n")

    few_shot = build_few_shot_block(qtype, n=3)
    if few_shot:
        parts.append(few_shot)

    if historical_replies:
        parts.append("=== Retrieved similar historical replies (style/info reference only) ===")
        for j, h in enumerate(historical_replies, 1):
            txt = h.chunk_text.strip()
            if len(txt) > 400:
                txt = txt[:400].rstrip() + "..."
            parts.append(f"\n--- Historical reply {j} (similarity={h.score:.3f}, ticket={h.doc_id}) ---\n{txt}\n")
        parts.append("=== End of historical replies ===\n")

    parts.append(f"=== Retrieved Documents ===\n{context}")
    return "\n".join(parts)


class AnswerGenerator:
    def __init__(self, api_key: str = "", model: str = "deepseek-chat",
                 temperature: float = 0.3, base_url: str | None = None):
        if not api_key:
            api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
        self.client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
        self.model = model
        self.temperature = temperature

    @classmethod
    def from_config(cls):
        from .config import get_config
        cfg = get_config()
        provider = cfg.get("provider", "openai").lower()
        if provider == "deepseek":
            dc = cfg.get("deepseek", {})
            return cls(
                api_key=dc.get("api_key", ""),
                model=dc.get("llm_model", "deepseek-chat"),
                temperature=dc.get("llm_temperature", 0.3),
                base_url=dc.get("base_url", "https://api.deepseek.com/v1"),
            )
        oc = cfg["openai"]
        import os as _os
        model = oc.get("llm_model") or _os.environ.get("OPENAI_LLM_MODEL", "qwen3.7-plus")
        base_url = oc.get("base_url") or _os.environ.get("OPENAI_BASE_URL")
        return cls(
            api_key=oc.get("api_key", ""),
            model=model,
            temperature=oc.get("llm_temperature", 0.3),
            base_url=base_url,
        )

    def generate(self, question, chunks, history="", qtype=None, historical_replies=None):
        if qtype is None:
            qtype = QuestionType.GENERAL
        context = build_context(chunks)
        user_msg = build_user_message(question, history, qtype, context, historical_replies)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=self.temperature,
                max_tokens=6000,
            )
            answer = response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            answer = "Sorry, generation failed. Please try again later."

        sources = [
            {"title": c.title, "url": c.wiki_url, "score": round(c.score, 3)}
            for c in chunks if c.wiki_url
        ]

        # Process sources: dedup, language unification, grouping
        answer_lang = detect_language(answer, question=question)
        processed = process_sources(sources, user_language=answer_lang)
        grouped_sources = processed.get("grouped", [])
        flat_sources = processed.get("flat", sources)
        source_stats = processed.get("stats", {})

        return {
            "answer": answer,
            "sources": flat_sources,
            "grouped_sources": grouped_sources,
            "source_stats": source_stats,
            "question_type": qtype.value,
            "image_urls": sum([c.image_urls for c in chunks], [])[:5],
            "resource_urls": sum([c.resource_urls for c in chunks], [])[:5],
            "answer_language": answer_lang,
        }
