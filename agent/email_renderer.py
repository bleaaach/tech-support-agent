"""邮件模板渲染器"""
from __future__ import annotations
import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .router import QuestionType

logger = logging.getLogger(__name__)

_TEMPLATE_MAP = {
    QuestionType.PARAM_QUERY: "param_query.md",
    QuestionType.COMPATIBILITY: "compatibility.md",
    QuestionType.TROUBLESHOOTING: "troubleshooting.md",
    QuestionType.HOWTO: "howto.md",
    QuestionType.TRANSFER: "transfer.md",
    QuestionType.GENERAL: "general.md",
}


def _detect_language(text: str, question: str = "") -> str:
    """根据文本内容检测语言，返回 'zh' | 'en'。

    优先用 question 语言判断（因为 answer 可能因 LLM prompt 失效而用错语言）。
    启发式：中文字符占比超过 15% 判定为中文，否则英文。
    """
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


class EmailRenderer:
    """邮件模板渲染器，支持中英双语自动切换"""

    def __init__(self, template_dir: str | Path | None = None):
        if template_dir is None:
            template_dir = Path(__file__).parent / "templates"

        self.template_dir = Path(template_dir)

        if self.template_dir.exists():
            self.env = Environment(
                loader=FileSystemLoader(str(self.template_dir)),
                autoescape=select_autoescape(["html", "xml"]),
            )
            self._use_file = True
            logger.info(f"Email templates loaded from: {self.template_dir}")
        else:
            self._use_file = False
            logger.warning(f"Template dir not found: {template_dir}, using fallback templates")

    def render(
        self,
        question: str,
        answer: str,
        sources: list[dict] | None = None,
        image_urls: list[str] | None = None,
        resource_urls: list[str] | None = None,
        qtype: QuestionType = QuestionType.GENERAL,
        answer_language: str = "zh",
    ) -> str:
        """将回答渲染为邮件格式

        Args:
            answer_language: 回答语言，'zh' | 'en'，用于模板选择中/英文标题和落款
        """
        sources = sources or []
        image_urls = image_urls or []
        resource_urls = resource_urls or []

        if self._use_file:
            template_name = _TEMPLATE_MAP.get(qtype, "general.md")
            try:
                tmpl = self.env.get_template(template_name)
                return tmpl.render(
                    question=question,
                    answer=answer,
                    sources=sources,
                    image_urls=image_urls,
                    resource_urls=resource_urls,
                    lang=answer_language,
                )
            except Exception as e:
                logger.error(f"Failed to load template {template_name}: {e}, falling back to inline")

        return self._render_fallback(question, answer, sources, image_urls, resource_urls, answer_language)

    def _render_fallback(
        self,
        question: str,
        answer: str,
        sources: list[dict],
        image_urls: list[str],
        resource_urls: list[str],
        lang: str,
    ) -> str:
        from jinja2 import Template as JinjaTemplate

        _fallback_zh = """**Seeed Studio 技术支持回复**

您好，

感谢您联系我们。以下是我们关于您咨询的问题的回复：

## 您的问题

{{ question }}

## 我们的回复

{{ answer }}

{% if sources %}
## 参考文档
{% for source in sources %}
- [{{ source.title }}]({{ source.url }})
{% endfor %}
{% endif %}

{% if image_urls %}
## 相关图片/原理图
{% for url in image_urls[:3] %}
- {{ url }}
{% endfor %}
{% endif %}

{% if resource_urls %}
## 相关资源
{% for url in resource_urls[:3] %}
- {{ url }}
{% endfor %}
{% endif %}

如有任何问题，欢迎直接回复此邮件。更多社区讨论和技术支持，请访问 [Seeed 论坛](https://forum.seeedstudio.com/) 或加入我们的 [Discord 社区](https://discord.gg/cpudkZmKb9)。

此致
Seeed Studio 技术支持团队
------------------------------------------------------------------
我们的工作时间为：周一至周五 9:00 AM - 6:00 PM GMT+8
关注我们：[LinkedIn](https://www.linkedin.com/company/seeed-studio/) | [Twitter/X](https://twitter.com/seeedstudio) | [YouTube](https://www.youtube.com/c/SeeedStudioOfficial) | [Facebook](https://www.facebook.com/SeeedStudio)"""

        _fallback_en = """**Seeed Studio Technical Support**

Hi there,

Thank you for contacting Seeed Studio Technical Support. Please find our response below.

## Your Question

{{ question }}

## Our Reply

{{ answer }}

{% if sources %}
## Reference Documentation
{% for source in sources %}
- [{{ source.title }}]({{ source.url }})
{% endfor %}
{% endif %}

{% if image_urls %}
## Related Diagrams / Schematics
{% for url in image_urls[:3] %}
- {{ url }}
{% endfor %}
{% endif %}

{% if resource_urls %}
## Related Resources
{% for url in resource_urls[:3] %}
- {{ url }}
{% endfor %}
{% endif %}

If you have any further questions, please feel free to reply to this email directly. For community discussion and peer-to-peer help, visit the [Seeed Forum](https://forum.seeedstudio.com/) or join our [Discord Community](https://discord.gg/cpudkZmKb9).

Best Regards!
Seeed Studio Technical Support Team
------------------------------------------------------------------
Our working hours are 9:00 AM - 6:00 PM GMT+8, Monday - Friday.
Follow us on [LinkedIn](https://www.linkedin.com/company/seeed-studio/) | [Twitter/X](https://twitter.com/seeedstudio) | [YouTube](https://www.youtube.com/c/SeeedStudioOfficial) | [Facebook](https://www.facebook.com/SeeedStudio)."""

        tmpl_str = _fallback_zh if lang == "zh" else _fallback_en
        tmpl = JinjaTemplate(tmpl_str)
        return tmpl.render(
            question=question,
            answer=answer,
            sources=sources,
            image_urls=image_urls,
            resource_urls=resource_urls,
        )


def render_email(
    question: str,
    answer: str,
    sources: list[dict] | None = None,
    image_urls: list[str] | None = None,
    resource_urls: list[str] | None = None,
    qtype: QuestionType = QuestionType.GENERAL,
    template_dir: str | None = None,
    answer_language: str = "zh",
) -> str:
    """快捷函数：渲染邮件"""
    renderer = EmailRenderer(template_dir=template_dir)
    return renderer.render(
        question=question,
        answer=answer,
        sources=sources,
        image_urls=image_urls,
        resource_urls=resource_urls,
        qtype=qtype,
        answer_language=answer_language,
    )
