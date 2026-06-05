import json
import subprocess
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "p3_hybrid_rag_eval_check"
QUERY_PATH = PROJECT_ROOT / "eval" / "hybrid_rag_queries.jsonl"
JSON_REPORT = PROJECT_ROOT / "outputs" / "eval_results" / f"{RUN_ID}_hybrid_rag_eval.json"
MARKDOWN_REPORT = PROJECT_ROOT / "outputs" / "eval_results" / f"{RUN_ID}_hybrid_rag_eval.md"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    checks = [
        _check_query_set(),
        _check_eval_runner(),
        _check_json_report(),
        _check_markdown_report(),
        _check_hybrid_metadata(),
        _check_source_mode_comparison(),
    ]
    passed = all(item[1] for item in checks)
    for name, ok, detail in checks:
        status = "passed" if ok else "failed"
        print(f"[P3 hybrid RAG eval] {name}: {status}")
        if detail:
            print(f"  {detail}")
    print(f"[P3 hybrid RAG eval] overall: {'passed' if passed else 'failed'}")
    return 0 if passed else 1


def _check_query_set() -> tuple[str, bool, str]:
    if not QUERY_PATH.exists():
        return "query set", False, f"missing {QUERY_PATH}"
    rows = _load_jsonl(QUERY_PATH)
    ids = [str(row.get("id")) for row in rows]
    required_fields = {"id", "query", "expected_doc_hint", "expected_candidate_sources", "expected_retrieval_strategy"}
    missing_details: list[str] = []
    for row in rows:
        missing = sorted(field for field in required_fields if not row.get(field))
        if missing:
            missing_details.append(f"{row.get('id')}: missing={missing}")
    ok = len(rows) >= 6 and len(ids) == len(set(ids)) and not missing_details
    detail = f"query_count={len(rows)}" if ok else "; ".join(missing_details) or f"ids={ids}"
    return "query set", ok, detail


def _check_eval_runner() -> tuple[str, bool, str]:
    command = [
        sys.executable,
        "eval/run_hybrid_rag_eval.py",
        "--run-id",
        RUN_ID,
        "--top-k",
        "5",
    ]
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    output = completed.stdout + completed.stderr
    if completed.returncode != 0:
        return "eval runner", False, output[-2000:]
    ok = JSON_REPORT.exists() and MARKDOWN_REPORT.exists()
    return "eval runner", ok, "" if ok else output[-1000:]


def _check_json_report() -> tuple[str, bool, str]:
    report = _load_report()
    summary = report.get("summary", {})
    ok = (
        report.get("run_id") == RUN_ID
        and summary.get("query_count", 0) >= 6
        and isinstance(report.get("records"), list)
        and len(report.get("records", [])) == summary.get("query_count")
    )
    return "json report", ok, "" if ok else str(summary)


def _check_markdown_report() -> tuple[str, bool, str]:
    if not MARKDOWN_REPORT.exists():
        return "markdown report", False, f"missing {MARKDOWN_REPORT}"
    text = MARKDOWN_REPORT.read_text(encoding="utf-8", errors="replace")
    ok = (
        "# Hybrid RAG Retrieval Evaluation" in text
        and "Source Mode Summary" in text
        and "Query-Level Results" in text
    )
    return "markdown report", ok, "" if ok else text[:500]


def _check_hybrid_metadata() -> tuple[str, bool, str]:
    report = _load_report()
    records = report.get("records", [])
    if not isinstance(records, list) or not records:
        return "hybrid metadata", False, "missing records"
    hybrid_results = [
        record.get("source_results", {}).get("hybrid", {})
        for record in records
        if isinstance(record, dict)
    ]
    score_parts_ok = all(result.get("score_parts_complete") is True for result in hybrid_results)
    metadata_ok = all(result.get("metadata_complete") is True for result in hybrid_results)
    strategy_ok = all(result.get("top1_retrieval_strategy") == "hybrid_rag_anything" for result in hybrid_results)
    fused_count = int(report.get("summary", {}).get("hybrid_fused_query_count", 0))
    ok = score_parts_ok and metadata_ok and strategy_ok and fused_count >= 1
    detail = "" if ok else f"score_parts={score_parts_ok}, metadata={metadata_ok}, strategy={strategy_ok}, fused={fused_count}"
    return "hybrid metadata", ok, detail


def _check_source_mode_comparison() -> tuple[str, bool, str]:
    report = _load_report()
    summary = report.get("summary", {})
    by_source = summary.get("by_source_mode", {})
    modes_ok = {"hybrid", "rag_anything", "raw"}.issubset(by_source)
    raw_used = int(summary.get("hybrid_raw_fallback_used_count", 0)) >= 1
    bm25_positive = int(summary.get("hybrid_top1_bm25_positive_count", 0)) >= 1
    candidate_distribution = summary.get("hybrid_candidate_source_distribution", {})
    parsed_seen = "rag_anything_parsed" in candidate_distribution
    block_seen = "rag_anything_block" in candidate_distribution
    ok = modes_ok and raw_used and bm25_positive and parsed_seen and block_seen
    detail = "" if ok else (
        f"modes={by_source.keys()}, raw_used={raw_used}, bm25_positive={bm25_positive}, "
        f"candidates={candidate_distribution}"
    )
    return "source mode comparison", ok, detail


def _load_report() -> dict[str, Any]:
    if not JSON_REPORT.exists():
        return {}
    return json.loads(JSON_REPORT.read_text(encoding="utf-8", errors="replace"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
