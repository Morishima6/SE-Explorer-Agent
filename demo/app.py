import argparse
import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from rag.cache_config import configure_project_cache

configure_project_cache(PROJECT_ROOT)


def _load_project_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        print(f"[demo] .env not found at {env_path}")
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        print("[demo] python-dotenv is not installed, skip .env loading")
        return
    load_dotenv(env_path)
    print(f"[demo] load environment variables from {env_path}")


def _validate_real_llm_env(model: str | None) -> None:
    missing: list[str] = []
    if not os.environ.get("OPENAI_API_KEY"):
        missing.append("OPENAI_API_KEY")
    if not (model or os.environ.get("OPENAI_MODEL")):
        missing.append("OPENAI_MODEL")
    if missing:
        names = ", ".join(missing)
        raise ValueError(f"Missing LLM configuration: {names}. Please set them in .env or environment variables.")


from agent.llm_client import LLMClient, MockLLMClient
from agent.loop import AgentLoop
from agent.tool_registry import ToolRegistry
from agent.trajectory import TrajectoryLogger
from rag.rag_anything_config import RAGAnythingProjectConfig
from rag.rag_anything_loader import RAGAnythingLoader
from tools.generate_patch import generate_patch
from tools.grep_code import grep_code
from tools.list_repo_tree import list_repo_tree
from tools.search_code import search_code
from tools.search_docs import search_docs
from tools.search_figures import search_figures
from tools.search_tables import search_tables
from tools.run_tests import run_tests
from tools.shell_readonly import shell_readonly
from tools.suggest_tests import suggest_tests
from tools.view_file import view_file


def _final_answer_tool(answer: str) -> dict[str, object]:
    print("[demo] final_answer tool called")
    return {"answer": answer}


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register("list_repo_tree", "查看仓库目录结构", list_repo_tree)
    registry.register("view_file", "读取文件片段", view_file)
    registry.register("grep_code", "关键词搜索代码或文本文件", grep_code)
    registry.register("search_code", "按关键词搜索代码文件", search_code)
    registry.register("search_docs", "检索 RAG-Anything 解析后的软件工程文档", search_docs)
    registry.register("search_tables", "检索 RAG-Anything 解析结果中的表格 block", search_tables)
    registry.register("search_figures", "检索 RAG-Anything 解析结果中的图片或图示 block", search_figures)
    registry.register("generate_patch", "生成 unified diff 修复建议，不直接修改文件", generate_patch)
    registry.register("suggest_tests", "生成测试命令和验证建议，不直接执行", suggest_tests)
    registry.register("run_tests", "run allowlisted test commands and return structured test results", run_tests)
    registry.register("final_answer", "输出最终答案，参数为 answer", _final_answer_tool)
    registry.register("shell_readonly", "run allowlisted read-only validation commands", shell_readonly)
    return registry


def _print_json(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="SE-Explorer Agent demo commands")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("list", help="列出已注册工具")
    tree_parser = subparsers.add_parser("tree", help="查看仓库目录")
    tree_parser.add_argument("--path", default=".")
    tree_parser.add_argument("--max-depth", type=int, default=2)

    view_parser = subparsers.add_parser("view", help="查看文件片段")
    view_parser.add_argument("path")
    view_parser.add_argument("start", type=int, nargs="?", default=1)
    view_parser.add_argument("end", type=int, nargs="?", default=80)

    grep_parser = subparsers.add_parser("search-code", help="搜索代码")
    grep_parser.add_argument("query")
    grep_parser.add_argument("--path", default=".")
    grep_parser.add_argument("--top-k", type=int, default=10)

    docs_parser = subparsers.add_parser("search-docs", help="搜索解析后的文档")
    docs_parser.add_argument("query")
    docs_parser.add_argument("--top-k", type=int, default=5)
    docs_parser.add_argument("--source", default="rag_anything", choices=["rag_anything", "all", "raw"])

    tables_parser = subparsers.add_parser("search-tables", help="搜索解析后的表格 block")
    tables_parser.add_argument("query")
    tables_parser.add_argument("--top-k", type=int, default=5)

    figures_parser = subparsers.add_parser("search-figures", help="搜索解析后的图片或图示 block")
    figures_parser.add_argument("query")
    figures_parser.add_argument("--top-k", type=int, default=5)

    ask_parser = subparsers.add_parser("ask", help="运行 ReAct Agent Loop")
    ask_parser.add_argument("question")
    ask_parser.add_argument("--max-steps", type=int, default=6)
    ask_parser.add_argument("--mock", action="store_true")
    ask_parser.add_argument("--mock-scenario", default="docs", choices=["docs", "code", "fix", "test", "multimodal"])
    ask_parser.add_argument("--model", default=None)
    ask_parser.add_argument("--task-id", default="demo_task")

    check_parser = subparsers.add_parser("check-rag", help="检查 RAG-Anything 可用性")
    check_parser.add_argument("--parser", default=None, choices=["mineru", "docling", "paddleocr"])

    build_parser = subparsers.add_parser("build-docs", help="使用 RAG-Anything 解析 books 文档")
    build_parser.add_argument("--limit", type=int, default=None)
    build_parser.add_argument("--parser", default=None, choices=["mineru", "docling", "paddleocr"])
    build_parser.add_argument("--parse-method", default="auto", choices=["auto", "ocr", "txt"])
    build_parser.add_argument("--mineru-timeout", type=int, default=600)
    build_parser.add_argument("--start-page", type=int, default=None)
    build_parser.add_argument("--end-page", type=int, default=None)
    build_parser.add_argument("--backend", default=None, help="MinerU backend, default uses pipeline")
    build_parser.add_argument("--device", default=None, help="MinerU device, default uses cuda:0")
    build_parser.add_argument("--dry-run", action="store_true")
    build_parser.add_argument("--no-staging", action="store_true")
    build_parser.add_argument("--skip-installation-check", action="store_true")

    args = parser.parse_args()

    if args.command in {None, "list"}:
        print("[demo] SE-Explorer Agent demo registry")
        tool_registry = build_registry()
        for tool in tool_registry.list_tools():
            print(f"- {tool.name}: {tool.description}")
        return 0

    if args.command == "tree":
        _print_json(list_repo_tree(path=args.path, max_depth=args.max_depth))
        return 0

    if args.command == "view":
        result = view_file(path=args.path, start=args.start, end=args.end)
        print(result["content"])
        return 0

    if args.command == "search-code":
        _print_json(grep_code(pattern=args.query, path=args.path, max_results=args.top_k))
        return 0

    if args.command == "search-docs":
        source = "all" if args.source == "raw" else args.source
        _print_json(search_docs(query=args.query, source=source, top_k=args.top_k))
        return 0

    if args.command == "search-tables":
        _print_json(search_tables(query=args.query, top_k=args.top_k))
        return 0

    if args.command == "search-figures":
        _print_json(search_figures(query=args.query, top_k=args.top_k))
        return 0

    if args.command == "ask":
        _load_project_env()
        registry = build_registry()
        if args.mock:
            llm_client = MockLLMClient(scenario=args.mock_scenario)
        else:
            _validate_real_llm_env(args.model)
            llm_client = LLMClient(model=args.model)
        agent = AgentLoop(
            registry=registry,
            llm_client=llm_client,
            max_steps=args.max_steps,
            trajectory_logger=TrajectoryLogger(),
            task_id=args.task_id,
        )
        result = agent.run(args.question)
        print("\n[agent answer]")
        print(result.answer)
        print("\n[verification]")
        if result.verification:
            _print_json(result.verification)
        else:
            print("No verification result.")
        print("\n[evidence]")
        if result.evidence:
            for item in result.evidence:
                location = item["source"]
                if item.get("line_range"):
                    location = f"{location}:{item['line_range']}"
                print(f"[{item['evidence_id']}] {item['source_type']} source={location}")
                print(str(item["content"])[:500])
        else:
            print("No evidence collected.")
        print("\n[agent observations]")
        for item in result.history:
            print(f"Step {item['step']} | {item['action']}")
            print(item["observation"])
        print("\n[outputs]")
        print(f"trajectory=outputs/trajectories/{args.task_id}.jsonl")
        print(f"evidence=outputs/evidence/{args.task_id}.jsonl")
        return 0

    if args.command == "check-rag":
        config = RAGAnythingProjectConfig.from_env()
        if args.parser is not None:
            config.parser = args.parser
        _print_json(RAGAnythingLoader(config).check_installation())
        return 0

    if args.command == "build-docs":
        config = RAGAnythingProjectConfig.from_env()
        if args.parser is not None:
            config.parser = args.parser
        config.parse_method = args.parse_method
        config.mineru_timeout = args.mineru_timeout
        config.start_page = args.start_page
        config.end_page = args.end_page
        if args.backend is not None:
            config.backend = args.backend
        if args.device is not None:
            config.device = args.device
        config.use_staging = not args.no_staging
        config.skip_installation_check = args.skip_installation_check
        result = RAGAnythingLoader(config).process(limit=args.limit, dry_run=args.dry_run)
        _print_json(result)
        return 0 if not result.get("failed_files") else 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
