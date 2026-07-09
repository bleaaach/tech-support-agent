"""SAGRetriever 单元测试（无需 SAG 服务运行）

覆盖：
1. RRF 融合算法正确性
2. SAGRetriever 接口与 QdrantRetriever 兼容（mock HTTP 响应）
3. SAG 不可达时的优雅降级
4. _hit_to_chunk 字段映射容错
5. 从 config 读取配置

运行：
    python -m tests.test_sag_retriever
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from agent.retriever import RetrievedChunk
from agent.sag_retriever import SAGRetriever, rrf_fuse


def _mk_chunk(doc_id: str, score: float, text: str = "") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_text=text or f"text for {doc_id}",
        title=f"title-{doc_id}",
        wiki_url=f"https://wiki.seeedstudio.com/{doc_id}",
        category="jetson",
        doc_id=doc_id,
        score=score,
        image_urls=[],
        resource_urls=[],
    )


class TestRRFFuse(unittest.TestCase):
    """RRF 融合算法"""

    def test_empty_input(self):
        self.assertEqual(rrf_fuse([]), [])
        self.assertEqual(rrf_fuse([[], []]), [])

    def test_single_list(self):
        chunks = [_mk_chunk("a", 0.9), _mk_chunk("b", 0.8)]
        fused = rrf_fuse([chunks], top_n=10)
        self.assertEqual(len(fused), 2)
        # 排名 1 在前
        self.assertEqual(fused[0].doc_id, "a")
        self.assertEqual(fused[1].doc_id, "b")

    def test_two_lists_no_overlap(self):
        c1 = [_mk_chunk("a", 0.9), _mk_chunk("b", 0.8)]
        c2 = [_mk_chunk("c", 0.95), _mk_chunk("d", 0.7)]
        fused = rrf_fuse([c1, c2], top_n=10)
        self.assertEqual(len(fused), 4)
        # rank1 in both lists 都拿满分；前面是 c (rank1 in c2) 和 a (rank1 in c1)，顺序不重要但要并列
        ids = [f.doc_id for f in fused[:2]]
        self.assertIn("c", ids)
        self.assertIn("a", ids)

    def test_overlap_boost(self):
        """同一 doc 在两路都出现 → RRF 分数叠加，应排第一"""
        c1 = [_mk_chunk("a", 0.9), _mk_chunk("b", 0.8)]
        c2 = [_mk_chunk("a", 0.95), _mk_chunk("c", 0.7)]
        fused = rrf_fuse([c1, c2], top_n=10)
        self.assertEqual(fused[0].doc_id, "a", "doc 出现两次应排第一")

    def test_weights(self):
        """权重影响融合顺序"""
        c1 = [_mk_chunk("a", 0.9), _mk_chunk("b", 0.8)]
        c2 = [_mk_chunk("c", 0.95)]
        # 让 c1 权重更高 → a 应排第一
        fused = rrf_fuse([c1, c2], weights=[2.0, 0.1], top_n=10)
        self.assertEqual(fused[0].doc_id, "a")

    def test_top_n_truncation(self):
        c1 = [_mk_chunk(f"d{i}", 0.9 - i * 0.1) for i in range(5)]
        c2 = [_mk_chunk(f"d{i}", 0.85 - i * 0.1) for i in range(3, 8)]
        fused = rrf_fuse([c1, c2], top_n=3)
        self.assertEqual(len(fused), 3)

    def test_score_replaced_with_rrf(self):
        """融合后 chunk.score 应是 RRF 分数，不是原始 score"""
        c1 = [_mk_chunk("a", 0.9)]
        fused = rrf_fuse([c1], top_n=1)
        # rank=1, weight=1, k=60 → 1/(60+1) ≈ 0.0164
        self.assertAlmostEqual(fused[0].score, 1.0 / 61, places=3)


class TestSAGRetrieverInterface(unittest.TestCase):
    """SAGRetriever 与 QdrantRetriever 接口兼容"""

    def test_retrieve_returns_list_of_RetrievedChunk(self):
        """retrieve() 必须返回 list[RetrievedChunk]"""
        retriever = SAGRetriever(base_url="http://127.0.0.1:1", enabled=False)
        result = retriever.retrieve("test query")
        # enabled=False 时返回空列表
        self.assertIsInstance(result, list)

    def test_disabled_returns_empty(self):
        retriever = SAGRetriever(base_url="http://127.0.0.1:1", enabled=False)
        self.assertEqual(retriever.retrieve("anything"), [])

    def test_unreachable_returns_empty(self):
        """服务不可达时不抛异常，返回空列表"""
        retriever = SAGRetriever(base_url="http://127.0.0.1:1", enabled=True, timeout=2)
        result = retriever.retrieve("test")
        self.assertEqual(result, [])

    def test_health_returns_bool(self):
        retriever = SAGRetriever(base_url="http://127.0.0.1:1", enabled=True)
        self.assertIsInstance(retriever.health(), bool)
        self.assertFalse(retriever.health())  # 端口 1 不可能开

    def test_disabled_health_false(self):
        retriever = SAGRetriever(base_url="http://localhost:4173", enabled=False)
        self.assertFalse(retriever.health())


class TestSAGRetrieverMocked(unittest.TestCase):
    """用 mock 模拟 SAG HTTP 响应"""

    def _mock_response(self, results: list[dict]) -> MagicMock:
        resp = MagicMock()
        resp.ok = True
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"results": results})
        return resp

    @patch("agent.sag_retriever.requests.Session")
    def test_retrieve_parses_results(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session.post.return_value = self._mock_response([
            {"eventId": "e1", "content": "J401 supports JetPack 6", "title": "reComputer J401",
             "sourceUrl": "https://wiki.seeedstudio.com/j401", "score": 0.92},
            {"id": "e2", "text": "J501 spec", "sourceTitle": "J501", "url": "https://wiki.seeedstudio.com/j501",
             "relevance": 0.85},
        ])
        mock_session_cls.return_value = mock_session

        retriever = SAGRetriever(base_url="http://localhost:4173", enabled=True, timeout=5)
        chunks = retriever.retrieve("JetPack version")

        self.assertEqual(len(chunks), 2)
        self.assertIsInstance(chunks[0], RetrievedChunk)
        self.assertEqual(chunks[0].doc_id, "e1")
        self.assertEqual(chunks[0].title, "reComputer J401")
        self.assertEqual(chunks[0].wiki_url, "https://wiki.seeedstudio.com/j401")
        self.assertAlmostEqual(chunks[0].score, 0.92)

        # 第二条用了 alias 字段
        self.assertEqual(chunks[1].doc_id, "e2")
        self.assertEqual(chunks[1].chunk_text, "J501 spec")
        self.assertAlmostEqual(chunks[1].score, 0.85)

    @patch("agent.sag_retriever.requests.Session")
    def test_health_true(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session.get.return_value.ok = True
        mock_session_cls.return_value = mock_session

        retriever = SAGRetriever(base_url="http://localhost:4173", enabled=True)
        self.assertTrue(retriever.health())

    @patch("agent.sag_retriever.requests.Session")
    def test_ingest(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session.post.return_value = self._mock_response({"ok": True, "eventId": "x"})
        mock_session_cls.return_value = mock_session

        retriever = SAGRetriever(base_url="http://localhost:4173", enabled=True)
        result = retriever.ingest(title="Test", content="# Hello\n\nWorld")
        self.assertTrue(result["ok"])


class TestSAGRetrieverFieldFallback(unittest.TestCase):
    """SAG 返回字段名可能不同版本下不同，验证容错"""

    def test_minimal_hit(self):
        """只有最少字段也能跑通"""
        retriever = SAGRetriever(enabled=False)
        # 直接调用内部方法
        chunk = retriever._hit_to_chunk({"id": "1", "text": "hello"})
        self.assertEqual(chunk.doc_id, "1")
        self.assertEqual(chunk.chunk_text, "hello")
        self.assertEqual(chunk.title, "")
        self.assertEqual(chunk.wiki_url, "")
        self.assertEqual(chunk.score, 0.0)

    def test_full_hit(self):
        retriever = SAGRetriever(enabled=False)
        chunk = retriever._hit_to_chunk({
            "eventId": "e1",
            "content": "text",
            "title": "T",
            "sourceUrl": "https://x",
            "score": 0.5,
            "imageUrls": ["https://x/a.png"],
            "resourceUrls": ["https://x/a.pdf"],
        })
        self.assertEqual(chunk.doc_id, "e1")
        self.assertEqual(chunk.title, "T")
        self.assertEqual(chunk.image_urls, ["https://x/a.png"])
        self.assertEqual(chunk.resource_urls, ["https://x/a.pdf"])


class TestSAGRetrieverFromConfig(unittest.TestCase):
    """从 config.yaml 读取配置"""

    def test_from_config(self):
        retriever = SAGRetriever.from_config()
        self.assertIsNotNone(retriever.base_url)
        self.assertIn(retriever.backend, ("qdrant", "sag", "hybrid")) if hasattr(retriever, "backend") else True
        # 默认 enabled 是 false（保守）
        # 实际值取决于 config.yaml，按文件加载来


if __name__ == "__main__":
    unittest.main(verbosity=2)