"""Email renderer 测试"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.email_renderer import render_email, EmailRenderer
from agent.router import QuestionType


def test_renderer_basic():
    """测试邮件模板渲染"""
    print("=== Email Renderer 测试 ===\n")

    renderer = EmailRenderer()

    sources = [
        {"title": "J401 Wiki", "url": "https://wiki.seeedstudio.com/j401/"},
        {"title": "J401B Wiki", "url": "https://wiki.seeedstudio.com/j401b/"},
    ]
    image_urls = ["https://files.seeedstudio.com/wiki/j401.png"]
    resource_urls = ["https://files.seeedstudio.com/wiki/j401_spec.pdf"]

    print("--- Test: troubleshooting ---")
    result = render_email(
        question="设备无法启动，怎么排查？",
        answer="请按以下步骤操作：\n1. 检查电源\n2. 检查LED指示灯",
        sources=sources,
        image_urls=image_urls,
        resource_urls=resource_urls,
        qtype=QuestionType.TROUBLESHOOTING,
    )
    print(result.encode('utf-8', errors='replace').decode('utf-8'))
    print()
    assert "感谢您" in result or "您好" in result
    assert "J401" in result or "设备" in result


def test_all_question_types():
    """测试所有问题类型"""
    print("=== Test all question types ===\n")
    for qtype in QuestionType:
        result = render_email(
            question="Test",
            answer="Test answer",
            qtype=qtype,
        )
        print(f"[OK] {qtype.value}: {len(result)} chars")
        assert len(result) > 0


if __name__ == "__main__":
    test_renderer_basic()
    print("\n" + "=" * 50)
    test_all_question_types()
    print("\nAll tests passed!")
