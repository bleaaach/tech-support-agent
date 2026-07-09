"""Wiki 文档解析器 - 解析 MD/MDX 文件，提取 frontmatter + 正文 + 图片/链接"""
import re
import html
from pathlib import Path
from dataclasses import dataclass, field
from typing import Iterator


@dataclass
class WikiChunk:
    """单个文档块"""
    doc_id: str          # 文档唯一 ID（slug）
    title: str           # 文档标题
    description: str     # 文档描述
    slug: str            # URL slug
    keywords: list[str]  # 关键词
    category: str        # 文档分类路径
    chunk_text: str      # 当前块文本
    chunk_index: int     # 块序号
    total_chunks: int    # 总块数
    image_urls: list[str] = field(default_factory=list)   # 文档中的图片链接
    resource_urls: list[str] = field(default_factory=list) # Resources 链接（PDF/Schematic/Datasheet）
    wiki_url: str = ""   # Wiki 页面 URL
    last_update_date: str = ""
    last_update_author: str = ""


def _extract_urls_from_text(text: str) -> tuple[list[str], list[str]]:
    """从文本中提取图片链接和资源链接"""
    # Wiki 图片格式: https://files.seeedstudio.com/wiki/...
    wiki_img_pattern = r'https://files\.seeedstudio\.com/wiki/[^\s)"\'<>]+'
    wiki_imgs = re.findall(wiki_img_pattern, text)

    # Resource 链接（PDF / Schematic / Datasheet / Driver）
    resource_pattern = r'https?://[^\s()"\'<>]+\.(pdf|zip|bin|img|deb|rpm|tar\.gz|sh|run)(?:\?[^\s]*)?'
    resources = re.findall(resource_pattern, text, re.IGNORECASE)
    # 也匹配非扩展名链接如 Google Drive / GitHub releases
    resource_extra = re.findall(
        r'https?://(?:drive\.google\.com|github\.com/[^/\s]+/[^/\s]+/releases|seeed-studio\.com|files\.seeedstudio\.com)[^\s)"\'<>]+',
        text
    )

    return list(set(wiki_imgs)), list(set(resources + resource_extra))


def _chunk_text(text: str, chunk_size: int = 600, overlap: int = 150, min_len: int = 50) -> list[str]:
    """按段落分块，保留语义边界。
    特别处理 Resources 部分，确保它与上下文不分离。"""
    # 先按双换行分割段落
    paragraphs = re.split(r'\n\n+', text)
    chunks = []
    current = ""
    current_has_resources = False
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        
        # 检查是否包含 Resources 关键字
        is_resources_section = "resource" in para.lower() or para.startswith("## Resources") or (para.startswith("- [") and (".pdf" in para.lower() or ".zip" in para.lower()))
        
        # 如果当前段落是 Resources 相关内容，且已积累了不少文本
        if is_resources_section and len(current) > 200:
            # 先保存当前块
            if len(current.strip()) >= min_len:
                chunks.append(current.strip())
            current = para
            current_has_resources = True
            continue
        
        # 如果当前文本已经包含 Resources，新内容应该追加到当前块
        if current_has_resources and len(current) + len(para) <= chunk_size * 1.2:
            current += "\n" + para
            continue
            
        if len(current) + len(para) <= chunk_size:
            current += "\n" + para
            if is_resources_section:
                current_has_resources = True
        else:
            if len(current.strip()) >= min_len:
                chunks.append(current.strip())
            # overlap: 保留最后一段作为下一块开头（增加 overlap 保留 Resources 上下文）
            overlap_text = current[-overlap:] if len(current) > overlap else current
            current = overlap_text + "\n" + para
            current_has_resources = is_resources_section

    if len(current.strip()) >= min_len:
        chunks.append(current.strip())

    return chunks


def _slug_from_path(file_path: Path, root_path: Path) -> str:
    """从文件路径生成 doc_id"""
    rel = file_path.relative_to(root_path)
    # Edge/NVIDIA_Jetson/FAQs/How_to_Encrypt_the_Disk_for_Jetson.md
    parts = list(rel.parts)
    if parts and parts[-1].endswith(('.md', '.mdx')):
        parts[-1] = parts[-1].rsplit('.', 1)[0]
    return '/'.join(parts)


def _category_from_path(file_path: Path, root_path: Path) -> str:
    """从路径提取分类"""
    rel = file_path.relative_to(root_path)
    parts = list(rel.parts)
    if parts and parts[-1].endswith(('.md', '.mdx')):
        parts = parts[:-1]
    return '/'.join(parts)


def parse_wiki_file(file_path: Path, root_path: Path, chunk_size: int = 500, overlap: int = 100) -> list[WikiChunk]:
    """解析单个 Wiki 文件，返回 chunk 列表"""
    try:
        raw = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            raw = file_path.read_text(encoding="utf-8-sig")
        except Exception:
            return []

    # ---- 1. 解析 frontmatter ----
    frontmatter = {}
    body = raw

    if raw.startswith('---'):
        end = raw.find('\n---', 3)
        if end != -1:
            fm_text = raw[3:end]
            body = raw[end + 4:]

            for line in fm_text.split('\n'):
                if ':' in line:
                    key, _, val = line.partition(':')
                    key = key.strip().strip('"\' ')
                    val = val.strip().strip('"\' ')
                    if key and val:
                        frontmatter[key] = val

    title = frontmatter.get('title', file_path.stem.replace('_', ' '))
    description = frontmatter.get('description', '')
    slug = frontmatter.get('slug', '').strip('/')
    if not slug:
        slug = file_path.stem
    keywords = frontmatter.get('keywords', [])
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.strip('[]').split(',')]
    elif not isinstance(keywords, list):
        keywords = []

    last_update = frontmatter.get('last_update', {})
    if isinstance(last_update, dict):
        last_date = last_update.get('date', '')
        last_author = last_update.get('author', '')
    else:
        last_date = ''
        last_author = ''

    wiki_url = frontmatter.get('url', f'https://wiki.seeedstudio.com/{slug}/')

    # ---- 2. 清理正文 ----
    body = body.strip()

    # 移除 HTML 注释 <!-- -->
    body = re.sub(r'<!--.*?-->', '', body, flags=re.DOTALL)
    # 移除 Docusaurus 特有标签 :::tip :::note 等
    body = re.sub(r'^:::[\w]+\b.*?^:::', '', body, flags=re.MULTILINE | re.DOTALL)
    # 移除 React/MDX 组件 <Xxx ...> 但保留内容
    body = re.sub(r'<[A-Z][^>]*>', '', body)
    body = re.sub(r'</\w+>', '', body)
    # 移除 iframe
    body = re.sub(r'<iframe[^>]*>.*?</iframe>', '', body, flags=re.DOTALL)
    # 替换换行符为空格（后续再分块时用 \n\n）
    body = re.sub(r'\n{3,}', '\n\n', body)

    # ---- 3. 提取图片和资源链接 ----
    image_urls, resource_urls = _extract_urls_from_text(raw)
    # 去重
    image_urls = sorted(set(image_urls))
    resource_urls = sorted(set(resource_urls))

    # ---- 4. 分块 ----
    chunks_text = _chunk_text(body, chunk_size, overlap)

    # ---- 5. 构建 WikiChunk ----
    doc_id = _slug_from_path(file_path, root_path)
    category = _category_from_path(file_path, root_path)

    return [
        WikiChunk(
            doc_id=doc_id,
            title=title,
            description=description,
            slug=slug,
            keywords=keywords,
            category=category,
            chunk_text=chunk_text,
            chunk_index=i,
            total_chunks=len(chunks_text),
            image_urls=image_urls,
            resource_urls=resource_urls,
            wiki_url=wiki_url,
            last_update_date=last_date,
            last_update_author=last_author,
        )
        for i, chunk_text in enumerate(chunks_text)
    ]


def scan_wiki_docs(wiki_root: Path, extensions: tuple[str, ...] = ('.md', '.mdx')) -> Iterator[Path]:
    """扫描 Wiki 目录下所有文档"""
    for ext in extensions:
        yield from wiki_root.rglob(f'*{ext}')


def parse_all_docs(wiki_root: Path, chunk_size: int = 500, overlap: int = 100) -> list[WikiChunk]:
    """解析所有 Wiki 文档，返回完整 chunk 列表"""
    all_chunks = []
    for file_path in scan_wiki_docs(wiki_root):
        chunks = parse_wiki_file(file_path, wiki_root, chunk_size, overlap)
        all_chunks.extend(chunks)
    return all_chunks
