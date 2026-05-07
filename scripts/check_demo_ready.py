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


def main() -> int:
    configure_project_cache(PROJECT_ROOT)

    env_path = PROJECT_ROOT / ".env"
    parsed_dir = PROJECT_ROOT / "data" / "parsed"
    outputs_dir = PROJECT_ROOT / "outputs"

    env_exists = env_path.exists()
    parsed_docs_exists = _has_parsed_docs(parsed_dir)
    imports_ok = _check_imports()
    outputs_writable = _check_outputs_writable(outputs_dir)
    ready_for_mock = imports_ok and parsed_docs_exists and outputs_writable

    print(f"[check_demo_ready] project root: {PROJECT_ROOT}")
    print(f"[check_demo_ready] .env exists: {str(env_exists).lower()}")
    print(f"[check_demo_ready] parsed docs exists: {str(parsed_docs_exists).lower()}")
    print(f"[check_demo_ready] core imports ok: {str(imports_ok).lower()}")
    print(f"[check_demo_ready] outputs writable: {str(outputs_writable).lower()}")
    print(f"[check_demo_ready] ready for mock demo: {str(ready_for_mock).lower()}")

    if not parsed_docs_exists:
        print("[check_demo_ready] hint: run build-docs before the mock ask demo.")

    return 0 if ready_for_mock else 1


def _has_parsed_docs(parsed_dir: Path) -> bool:
    if not parsed_dir.exists():
        return False
    for pattern in ("*.md", "*.json"):
        if any(parsed_dir.rglob(pattern)):
            return True
    return False


def _check_imports() -> bool:
    try:
        from agent.llm_client import MockLLMClient
        from agent.loop import AgentLoop
        from agent.tool_registry import ToolRegistry
        from agent.verifier import Verifier
        from tools.search_docs import search_docs
    except ImportError as exc:
        print(f"[check_demo_ready] import failed: {exc}")
        return False

    _ = (AgentLoop, MockLLMClient, ToolRegistry, Verifier, search_docs)
    return True


def _check_outputs_writable(outputs_dir: Path) -> bool:
    outputs_dir.mkdir(parents=True, exist_ok=True)
    probe_path = outputs_dir / ".demo_ready_probe"
    try:
        probe_path.write_text("ok", encoding="utf-8")
        probe_path.unlink()
    except OSError as exc:
        print(f"[check_demo_ready] outputs write failed: {exc}")
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
