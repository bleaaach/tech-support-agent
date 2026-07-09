"""LLM 回答生成器"""
import json
import logging
import os
from pathlib import Path
from typing import Any

from openai import OpenAI

from .retriever import RetrievedChunk
from .router import QuestionType

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你是一个专业的 Jetson 技术支持工程师。请根据检索到的文档内容，用专业、耐心、清晰的方式回答用户问题。

规则：
1. 回答必须基于提供的文档内容，不要编造信息
2. 如果检索到的内容不足以回答，请明确说明，并给出一般性建议
3. 答案要清晰、有条理，优先使用表格和列表
4. 涉及操作步骤时，使用编号列表
5. 提及产品规格时，尽量引用 Wiki 原文
6. 英文产品名/型号保持原样，不翻译
7. 如果是故障排查，引导用户逐步排查，并询问关键信息（电源、网络、连接状态等）
"""

# Few-shot 样例懒加载
_FEW_SHOT_DATA: dict[str, list[dict]] | None = None
_FEW_SHOT_MAX_CHARS_PER_SAMPLE = 200  # 每条样例 answer 截断到 200 字以内 (控制 token 数)


def _get_few_shot_data() -> dict[str, list[dict]]:
    """懒加载 data/few_shot_examples.json (按 qtype 分组)"""
    global _FEW_SHOT_DATA
    if _FEW_SHOT_DATA is not None:
        return _FEW_SHOT_DATA
    # 项目根目录 = agent/ 的上一级
    project_root = Path(__file__).parent.parent
    fs_path = project_root / "data" / "few_shot_examples.json"
    if not fs_path.exists():
        log_msg = f"Few-shot file not found: {fs_path}, skipping few-shot injection"
        logger.warning(log_msg)
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


def _build_few_shot_block(qtype: QuestionType, n: int = 3) -> str:
    """根据 qtype 构造 few-shot 提示块。

    - 每类最多取 n 条
    - 每条样例 answer 截断到 _FEW_SHOT_MAX_CHARS_PER_SAMPLE 字以内
    - 若样例不存在 (空 dict)，返回空串
    """
    data = _get_few_shot_data()
    if not data:
        return ""
    items = data.get(qtype.value, [])[:n]
    if not items:
        return ""
    blocks = ["=== 历史工单参考样例 (仅参考风格与结构，不要直接复制) ==="]
    for i, item in enumerate(items, 1):
        question = item.get("question", "").strip()
        answer = item.get("answer", "").strip()
        if len(answer) > _FEW_SHOT_MAX_CHARS_PER_SAMPLE:
            answer = answer[:_FEW_SHOT_MAX_CHARS_PER_SAMPLE].rstrip() + "..."
        blocks.append(
            f"\n--- 示例 {i} ---\n"
            f"客户问题：{question}\n"
            f"历史回复：{answer}\n"
        )
    blocks.append("=== 样例结束 ===\n")
    return "\n".join(blocks)


def _build_context(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "（未检索到相关文档）"
    lines = []
    for i, c in enumerate(chunks, 1):
        lines.append(f"--- 文档 {i} ---")
        lines.append(f"标题：{c.title}")
        lines.append(f"分类：{c.category}")
        lines.append(f"来源：{c.wiki_url}")
        if c.image_urls:
            lines.append(f"相关图片：{', '.join(c.image_urls[:3])}")
        if c.resource_urls:
            lines.append(f"相关资源：{', '.join(c.resource_urls[:3])}")
        lines.append(f"内容：{c.chunk_text}")
        lines.append("")
    return "\n".join(lines)


def _build_user_message(
    question: str,
    history: str,
    qtype: QuestionType,
    context: str,
    historical_replies: list[RetrievedChunk] | None = None,
) -> str:
    type_hints = {
        QuestionType.PARAM_QUERY: "这是参数查询类问题，请优先列出具体参数，格式清晰。",
        QuestionType.COMPATIBILITY: "这是兼容性问题，请重点说明兼容的具体型号/版本/条件。",
        QuestionType.TROUBLESHOOTING: "这是故障排查类问题，请引导用户逐步排查，询问关键状态信息。",
        QuestionType.HOWTO: "这是操作指引类问题，请给出清晰的分步骤说明。",
        QuestionType.TRANSFER: "这是需要转接的问题，请礼貌说明转至相应部门。",
        QuestionType.GENERAL: "请给出专业、友好的回答。",
    }
    hint = type_hints.get(qtype, "")

    parts = []
    if history:
        parts.append(f"=== 对话历史 ===\n{history}\n")
    parts.append(f"=== 用户当前问题 ===\n{question}\n")
    parts.append(f"=== 问题类型提示 ===\n{hint}\n")

    # 注入 few-shot 样例
    few_shot = _build_few_shot_block(qtype, n=3)
    if few_shot:
        parts.append(few_shot)

    # 注入历史相似回复 (RAG-2)
    if historical_replies:
        parts.append("=== 检索到的历史相似回复 (仅参考风格与信息) ===")
        for j, h in enumerate(historical_replies, 1):
            txt = h.chunk_text.strip()
            if len(txt) > 400:
                txt = txt[:400].rstrip() + "..."
            parts.append(f"\n--- 历史回复 {j} (相似度={h.score:.3f}, 工单={h.doc_id}) ---\n{txt}\n")
        parts.append("=== 历史回复结束 ===\n")

    parts.append(f"=== 检索到的文档 ===\n{context}")
    return "\n".join(parts)


class AnswerGenerator:
    def __init__(
        self,
        api_key: str = "",
        model: str = "deepseek-chat",
        temperature: float = 0.3,
        base_url: str | None = None,
    ):
        if not api_key:
            api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
        self.client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
        self.model = model
        self.temperature = temperature

    @classmethod
    def from_config(cls) -> "AnswerGenerator":
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
        return cls(
            api_key=oc.get("api_key", ""),
            model=oc.get("llm_model", "glm-5.2"),
            temperature=oc.get("llm_temperature", 0.3),
            base_url=oc.get("base_url") or None,
        )

    def generate(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        history: str = "",
        qtype: QuestionType = QuestionType.GENERAL,
        historical_replies: list[RetrievedChunk] | None = None,
    ) -> dict[str, Any]:
        """生成回答，返回 dict 包含 answer + sources

        Args:
            question: 用户问题
            chunks: wiki 文档检索结果 (RAG-1)
            history: 对话历史
            qtype: 问题分类
            historical_replies: 历史相似回复 (RAG-2)，可选
        """
        context = _build_context(chunks)
        user_msg = _build_user_message(question, history, qtype, context, historical_replies)

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
            answer = "抱歉，生成回答时遇到问题，请稍后重试。"

        sources = [
            {"title": c.title, "url": c.wiki_url, "score": round(c.score, 3)}
            for c in chunks if c.wiki_url
        ]

        return {
            "answer": answer,
            "sources": sources,
            "question_type": qtype.value,
            "image_urls": sum([c.image_urls for c in chunks], [])[:5],
            "resource_urls": sum([c.resource_urls for c in chunks], [])[:5],
        }