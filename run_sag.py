"""独立运行 LangGraph SAG (Self-Agentic Graph) 工作流

用法：
    python run_sag.py                          # 交互式测试
    python run_sag.py "你的问题"               # 单次查询
    python run_sag.py --visualize              # 可视化工作流图结构
    python run_sag.py --debug "问题"           # 调试模式（显示每个节点的输出）
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path

# 确保项目根目录在 sys.path
ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 加载 .env
_env_path = ROOT / ".env"
if _env_path.exists():
    with open(_env_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

from agent.graph import build_graph, AgentState
from agent.retriever import QdrantRetriever
from agent.router import QuestionRouter
from agent.generator import AnswerGenerator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def visualize_graph():
    """可视化 LangGraph 结构（需要 graphviz）"""
    try:
        from langchain_core.runnables.graph import MermaidDrawMethod
        print("\n🔍 构建 LangGraph...")
        graph = build_graph()
        print("✅ 图构建成功\n")

        # 打印节点列表
        nodes = list(graph.nodes.keys())
        print("📊 图节点列表:")
        for node in nodes:
            if node not in ["__start__", "__end__"]:
                print(f"  • {node}")

        # 生成 Mermaid 图
        print("\n🎨 Mermaid 流程图:")
        print("=" * 60)
        try:
            mermaid = graph.get_graph().draw_mermaid()
            print(mermaid)
        except Exception as e:
            print(f"无法生成 Mermaid 图: {e}")
            print("\n图结构 (文本):")
            for node in nodes:
                if node not in ["__start__", "__end__"]:
                    print(f"  {node}")
        print("=" * 60)

        # 保存为 PNG（如果有 graphviz）
        try:
            png_path = ROOT / "graph_visualization.png"
            graph.get_graph().draw_mermaid_png(
                output_file_path=str(png_path),
                draw_method=MermaidDrawMethod.API,
            )
            print(f"\n✅ 图已保存为: {png_path}")
        except Exception as e:
            print(f"\n⚠️  无法保存 PNG (需要 graphviz): {e}")

    except ImportError as e:
        print(f"❌ 缺少依赖: {e}")
        print("请运行: pip install graphviz")


def run_single_query(question: str, debug: bool = False, show_sources: bool = True):
    """运行单次查询"""
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger("agent").setLevel(logging.DEBUG)

    print(f"\n{'='*60}")
    print(f"❓ 问题: {question}")
    print(f"{'='*60}\n")

    try:
        # 构建图
        print("🔧 初始化 LangGraph 工作流...")
        graph = build_graph()
        print("✅ 工作流就绪\n")

        # 准备初始状态
        initial_state: AgentState = {
            "user_message": question,
            "history_text": "",
            "category": "",
            "rewrite_iterations": 0,
        }

        print("🚀 开始执行工作流...\n")

        # 执行图（增加递归限制到 50，防止 rewrite loop 超限）
        if debug:
            # 调试模式：逐节点打印
            print("📍 节点执行追踪:")
            print("-" * 60)
            final_state = graph.invoke(initial_state, {"recursion_limit": 50})
        else:
            final_state = graph.invoke(initial_state, {"recursion_limit": 50})

        print("\n" + "="*60)
        print("✅ 工作流执行完成")
        print("="*60 + "\n")

        # 打印结果
        answer = final_state.get("answer", "（无回答）")
        sources = final_state.get("sources", [])
        qtype = final_state.get("question_type", "general")
        image_urls = final_state.get("image_urls", [])
        resource_urls = final_state.get("resource_urls", [])

        print("💡 回答:")
        print("-" * 60)
        print(answer)
        print("-" * 60)

        print(f"\n📋 问题类型: {qtype}")

        if show_sources and sources:
            print(f"\n📚 参考来源 ({len(sources)} 条):")
            for i, src in enumerate(sources, 1):
                title = src.get("title", "未知标题")
                url = src.get("wiki_url", "")
                score = src.get("score", 0.0)
                print(f"  [{i}] {title} (相似度: {score:.2f})")
                if url:
                    print(f"      {url}")

        if image_urls:
            print(f"\n🖼️  相关图片 ({len(image_urls)} 张):")
            for url in image_urls[:3]:
                print(f"  • {url}")

        if resource_urls:
            print(f"\n🔗 相关资源 ({len(resource_urls)} 个):")
            for url in resource_urls[:3]:
                print(f"  • {url}")

        # 调试信息
        if debug:
            print(f"\n🔍 调试信息:")
            print(f"  • 改写查询: {final_state.get('rewritten_queries', [])}")
            print(f"  • Wiki 文档数: {len(final_state.get('wiki_chunks', []))}")
            print(f"  • 历史回复数: {len(final_state.get('historical_chunks', []))}")
            print(f"  • 反思得分: {final_state.get('reflection_score', 'N/A')}")
            print(f"  • 反思理由: {final_state.get('reflection_reason', 'N/A')}")
            print(f"  • 改写迭代: {final_state.get('rewrite_iterations', 0)}")
            fallback = final_state.get("fallback_reason", "")
            if fallback:
                print(f"  • ⚠️  降级原因: {fallback}")

        print()
        return final_state

    except Exception as e:
        logger.error(f"执行失败: {e}", exc_info=True)
        print(f"\n❌ 错误: {e}\n")
        return None


def interactive_mode():
    """交互式测试模式"""
    print("\n" + "="*60)
    print("🤖 LangGraph SAG 交互式测试")
    print("="*60)
    print("\n命令:")
    print("  • 直接输入问题进行查询")
    print("  • :debug - 切换调试模式")
    print("  • :sources - 切换来源显示")
    print("  • :graph - 显示图结构")
    print("  • :quit / :q - 退出")
    print()

    debug = False
    show_sources = True

    # 预热：构建图（避免第一次查询慢）
    print("🔧 预热工作流...")
    try:
        build_graph()
        print("✅ 就绪\n")
    except Exception as e:
        print(f"⚠️  预热失败: {e}\n")

    while True:
        try:
            question = input("❓ > ").strip()

            if not question:
                continue

            if question in [":quit", ":q", ":exit"]:
                print("👋 再见！")
                break

            if question == ":debug":
                debug = not debug
                print(f"🔧 调试模式: {'开启' if debug else '关闭'}")
                continue

            if question == ":sources":
                show_sources = not show_sources
                print(f"📚 来源显示: {'开启' if show_sources else '关闭'}")
                continue

            if question == ":graph":
                visualize_graph()
                continue

            # 执行查询
            run_single_query(question, debug=debug, show_sources=show_sources)

        except KeyboardInterrupt:
            print("\n\n👋 再见！")
            break
        except EOFError:
            print("\n👋 再见！")
            break


def main():
    parser = argparse.ArgumentParser(
        description="独立运行 LangGraph SAG 工作流",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "question",
        nargs="?",
        help="要查询的问题（不提供则进入交互模式）",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="开启调试模式（显示详细日志）",
    )
    parser.add_argument(
        "--visualize",
        action="store_true",
        help="可视化工作流图结构",
    )
    parser.add_argument(
        "--no-sources",
        action="store_true",
        help="不显示参考来源",
    )

    args = parser.parse_args()

    if args.visualize:
        visualize_graph()
        return 0

    if args.question:
        # 单次查询模式
        result = run_single_query(
            args.question,
            debug=args.debug,
            show_sources=not args.no_sources,
        )
        return 0 if result else 1
    else:
        # 交互式模式
        interactive_mode()
        return 0


if __name__ == "__main__":
    sys.exit(main())
