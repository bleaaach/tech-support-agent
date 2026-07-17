"""诊断 Agent：从用户消息中识别 Jetson 错误码，路由到对应 Wiki 故障文档。

设计详见 docs/MULTI_AGENT_INTEGRATION_PLAN.md §三。

工作流：
    user_message
      ↓
    [1] regex 扫描 error_codes.yaml 中的 pattern
      ↓
    [2] 每个匹配的 code → 用 suggested_docs 路径在 Qdrant 中检索
      ↓
    [3] 构造 diagnostic_chunks（注入 wiki_chunks，prepend，最高优先级）
      ↓
    [4] 若无匹配 → 返回空（不报错，正常降级）

触发条件（由外部节点控制）：
    - question_type ∈ trigger_qtypes（默认 troubleshooting）
    - 用户消息命中至少 1 个已知错误码
    - 节点本身 enabled=True
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


# .env 加载（与其他模块一致）
_env_path = Path(__file__).parent.parent.parent / ".env"
if _env_path.exists():
    with open(_env_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


@dataclass
class ErrorCodeMatch:
    """单条错误码匹配结果"""

    code: str                          # 错误码名，如 "MC_ERR"
    raw: str                           # 原始匹配文本，如 "MC_ERR 0x14"
    description: str                   # 人类可读描述
    severity: str                      # critical | warning | info
    suggested_docs: list[str]          # Wiki 文档相对路径列表
    troubleshooting_steps: list[str]   # 人工排查步骤


@dataclass
class DiagnoseOutput:
    """DiagnoseAgent.run() 的返回结构（与 graph 节点契约对齐）"""

    matched_error_codes: list[ErrorCodeMatch] = field(default_factory=list)
    matched_docs: list[dict] = field(default_factory=list)          # 来自 Qdrant 检索的文档摘要
    diagnostic_chunks: list[dict] = field(default_factory=list)     # 注入 wiki_chunks 的结构化 chunks
    fallback_hint: str = ""                                          # 若无可匹配错误码，给用户的提示


class DiagnoseAgent:
    """诊断 Agent：识别 Jetson 错误码 + 路由到故障文档

    用法：
        agent = DiagnoseAgent.from_config({
            "enabled": True,
            "trigger_qtypes": ["troubleshooting"],
            "max_matched_docs": 3,
            "error_codes_db": "data/error_codes.yaml",
        })
        out = agent.run(user_message="dmesg 显示 MC_ERR 0x14 ...", qtype="troubleshooting")
        # out.diagnostic_chunks 可注入 graph 的 wiki_chunks
    """

    DEFAULT_TRIGGER_QTYPES = ["troubleshooting"]
    DEFAULT_MAX_MATCHED_DOCS = 3

    def __init__(
        self,
        enabled: bool = False,
        trigger_qtypes: list[str] | None = None,
        max_matched_docs: int = DEFAULT_MAX_MATCHED_DOCS,
        error_codes_db: str = "data/error_codes.yaml",
        qdrant_retriever: Any | None = None,    # 注入测试用，None 时 lazy init
    ):
        self.enabled = enabled
        self.trigger_qtypes = trigger_qtypes or self.DEFAULT_TRIGGER_QTYPES
        self.max_matched_docs = max_matched_docs
        self.error_codes_db_path = Path(__file__).parent.parent.parent / error_codes_db
        self._qdrant_retriever = qdrant_retriever

        # 编译 regex（在 __init__ 一次性编译，避免每次 run 重新编译）
        self._code_patterns: list[tuple[dict, re.Pattern]] = []
        self._case_sensitive = False
        self._max_matches_per_code = 5
        self._min_chunk_text_length = 50
        self._load_error_codes_db()

    # ---------- 工厂方法 ----------
    @classmethod
    def from_config(cls, cfg: dict) -> "DiagnoseAgent":
        """从 config.yaml 风格的 dict 构造（兼容 None / 缺字段）"""
        return cls(
            enabled=cfg.get("enabled", False),
            trigger_qtypes=cfg.get("trigger_qtypes", cls.DEFAULT_TRIGGER_QTYPES),
            max_matched_docs=cfg.get("max_matched_docs", cls.DEFAULT_MAX_MATCHED_DOCS),
            error_codes_db=cfg.get("error_codes_db", "data/error_codes.yaml"),
        )

    # ---------- 公开方法 ----------
    def run(self, user_message: str, qtype: str = "general") -> DiagnoseOutput:
        """主入口：扫描错误码 → 检索文档 → 构造 diagnostic_chunks

        异常被全部捕获，返回空 DiagnoseOutput，不影响上层流程。
        """
        if not self.enabled:
            return DiagnoseOutput(fallback_hint="diagnose agent disabled")

        if qtype not in self.trigger_qtypes:
            return DiagnoseOutput(fallback_hint=f"qtype {qtype} not in trigger_qtypes")

        try:
            matches = self._extract_error_codes(user_message)
            if not matches:
                return DiagnoseOutput(
                    fallback_hint="未识别到已知 Jetson 错误码。如方便，请粘贴完整 dmesg 输出或报错截图。"
                )

            chunks, doc_summaries = self._build_diagnostic_chunks(matches)

            logger.info(
                f"[diagnose] matched {len(matches)} error codes, "
                f"built {len(chunks)} diagnostic chunks"
            )
            return DiagnoseOutput(
                matched_error_codes=matches,
                matched_docs=doc_summaries,
                diagnostic_chunks=chunks,
            )
        except Exception as e:
            logger.error(f"[diagnose] failed (non-fatal): {e}", exc_info=True)
            return DiagnoseOutput(fallback_hint=f"诊断流程异常：{e!s}")

    # ---------- 内部：错误码扫描 ----------
    def _extract_error_codes(self, text: str) -> list[ErrorCodeMatch]:
        """扫描用户消息，匹配所有已知错误码

        返回去重后的 ErrorCodeMatch 列表。
        """
        seen_codes: set[str] = set()
        results: list[ErrorCodeMatch] = []

        for entry, pattern in self._code_patterns:
            raw_matches = pattern.findall(text)
            if not raw_matches:
                continue

            code = entry["code"]
            if code in seen_codes:
                continue
            seen_codes.add(code)

            # 取前 N 个匹配文本（截断避免日志刷屏）
            raws = raw_matches[: self._max_matches_per_code]
            raw_combined = " | ".join(r if isinstance(r, str) else str(r) for r in raws)

            results.append(
                ErrorCodeMatch(
                    code=code,
                    raw=raw_combined,
                    description=entry["description"],
                    severity=entry.get("severity", "info"),
                    suggested_docs=entry.get("suggested_docs", []),
                    troubleshooting_steps=entry.get("troubleshooting_steps", []),
                )
            )

        # 按 severity 排序（critical > warning > info）
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        results.sort(key=lambda m: severity_order.get(m.severity, 99))
        return results

    # ---------- 内部：文档检索 ----------
    def _build_diagnostic_chunks(
        self, matches: list[ErrorCodeMatch]
    ) -> tuple[list[dict], list[dict]]:
        """对每个匹配的 error code，用 suggested_docs 在 Qdrant 中检索，构造 chunks

        Returns:
            chunks: 注入 wiki_chunks 的结构化数据
            doc_summaries: 仅摘要信息（调试 / 日志用）
        """
        chunks: list[dict] = []
        doc_summaries: list[dict] = []

        # 收集所有要检索的 doc path（去重）
        all_doc_paths: list[str] = []
        seen_paths: set[str] = set()
        for m in matches:
            for path in m.suggested_docs:
                if path not in seen_paths:
                    seen_paths.add(path)
                    all_doc_paths.append(path)

        # 调用 Qdrant 检索（如果 retriever 不可用，跳过）
        retrieved_docs: dict[str, dict] = {}
        if all_doc_paths and self._get_qdrant_retriever() is not None:
            try:
                retrieved_docs = self._retrieve_docs_by_path(all_doc_paths)
            except Exception as e:
                logger.warning(f"[diagnose] Qdrant retrieval failed: {e}")

        # 构造 chunks
        for match in matches:
            # 收集该错误码对应的实际命中的文档
            related_docs = []
            for path in match.suggested_docs:
                if path in retrieved_docs:
                    related_docs.append(retrieved_docs[path])
                    doc_summaries.append(
                        {
                            "code": match.code,
                            "title": retrieved_docs[path].get("title", ""),
                            "wiki_url": retrieved_docs[path].get("wiki_url", ""),
                            "path": path,
                        }
                    )

            # chunk_text：把错误码 + 描述 + 排查步骤拼起来
            chunk_text = self._format_chunk_text(match, related_docs)
            if len(chunk_text) < self._min_chunk_text_length:
                # 兜底：至少把错误码描述写进去
                chunk_text = (
                    f"[Diagnose] {match.code}\n\n"
                    f"**描述**: {match.description}\n\n"
                    f"**原始匹配**: `{match.raw}`\n\n"
                    f"**严重程度**: {match.severity}\n\n"
                    f"请参考相关故障排查文档。"
                )

            # 标题取第一个匹配文档的标题，或用错误码
            primary_doc = related_docs[0] if related_docs else {}
            chunk_title = primary_doc.get("title", f"[Diagnose] {match.code}")

            chunks.append(
                {
                    "chunk_text": chunk_text,
                    "title": chunk_title,
                    "wiki_url": primary_doc.get("wiki_url", ""),
                    "category": "diagnostic",
                    "doc_id": primary_doc.get("doc_id", f"diagnose_{match.code}"),
                    "score": 1.0,    # 诊断线索优先级最高
                    "image_urls": primary_doc.get("image_urls", []),
                    "resource_urls": primary_doc.get("resource_urls", []),
                    # 调试用元数据
                    "_diagnose_meta": {
                        "code": match.code,
                        "raw": match.raw,
                        "severity": match.severity,
                        "matched_docs_count": len(related_docs),
                    },
                }
            )

        return chunks, doc_summaries

    def _format_chunk_text(self, match: ErrorCodeMatch, related_docs: list[dict]) -> str:
        """构造诊断 chunk_text

        结构：
            [Diagnose] MC_ERR
            **描述**: Memory Controller Error — 内存控制器硬件故障
            **原始日志**: `MC_ERR 0x14`
            **严重程度**: critical
            **排查步骤**:
              1. 检查 dmesg ...
              2. 运行 tegrastats ...
            **参考文档**:
              - [doc title](wiki_url)
              - [doc title](wiki_url)
        """
        lines: list[str] = []
        lines.append(f"[Diagnose] {match.code}")
        lines.append("")
        lines.append(f"**描述**: {match.description}")
        lines.append("")
        lines.append(f"**原始日志匹配**: `{match.raw}`")
        lines.append("")
        lines.append(f"**严重程度**: {match.severity}")
        lines.append("")

        if match.troubleshooting_steps:
            lines.append("**排查步骤**:")
            for i, step in enumerate(match.troubleshooting_steps, 1):
                lines.append(f"{i}. {step}")
            lines.append("")

        if related_docs:
            lines.append("**参考文档**:")
            for doc in related_docs[: self.max_matched_docs]:
                title = doc.get("title", "未知")
                url = doc.get("wiki_url", "")
                if url:
                    lines.append(f"- [{title}]({url})")
                else:
                    lines.append(f"- {title}")
            lines.append("")

        return "\n".join(lines).strip()

    # ---------- 内部：Qdrant 集成 ----------
    def _get_qdrant_retriever(self):
        """Lazy init QdrantRetriever（与现有项目使用同一个 collection）"""
        if self._qdrant_retriever is None:
            try:
                from ..retriever import QdrantRetriever

                self._qdrant_retriever = QdrantRetriever()
            except Exception as e:
                logger.warning(f"[diagnose] cannot init QdrantRetriever: {e}")
                self._qdrant_retriever = False  # 标记为不可用
        return self._qdrant_retriever if self._qdrant_retriever else None

    def _retrieve_docs_by_path(self, doc_paths: list[str]) -> dict[str, dict]:
        """根据 Wiki 相对路径列表，在 Qdrant 中找到对应文档的 slug 字段

        策略：用 doc_path 中的最后一段（如 How_to_Troubleshoot_Memory_Errors.md）作为关键词
              在 Qdrant payload 中检索 title 字段匹配的文档。

        Returns:
            {doc_path: {"title": ..., "wiki_url": ..., "doc_id": ..., "image_urls": [...], "resource_urls": [...]}}
        """
        retriever = self._get_qdrant_retriever()
        if retriever is None:
            return {}

        result: dict[str, dict] = {}
        # 从 doc_path 中提取文件名作为检索关键词
        from ..retriever import RetrievedChunk

        for path in doc_paths:
            # path 例: "Edge/NVIDIA_Jetson/FAQs/How_to_Troubleshoot_Memory_Errors.md"
            filename = path.split("/")[-1].replace(".md", "")
            # 用 filename 作为搜索词
            try:
                chunks = retriever.retrieve(filename, top_k=1)
                if chunks and len(chunks) > 0:
                    top: RetrievedChunk = chunks[0]
                    # 仅当 top 的标题与 filename 有较高重合度时，才采纳（避免误匹配）
                    if filename.lower().replace("_", " ") in top.title.lower().replace("_", " ") or \
                       any(word in top.title.lower() for word in filename.lower().replace("_", " ").split() if len(word) > 3):
                        result[path] = {
                            "title": top.title,
                            "wiki_url": top.wiki_url,
                            "doc_id": top.doc_id,
                            "image_urls": top.image_urls,
                            "resource_urls": top.resource_urls,
                        }
            except Exception as e:
                logger.warning(f"[diagnose] retrieve '{filename}' failed: {e}")
                continue

        return result

    # ---------- 内部：YAML 加载 ----------
    def _load_error_codes_db(self) -> None:
        """加载并编译错误码 YAML"""
        if not self.error_codes_db_path.exists():
            logger.warning(
                f"[diagnose] error_codes_db not found: {self.error_codes_db_path}"
            )
            return

        try:
            with open(self.error_codes_db_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"[diagnose] failed to load YAML: {e}")
            return

        global_cfg = data.get("diagnose_config", {}) or {}
        self._case_sensitive = global_cfg.get("case_sensitive", False)
        self._max_matches_per_code = global_cfg.get("max_pattern_matches_per_code", 5)
        self._min_chunk_text_length = global_cfg.get("min_chunk_text_length", 50)

        flags = 0 if self._case_sensitive else re.IGNORECASE
        for entry in data.get("error_codes", []) or []:
            pattern_str = entry.get("pattern")
            if not pattern_str:
                continue
            try:
                compiled = re.compile(pattern_str, flags=flags)
                self._code_patterns.append((entry, compiled))
            except re.error as e:
                logger.warning(
                    f"[diagnose] invalid regex for {entry.get('code')}: {e}"
                )

        logger.info(
            f"[diagnose] loaded {len(self._code_patterns)} error codes from "
            f"{self.error_codes_db_path}"
        )


# ============================================================
# Standalone 入口（便于 Phase 2 验证，Phase 3 由 graph.py 调用）
# ============================================================

def _cli():
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Diagnose Agent CLI — 识别 Jetson 错误码并给出诊断线索"
    )
    parser.add_argument(
        "--message", "-m", required=True, help="用户消息（含日志/错误码）"
    )
    parser.add_argument("--qtype", default="troubleshooting", help="问题类型")
    parser.add_argument("--no-qdrant", action="store_true", help="跳过 Qdrant 检索")
    args = parser.parse_args()

    agent = DiagnoseAgent.from_config({"enabled": True})
    if args.no_qdrant:
        agent._qdrant_retriever = False
    out = agent.run(args.message, args.qtype)
    print(json.dumps(
        {
            "matched_codes": [
                {"code": m.code, "raw": m.raw, "severity": m.severity}
                for m in out.matched_error_codes
            ],
            "matched_docs_count": len(out.matched_docs),
            "diagnostic_chunks_count": len(out.diagnostic_chunks),
            "fallback_hint": out.fallback_hint,
            "first_chunk_preview": (
                out.diagnostic_chunks[0]["chunk_text"][:300]
                if out.diagnostic_chunks
                else None
            ),
        },
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    _cli()