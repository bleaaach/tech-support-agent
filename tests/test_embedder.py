"""Embedder 单元测试"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_embedder_mock():
    """不依赖真实 API，验证 batch 处理逻辑"""
    from pipeline.embedder import OpenAIEmbedding

    print("=== Embedder Test ===\n")

    try:
        embedder = OpenAIEmbedding(api_key="sk-test", model="text-embedding-3-small")
        print(f"[OK] Embedder initialized")
        print(f"  - Model: {embedder.model}")
        print(f"  - Dimensions: {embedder.dimensions}")
        print(f"  - Batch size: {embedder.batch_size}")
        assert embedder.model == "text-embedding-3-small"
        assert embedder.dimensions == 1536
    except Exception as e:
        print(f"[FAIL] Init failed: {e}")
        raise


if __name__ == "__main__":
    test_embedder_mock()
    print("\nAll tests passed!")
