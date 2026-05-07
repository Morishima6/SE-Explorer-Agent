import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rag.rag_anything_config import RAGAnythingProjectConfig
from rag.rag_anything_loader import RAGAnythingLoader


SMOKE_QUERY = "P3 parser smoke evidence"


def main() -> int:
    checks = [
        _check_smoke_fixture(),
        _check_real_process(),
        _check_search_smoke_output(),
    ]
    passed = all(item[1] for item in checks)
    for name, ok, detail in checks:
        status = "passed" if ok else "failed"
        print(f"[P3 RAG parse smoke] {name}: {status}")
        if detail:
            print(f"  {detail}")
    print(f"[P3 RAG parse smoke] overall: {'passed' if passed else 'failed'}")
    return 0 if passed else 1


def _build_config() -> RAGAnythingProjectConfig:
    config = RAGAnythingProjectConfig.from_env()
    config.books_dir = "data/p3_smoke_docs"
    config.parser_output_dir = "data/p3_smoke_parsed"
    config.parse_log_dir = "outputs/p3_smoke_parse_logs"
    config.staging_dir = ".cache/p3_smoke_raganything_inputs"
    config.max_workers = 1
    config.timeout_per_file = 60
    config.mineru_timeout = 60
    config.enable_text_fallback = True
    return config


def _check_smoke_fixture() -> tuple[str, bool, str]:
    fixture = PROJECT_ROOT / "data" / "p3_smoke_docs" / "se_explorer_smoke.md"
    if not fixture.exists():
        return "smoke fixture", False, str(fixture)
    text = fixture.read_text(encoding="utf-8", errors="replace")
    return "smoke fixture", SMOKE_QUERY in text, str(fixture)


def _check_real_process() -> tuple[str, bool, str]:
    loader = RAGAnythingLoader(_build_config())
    result = loader.process(limit=1, dry_run=False)
    fallback_files = result.get("fallback_files", [])
    ok = (
        result.get("dry_run") is False
        and result.get("total_files") == 1
        and not result.get("failed_files")
        and len(fallback_files) == 1
    )
    return "real process", ok, f"fallback_files={fallback_files}, failed_files={result.get('failed_files')}"


def _check_search_smoke_output() -> tuple[str, bool, str]:
    loader = RAGAnythingLoader(_build_config())
    results = loader.search_parsed_outputs(SMOKE_QUERY, top_k=3)
    if not results:
        return "search smoke output", False, "no search results"
    first = results[0]
    metadata = first.get("metadata", {}) if isinstance(first.get("metadata"), dict) else {}
    ok = SMOKE_QUERY.lower() in str(first.get("snippet", "")).lower() and metadata.get("doc_id") == "doc_000001"
    detail = f"source={first.get('source')}, doc_id={metadata.get('doc_id')}, score={first.get('score')}"
    return "search smoke output", ok, detail


if __name__ == "__main__":
    raise SystemExit(main())
