"""问题分类路由器"""
from __future__ import annotations
import json
import logging
from enum import Enum

from openai import OpenAI

logger = logging.getLogger(__name__)


class QuestionType(str, Enum):
    PARAM_QUERY = "param_query"       # 参数、规格查询
    COMPATIBILITY = "compatibility"   # 兼容性问题
    TROUBLESHOOTING = "troubleshooting"  # 故障排查
    HOWTO = "howto"                   # 操作指引
    GENERAL = "general"                # 一般问题
    TRANSFER = "transfer"             # 转接（非技术）


_PROMPT = """你是一个技术支持问题分类器。根据用户问题，从以下类型中选择最合适的一个：

- param_query: 参数、规格、技术参数查询（如"内存多大？"、"功耗多少W？"）
- compatibility: 模块、外设、软件兼容性（如"能接什么摄像头？"、"支持哪个 JetPack 版本？"）
- troubleshooting: 设备不工作、报错、异常排查（如"设备启动不了"、"刷机失败"、"摄像头没画面"）
- howto: 操作步骤、教程请求（如"怎么刷机？"、"如何配置？"）
- general: 一般性提问
- transfer: 投诉、售后、价格、商务问题（转销售/售后处理）

用户问题: {question}

只返回一个 JSON，不要有其他文字：
{{"type": "类型", "reason": "简短理由（1句话）"}}
"""


class QuestionRouter:
    def __init__(
        self,
        api_key: str = "",
        model: str = "deepseek-chat",
        base_url: str | None = None,
    ):
        if not api_key:
            import os
            api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
        self.client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
        self.model = model
        self.base_url = base_url

    @classmethod
    def from_config(cls) -> "QuestionRouter":
        from .config import get_config
        cfg = get_config()
        provider = cfg.get("provider", "openai").lower()
        if provider == "deepseek":
            dc = cfg.get("deepseek", {})
            return cls(
                api_key=dc.get("api_key", ""),
                model=dc.get("llm_model", "deepseek-chat"),
                base_url=dc.get("base_url", "https://api.deepseek.com/v1"),
            )
        oc = cfg["openai"]
        import os
        model = oc.get("llm_model") or os.environ.get("OPENAI_LLM_MODEL", "qwen3.7-plus")
        base_url = oc.get("base_url") or os.environ.get("OPENAI_BASE_URL")
        return cls(
            api_key=oc.get("api_key", ""),
            model=model,
            base_url=base_url,
        )

    def classify(self, question: str, history: str = "") -> QuestionType:
        """对问题进行分类（失败时重试 1 次）"""
        full_question = question
        if history:
            full_question = f"对话历史：\n{history}\n\n当前问题：{question}"

        raw_type = "general"
        for attempt in (1, 2):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "你是一个技术支持问题分类器。"},
                        {"role": "user", "content": _PROMPT.format(question=full_question)},
                    ],
                    temperature=0.0,
                    max_tokens=100,
                )
                text = (response.choices[0].message.content or "").strip()
                if not text:
                    raise ValueError(f"empty response on attempt {attempt}")
                data = json.loads(text)
                raw_type = data.get("type", "general").lower()
                logger.info(f"Question type: {raw_type} — {data.get('reason', '')}")
                break
            except Exception as e:
                if attempt == 1:
                    logger.warning(f"Classification attempt {attempt} failed: {e}, retrying once")
                else:
                    logger.error(f"Classification failed after retry: {e}, defaulting to general")
                    raw_type = "general"

        type_map = {
            "param_query": QuestionType.PARAM_QUERY,
            "compatibility": QuestionType.COMPATIBILITY,
            "troubleshooting": QuestionType.TROUBLESHOOTING,
            "howto": QuestionType.HOWTO,
            "general": QuestionType.GENERAL,
            "transfer": QuestionType.TRANSFER,
        }
        return type_map.get(raw_type, QuestionType.GENERAL)
