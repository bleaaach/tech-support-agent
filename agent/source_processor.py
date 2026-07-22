"""Reference document processor: deduplication, language normalization, and grouping.

Usage:
    from .source_processor import process_sources
    processed = process_sources(raw_sources, user_language="zh")

Key features:
1. Deduplication: normalize by doc_id / URL path / title, keep highest score
2. Language unification: prefer user's language version, strip mixed-language prefixes
3. Product grouping: group by product category from URL/path metadata
4. Relevance sorting: sort within groups by score, groups by relevance
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

logger = __import__("logging").getLogger(__name__)


# ---- Language normalization ----

_STRIP_PREFIX_RE = re.compile(
    r"^(?:(?:zh[-_]?CN|中文|英文|en|US)\s*[-._/\\]*\s*)+",
    re.IGNORECASE,
)
_SITE_LANG_RE = re.compile(r"/(zh-CN|zh|en|ja|es|pt-BR)/")


def normalize_title(title: str) -> str:
    """Strip language prefixes/suffixes and normalize whitespace.

    Examples:
        "zh-CN_reComputer J401 Getting Started" -> "reComputer J401 Getting Started"
        "中文_刷写 Jetpack" -> "刷写 Jetpack"
        "Flash Jetpack || Interfaces Usage" -> "Flash Jetpack | Interfaces Usage"
    """
    if not title:
        return ""
    t = title.strip()
    # Strip leading language prefixes
    t = _STRIP_PREFIX_RE.sub("", t)
    # Normalize separators
    t = re.sub(r"\s*[-._|]+\s*", " | ", t)
    return t.strip()


def extract_lang_from_url(url: str) -> Optional[str]:
    """Extract language code from URL path (e.g., /zh-CN/docs/... -> zh)."""
    m = _SITE_LANG_RE.search(url)
    if m:
        lang = m.group(1)
        if lang.startswith("zh"):
            return "zh"
        return lang
    return None


# ---- Deduplication ----

def _doc_id_key(src: Dict) -> str:
    """Build a stable dedup key from doc_id, URL path, and title."""
    doc_id = src.get("doc_id", "") or ""
    url = src.get("wiki_url", "") or ""
    title = src.get("title", "") or ""

    # For SAG results, doc_id may contain chunk prefix - extract base
    base_doc = re.sub(r"::chunk:\d+$", "", doc_id)

    # Extract path from URL as secondary key
    path = ""
    if url:
        # Extract path after domain
        m = re.search(r"(?:wiki\.seeedstudio\.com|seeed\.studio\.com)(/.*)", url)
        if m:
            path = m.group(1)

    return f"{base_doc}|{path}|{normalize_title(title)}"


def deduplicate_sources(sources: List[Dict]) -> List[Dict]:
    """Deduplicate sources by doc_id + URL path + normalized title.

    Strategy:
    - Build dedup key per source
    - Keep entry with highest score among duplicates
    - Preserve order (first occurrence wins tie)
    """
    seen: Dict[str, Dict] = {}
    for src in sources:
        key = _doc_id_key(src)
        score = float(src.get("score", 0.0))
        if key not in seen:
            seen[key] = src
        elif score > float(seen[key].get("score", 0.0)):
            seen[key] = src
    return list(seen.values())


# ---- Product grouping ----

# URL path patterns -> product group name
_PRODUCT_PATTERNS: List[tuple] = [
    # Robotics / Industrial
    (r"/reComputer_Jetson_Series/reComputer_Industrial/", "reComputer Industrial"),
    (r"/reComputer_Jetson_Series/reComputer_J401", "reComputer J401"),
    (r"/reComputer_Jetson_Series/reComputer_J401B", "reComputer J4012"),
    (r"/Carrier_Boards/(?:Robotics_)?J401[^B]", "Robotics J401 Carrier"),
    (r"/Carrier_Boards/Robotics_J401", "Robotics J401 Carrier"),
    (r"/Carrier_Boards/J401/", "J401 Carrier Board"),
    (r"/Carrier_Boards/Mini_J401/", "Mini J401 Carrier"),
    (r"/reComputer_Jetson_Series/reComputer_Mini_J401", "reComputer Mini J401"),
    (r"/Robotics_J501/", "Robotics J501"),
    (r"/reComputer_Jetson_Series/reComputer_R1000", "reComputer R1000"),
    (r"/reComputer_Jetson_Series/reComputer_R3000", "reComputer R3000"),
    # GMSL / Camera
    (r"/GMSL_Camera_Driver/", "GMSL Camera"),
    (r"/A603/", "A603 GMSL Board"),
    (r"/A205/", "A205 AI Acceleration"),
    (r"/A206/", "A206 AI Acceleration"),
    (r"/A405/", "A405 AI Acceleration"),
    # reServer
    (r"/reServer/", "reServer Industrial"),
    # Edge AI / Raspberry Pi
    (r"/Edge_AI_Computer/reComputer_Industrial_R2", "reComputer Industrial R2xxx"),
    (r"/Edge_AI_Computer/reComputer_Industrial_R1", "reComputer Industrial R1xxx"),
    # reComputer Classic / Nano
    (r"/reComputer_Classic/", "reComputer Classic"),
    (r"/reComputer_Nano/", "reComputer Nano"),
    # Wiki / FAQ
    (r"/wiki/", "General Wiki"),
    (r"/FAQ/", "FAQ"),
    # Jetson SoM / Module
    (r"/Jetson/", "Jetson SoM"),
]

_FALLBACK_RE = re.compile(r"/([^/]+)/[^/]*$")


def _infer_product_group(url: str, title: str) -> str:
    """Infer product group from URL path and title."""
    for pattern, group_name in _PRODUCT_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            return group_name
    # Fallback: use title's first meaningful segment (skip language codes)
    if title:
        # Strip language prefixes
        clean_title = _STRIP_PREFIX_RE.sub("", title).strip()
        # Use first 2-3 words as group name
        words = clean_title.split()[:3]
        if words:
            return " ".join(words)[:40]
    return "Documentation"


def _infer_doc_type(url: str, title: str) -> str:
    """Infer document type from URL and title."""
    lower_url = url.lower()
    lower_title = title.lower()

    if any(k in lower_url or k in lower_title for k in ["getting_start", "入门", "开始"]):
        return "Getting Started"
    if any(k in lower_url or k in lower_title for k in ["flash", "刷写", "烧写"]):
        return "Flash Guide"
    if any(k in lower_url or k in lower_title for k in ["interfaces", "接口", "hardware"]):
        return "Interfaces Usage"
    if any(k in lower_url or k in lower_title for k in ["troubleshoot", "故障", "排查"]):
        return "Troubleshooting"
    if any(k in lower_url or k in lower_title for k in ["spec", "specification", "规格"]):
        return "Specifications"
    if any(k in lower_url or k in lower_title for k in ["driver", "驱动"]):
        return "Driver Guide"
    if any(k in lower_url or k in lower_title for k in ["deployment", "部署"]):
        return "Deployment Guide"
    if any(k in lower_url or k in lower_title for k in ["_faq", "FAQ"]):
        return "FAQ"
    return "Documentation"


# ---- Language version unification ----

_SITE_PREFIX_RE = re.compile(
    r"^(?:https?://)?(?:wiki\.seeedstudio\.com|seeed\.studio\.com)/",
    re.IGNORECASE,
)
_LANG_PATH_RE = re.compile(r"/(zh-CN|en|ja|es|pt-BR)/")


def _extract_path_without_lang(url: str) -> str:
    """Extract path without language code for matching across language versions."""
    return _LANG_PATH_RE.sub("/", url)


def _is_same_doc(url1: str, url2: str) -> bool:
    """Check if two URLs point to the same document (different language versions)."""
    # Normalize URLs
    p1 = _extract_path_without_lang(_SITE_PREFIX_RE.sub("", url1))
    p2 = _extract_path_without_lang(_SITE_PREFIX_RE.sub("", url2))
    return p1 == p2


def unify_language_versions(sources: List[Dict], preferred_lang: str = "zh") -> List[Dict]:
    """Pick one document per logical page, preferring user's language.

    For documents that exist in multiple language versions:
    - Keep the version matching preferred_lang
    - If none found, keep the first occurrence
    """
    seen_paths: Dict[str, List[Dict]] = {}
    for src in sources:
        url = src.get("wiki_url", "") or ""
        path = _extract_path_without_lang(_SITE_PREFIX_RE.sub("", url))
        if path not in seen_paths:
            seen_paths[path] = []
        seen_paths[path].append(src)

    result = []
    for path, variants in seen_paths.items():
        if len(variants) == 1:
            result.append(variants[0])
        else:
            # Pick preferred language
            lang_matches = [v for v in variants
                          if extract_lang_from_url(v.get("wiki_url", "")) == preferred_lang]
            if lang_matches:
                result.append(lang_matches[0])
            else:
                result.append(variants[0])
    return result


# ---- Main entry point ----

def process_sources(
    sources: List[Dict],
    user_language: str = "zh",
) -> Dict[str, Any]:
    """Process raw sources: dedup, unify language versions, group by product.

    Args:
        sources: Raw source list from retriever (each dict must have title, wiki_url, score)
        user_language: User's preferred language ("zh" or "en")

    Returns:
        {
            "grouped": [
                {
                    "group_name": "reComputer J401",
                    "group_key": "recomputer-j401",
                    "doc_type": "Getting Started",
                    "items": [
                        {"title": "...", "url": "...", "lang": "zh", "score": ...},
                        ...
                    ]
                },
                ...
            ],
            "flat": [...],  # Flat deduped list for backward compatibility
            "stats": {
                "total_input": 10,
                "total_deduped": 8,
                "total_grouped": 3,
            }
        }
    """
    if not sources:
        return {"grouped": [], "flat": [], "stats": {"total_input": 0, "total_deduped": 0, "total_grouped": 0}}

    total_input = len(sources)

    # Step 1: Language version unification
    unified = unify_language_versions(sources, preferred_lang=user_language)

    # Step 2: Deduplication
    deduped = deduplicate_sources(unified)

    # Step 3: Sort by score (descending)
    deduped.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)

    # Step 4: Group by product
    groups: Dict[str, List[Dict]] = {}
    for src in deduped:
        url = src.get("wiki_url", "") or ""
        title = src.get("title", "") or ""
        group_name = _infer_product_group(url, title)
        doc_type = _infer_doc_type(url, title)

        item = {
            "title": normalize_title(title),
            "url": url,
            "lang": extract_lang_from_url(url) or user_language,
            "score": float(src.get("score", 0.0)),
            "doc_type": doc_type,
        }
        if group_name not in groups:
            groups[group_name] = []
        groups[group_name].append(item)

    # Step 5: Sort items within groups by score, sort groups by top score
    def group_top_score(items: List[Dict]) -> float:
        return max((i["score"] for i in items), default=0.0)

    sorted_groups = sorted(
        groups.items(),
        key=lambda g: group_top_score(g[1]),
        reverse=True,
    )

    # Step 6: Build output structure
    grouped = []
    for group_name, items in sorted_groups:
        items.sort(key=lambda x: x["score"], reverse=True)
        group_key = re.sub(r"[^a-z0-9]+", "-", group_name.lower()).strip("-")
        grouped.append({
            "group_name": group_name,
            "group_key": group_key,
            "doc_type": items[0]["doc_type"] if items else "Documentation",
            "count": len(items),
            "items": items,
        })

    logger.info(
        f"[source_processor] input={total_input}, deduped={len(deduped)}, "
        f"groups={len(grouped)}, preferred_lang={user_language}"
    )

    return {
        "grouped": grouped,
        "flat": deduped,
        "stats": {
            "total_input": total_input,
            "total_deduped": len(deduped),
            "total_grouped": len(grouped),
        },
    }


def render_grouped_sources_as_markdown(grouped: List[Dict], flat: List[Dict]) -> str:
    """Render grouped sources as Markdown for email template.

    Falls back to flat list if grouping is not useful.
    """
    if not grouped:
        return ""

    # If only one group or groups are very small, use flat list
    if len(grouped) == 1 and grouped[0]["count"] <= 5:
        return _render_flat_list(flat)

    lines = []
    for group in grouped:
        group_name = group["group_name"]
        doc_type = group["doc_type"]
        items = group["items"]

        lines.append(f"**{group_name}**")
        for item in items:
            title = item["title"]
            url = item["url"]
            lines.append(f"- [{title}]({url})")
        lines.append("")  # blank line between groups

    return "\n".join(lines)


def _render_flat_list(flat: List[Dict]) -> str:
    """Render flat source list as Markdown bullet points."""
    if not flat:
        return ""
    lines = []
    for src in flat:
        title = normalize_title(src.get("title", ""))
        url = src.get("wiki_url", "")
        if title and url:
            lines.append(f"- [{title}]({url})")
    return "\n".join(lines)
