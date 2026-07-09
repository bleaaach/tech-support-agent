"""邮件模板渲染器"""
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


class EmailRenderer:
    """邮件模板渲染器"""

    def __init__(self, template_dir: str | Path | None = None):
        # 优先使用 agent/templates 目录
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
    ) -> str:
        """将回答渲染为邮件格式"""
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
                )
            except Exception as e:
                logger.error(f"Failed to load template {template_name}: {e}")

        # 回退到内联模板
        from jinja2 import Template as JinjaTemplate
        _fallback = """**Seeed Studio 技术支持回复**

您好，

感谢您联系我们。以下是我们关于您咨询的问题的回复：

## {{ question }}

{{ answer }}

{% if sources %}
## 参考文档
{% for source in sources %}
- [{{ source.Title }}]({{ source.url }})
{% endfor %}
{% endif %}

此致
Seeed Studio 技术支持团队
"""
        tmpl = JinjaTemplate(_fallback)
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
    )

