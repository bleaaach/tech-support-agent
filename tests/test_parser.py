"""Parser 单元测试 - 验证 Wiki MD 文件解析"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.parser import parse_wiki_file, parse_all_docs, scan_wiki_docs


# 测试样例
SAMPLE_MD = """---
description: Test doc
title: Test Jetson Document
slug: /test_jetson
keywords:
  - Test
  - Jetson
  - reComputer
image: https://files.seeedstudio.com/wiki/test.png
url: https://wiki.seeedstudio.com/test_jetson/
last_update:
  date: 2026/1/1
  author: Tester
createdAt: '2026-01-01'
---

This is a test document about Jetson reComputer.

## Section 1
Some content here.

![test image](https://files.seeedstudio.com/wiki/test.png)

## Section 2
More content here.

:::tip
This is a tip.
:::

| Col1 | Col2 |
|------|------|
| A    | B    |

<iframe src="https://www.youtube.com/embed/xxx"></iframe>
"""


def test_parse_basic():
    """测试基本解析功能"""
    from pipeline.parser import _chunk_text, _extract_urls_from_text

    urls = _extract_urls_from_text(SAMPLE_MD)
    print(f"图片 URLs: {urls}")
    assert len(urls) > 0, "应提取到至少一个图片 URL"

    chunks = _chunk_text(SAMPLE_MD, chunk_size=200, overlap=30)
    print(f"分块数: {len(chunks)}")
    assert len(chunks) > 0, "应该分出至少一个块"


def test_parse_real_file():
    """测试解析真实 Wiki 文件"""
    sample_path = Path("D:/wiki-documents/sites/en/docs/Edge/NVIDIA_Jetson/Jetson_DevelopTool/Jetson_DevelopTool_Overview.md")
    if not sample_path.exists():
        print(f"SKIP: {sample_path} 不存在")
        return

    root = Path("D:/wiki-documents/sites/en/docs/Edge/NVIDIA_Jetson")
    chunks = parse_wiki_file(sample_path, root)
    print(f"\n文档: {chunks[0].title if chunks else 'N/A'}")
    print(f"分块数: {len(chunks)}")
    if chunks:
        c = chunks[0]
        print(f"Title: {c.title}")
        print(f"Description: {c.description[:80]}...")
        print(f"Slug: {c.slug}")
        print(f"Category: {c.category}")
        print(f"Keywords: {c.keywords}")
        print(f"Wiki URL: {c.wiki_url}")
        print(f"Image URLs count: {len(c.image_urls)}")
        print(f"Chunk text (first 200 chars): {c.chunk_text[:200]}")
        assert c.title, "Title 不能为空"
        assert c.chunk_text, "Chunk text 不能为空"


def test_scan_wiki():
    """扫描 Wiki 目录"""
    root = Path("D:/wiki-documents/sites/en/docs/Edge/NVIDIA_Jetson")
    if not root.exists():
        print(f"SKIP: {root} 不存在")
        return

    files = list(scan_wiki_docs(root))
    print(f"\n扫描到 {len(files)} 个文档")
    assert len(files) > 0, "至少应扫描到一个文档"

    # 解析所有
    all_chunks = parse_all_docs(root, chunk_size=500, overlap=100)
    print(f"总 chunk 数: {len(all_chunks)}")
    assert len(all_chunks) >= len(files), "每个文档至少应有一个 chunk"


if __name__ == "__main__":
    print("=== Parser 单元测试 ===\n")
    test_parse_basic()
    print("\n" + "=" * 50)
    test_parse_real_file()
    print("\n" + "=" * 50)
    test_scan_wiki()
    print("\n所有测试通过!")
