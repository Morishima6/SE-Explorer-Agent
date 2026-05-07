import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rag.cache_config import configure_project_cache
from rag.rag_anything_config import RAGAnythingProjectConfig
from rag.rag_anything_loader import RAGAnythingLoader


def main() -> int:
    checks = [
        _check_default_parser(),
        _check_project_cache_env(),
        _check_parser_installation(),
        _check_dry_run_staging(),
    ]
    passed = all(item[1] for item in checks)
    for name, ok, detail in checks:
        status = "passed" if ok else "failed"
        print(f"[P3 RAG parser env] {name}: {status}")
        if detail:
            print(f"  {detail}")
    print(f"[P3 RAG parser env] overall: {'passed' if passed else 'failed'}")
    return 0 if passed else 1


def _check_default_parser() -> tuple[str, bool, str]:
    config = RAGAnythingProjectConfig.from_env()
    ok = config.parser == "paddleocr"
    return "default parser", ok, f"parser={config.parser}"


def _check_project_cache_env() -> tuple[str, bool, str]:
    resolved = configure_project_cache(PROJECT_ROOT)
    cache_root = PROJECT_ROOT / ".cache"
    required = {
        "PADDLE_PDX_CACHE_HOME": cache_root / "paddlex",
        "MPLCONFIGDIR": cache_root / "matplotlib",
        "PADDLEOCR_HOME": cache_root / "paddleocr",
    }
    mismatches = [
        f"{key}={resolved.get(key)}"
        for key, expected in required.items()
        if Path(str(resolved.get(key, ""))).resolve() != expected.resolve()
    ]
    return "project cache env", not mismatches, "; ".join(mismatches)


def _check_parser_installation() -> tuple[str, bool, str]:
    result = RAGAnythingLoader().check_installation()
    ok = result.get("raganything_imported") is True and result.get("parser_installed") is True
    detail = f"parser={result.get('parser')}, parser_installed={result.get('parser_installed')}"
    if result.get("error"):
        detail += f", error={result.get('error')}"
    return "parser installation", ok, detail


def _check_dry_run_staging() -> tuple[str, bool, str]:
    loader = RAGAnythingLoader()
    result = loader.process(limit=1, dry_run=True)
    files = [str(item) for item in result.get("successful_files", [])]
    ok = (
        result.get("dry_run") is True
        and result.get("total_files", 0) >= 1
        and not result.get("failed_files")
        and any(".cache" in item and "raganything_inputs" in item for item in files)
    )
    return "dry-run staging", ok, f"total_files={result.get('total_files')}, files={files[:1]}"


if __name__ == "__main__":
    raise SystemExit(main())
