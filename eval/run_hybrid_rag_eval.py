import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from tools.search_docs import search_docs


SOURCE_MODES = ["hybrid", "rag_anything", "raw"]
REQUIRED_SCORE_PARTS = {
    "base_score",
    "normalized_base_score",
    "keyword_score",
    "coverage_score",
    "phrase_score",
    "bm25_score",
    "metadata_score",
    "source_score",
    "final_score",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate deterministic Hybrid RAG retrieval quality")
    parser.add_argument("--queries", default="eval/hybrid_rag_queries.jsonl")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    run_id = args.run_id or datetime.now().strftime("hybrid_rag_eval_%Y%m%d_%H%M%S")
    queries = _load_queries(PROJECT_ROOT / args.queries, args.limit)
    records = [_evaluate_query(query, top_k=args.top_k) for query in queries]
    summary = _build_summary(run_id=run_id, records=records)

    output_dir = PROJECT_ROOT / "outputs" / "eval_results"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{run_id}_hybrid_rag_eval.json"
    markdown_path = output_dir / f"{run_id}_hybrid_rag_eval.md"
    report = {
        "run_id": run_id,
        "queries_path": args.queries,
        "top_k": args.top_k,
        "summary": summary,
        "records": records,
        "markdown_path": str(markdown_path.relative_to(PROJECT_ROOT)),
    }
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_format_markdown(report), encoding="utf-8")

    print(f"[hybrid_rag_eval] report={json_path}")
    print(f"[hybrid_rag_eval] markdown={markdown_path}")
    print(f"[hybrid_rag_eval] query_count={summary['query_count']}")
    print(f"[hybrid_rag_eval] needs_review={summary['needs_review_count']}")
    return 0


def _load_queries(path: Path, limit: int | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        query_id = str(row.get("id", ""))
        if not query_id:
            errors.append(f"line {line_number}: missing id")
        if query_id in seen:
            errors.append(f"line {line_number}: duplicate id={query_id}")
        seen.add(query_id)
        for field in ["query", "expected_doc_hint", "expected_retrieval_strategy"]:
            if not row.get(field):
                errors.append(f"{query_id or line_number}: missing {field}")
        if not isinstance(row.get("expected_candidate_sources", []), list):
            errors.append(f"{query_id or line_number}: expected_candidate_sources must be list")
        rows.append(row)
        if limit is not None and len(rows) >= limit:
            break
    if errors:
        raise ValueError("; ".join(errors))
    print(f"[hybrid_rag_eval] loaded queries={len(rows)}")
    return rows


def _evaluate_query(query: dict[str, Any], top_k: int) -> dict[str, Any]:
    query_text = str(query["query"])
    expected_hint = str(query.get("expected_doc_hint", ""))
    print(f"[hybrid_rag_eval] query={query.get('id')} text={query_text}")
    source_results: dict[str, Any] = {}
    for source_mode in SOURCE_MODES:
        rows = search_docs(query=query_text, source=source_mode, top_k=top_k)
        source_results[source_mode] = _evaluate_source_mode(
            rows=rows,
            source_mode=source_mode,
            expected_hint=expected_hint,
            expected_strategy=str(query.get("expected_retrieval_strategy", "")),
            expected_candidate_sources=[str(item) for item in query.get("expected_candidate_sources", [])],
        )
    needs_review, review_reasons = _review_query(source_results, query)
    return {
        "id": query.get("id"),
        "query": query_text,
        "expected_doc_hint": expected_hint,
        "expected_candidate_sources": query.get("expected_candidate_sources", []),
        "expected_block_types": query.get("expected_block_types", []),
        "notes": query.get("notes", ""),
        "source_results": source_results,
        "needs_review": needs_review,
        "review_reasons": review_reasons,
    }


def _evaluate_source_mode(
    rows: list[dict[str, object]],
    source_mode: str,
    expected_hint: str,
    expected_strategy: str,
    expected_candidate_sources: list[str],
) -> dict[str, Any]:
    top1 = rows[0] if rows else {}
    top1_metadata = _metadata(top1)
    top1_score_parts = top1_metadata.get("score_parts", {}) if isinstance(top1_metadata.get("score_parts"), dict) else {}
    candidate_sources = sorted(_candidate_sources(rows))
    block_types = sorted(_block_types(rows))
    top1_has_expected_doc = _row_matches_hint(top1, expected_hint) if rows else False
    topk_has_expected_doc = any(_row_matches_hint(row, expected_hint) for row in rows)
    score_parts_complete = _score_parts_complete(rows) if source_mode == "hybrid" else None
    strategy_ok = (
        top1_metadata.get("retrieval_strategy") == expected_strategy
        if source_mode == "hybrid"
        else None
    )
    expected_sources_covered = all(source in candidate_sources for source in expected_candidate_sources)
    raw_fallback_used = "raw_text_fallback" in candidate_sources or any(
        str(_metadata(row).get("source") or _metadata(row).get("source_kind")) == "raw_text_fallback"
        for row in rows
    )
    return {
        "source_mode": source_mode,
        "result_count": len(rows),
        "top1_source": top1.get("source") if isinstance(top1, dict) else None,
        "top1_score": top1.get("score") if isinstance(top1, dict) else None,
        "top1_content_type": top1.get("content_type") if isinstance(top1, dict) else None,
        "top1_snippet": _shorten(str(top1.get("snippet", ""))) if isinstance(top1, dict) else "",
        "top1_has_expected_doc": top1_has_expected_doc,
        "topk_has_expected_doc": topk_has_expected_doc,
        "top1_retrieval_strategy": top1_metadata.get("retrieval_strategy"),
        "top1_bm25_score": top1_score_parts.get("bm25_score"),
        "candidate_sources": candidate_sources,
        "expected_candidate_sources_covered": expected_sources_covered,
        "block_types": block_types,
        "score_parts_complete": score_parts_complete,
        "metadata_complete": _metadata_complete(top1_metadata, source_mode),
        "raw_fallback_used": raw_fallback_used,
    }


def _review_query(source_results: dict[str, Any], query: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    hybrid = source_results.get("hybrid", {})
    if not hybrid.get("topk_has_expected_doc"):
        reasons.append("hybrid top-k did not include expected doc hint")
    if hybrid.get("top1_retrieval_strategy") != query.get("expected_retrieval_strategy"):
        reasons.append("hybrid top-1 missing expected retrieval_strategy")
    if hybrid.get("score_parts_complete") is not True:
        reasons.append("hybrid score_parts incomplete")
    if hybrid.get("metadata_complete") is not True:
        reasons.append("hybrid metadata incomplete")
    expected_sources = [str(item) for item in query.get("expected_candidate_sources", [])]
    if expected_sources and not hybrid.get("expected_candidate_sources_covered"):
        reasons.append("hybrid did not cover expected candidate_sources")
    return bool(reasons), reasons


def _build_summary(run_id: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    by_source = {source: _source_summary(records, source) for source in SOURCE_MODES}
    hybrid_records = [record["source_results"]["hybrid"] for record in records]
    block_type_distribution: dict[str, int] = {}
    candidate_source_distribution: dict[str, int] = {}
    for result in hybrid_records:
        for block_type in result.get("block_types", []):
            block_type_distribution[block_type] = block_type_distribution.get(block_type, 0) + 1
        for source in result.get("candidate_sources", []):
            candidate_source_distribution[source] = candidate_source_distribution.get(source, 0) + 1
    needs_review = [record for record in records if record.get("needs_review") is True]
    return {
        "run_id": run_id,
        "query_count": len(records),
        "source_modes": SOURCE_MODES,
        "by_source_mode": by_source,
        "hybrid_candidate_source_distribution": candidate_source_distribution,
        "hybrid_block_type_distribution": block_type_distribution,
        "hybrid_fused_query_count": sum(
            1 for result in hybrid_records if len(result.get("candidate_sources", [])) >= 2
        ),
        "hybrid_raw_fallback_used_count": sum(
            1 for result in hybrid_records if result.get("raw_fallback_used") is True
        ),
        "hybrid_top1_bm25_positive_count": sum(
            1 for result in hybrid_records if float(result.get("top1_bm25_score") or 0) > 0
        ),
        "needs_review_count": len(needs_review),
        "needs_review_query_ids": [str(record.get("id")) for record in needs_review],
    }


def _source_summary(records: list[dict[str, Any]], source_mode: str) -> dict[str, Any]:
    results = [record["source_results"][source_mode] for record in records]
    count = len(results)
    return {
        "query_count": count,
        "non_empty_rate": _rate(results, "result_count", lambda value: int(value) > 0),
        "top1_expected_doc_rate": _rate(results, "top1_has_expected_doc"),
        "topk_expected_doc_rate": _rate(results, "topk_has_expected_doc"),
        "metadata_complete_rate": _rate(results, "metadata_complete"),
        "score_parts_complete_rate": _rate(results, "score_parts_complete")
        if source_mode == "hybrid"
        else None,
        "raw_fallback_used_count": sum(1 for result in results if result.get("raw_fallback_used") is True),
    }


def _rate(rows: list[dict[str, Any]], key: str, predicate: Any | None = None) -> float:
    if not rows:
        return 0.0
    if predicate is None:
        matched = sum(1 for row in rows if row.get(key) is True)
    else:
        matched = sum(1 for row in rows if predicate(row.get(key, 0)))
    return matched / len(rows)


def _candidate_sources(rows: list[dict[str, object]]) -> set[str]:
    sources: set[str] = set()
    for row in rows:
        metadata = _metadata(row)
        values = metadata.get("candidate_sources", [])
        if isinstance(values, list):
            sources.update(str(item) for item in values)
        if metadata.get("source") == "raw_text_fallback" or metadata.get("source_kind") == "raw_text_fallback":
            sources.add("raw_text_fallback")
    return sources


def _block_types(rows: list[dict[str, object]]) -> set[str]:
    values: set[str] = set()
    for row in rows:
        metadata = _metadata(row)
        block_type = metadata.get("block_type") or row.get("content_type")
        if block_type:
            values.add(str(block_type))
    return values


def _score_parts_complete(rows: list[dict[str, object]]) -> bool:
    if not rows:
        return False
    for row in rows:
        score_parts = _metadata(row).get("score_parts", {})
        if not isinstance(score_parts, dict) or not REQUIRED_SCORE_PARTS.issubset(score_parts):
            return False
    return True


def _metadata_complete(metadata: dict[str, Any], source_mode: str) -> bool:
    if source_mode == "raw":
        return bool(metadata)
    candidate_sources = metadata.get("candidate_sources", [])
    if isinstance(candidate_sources, list) and "raw_text_fallback" in candidate_sources:
        return (
            metadata.get("retrieval_strategy") == "hybrid_rag_anything"
            and isinstance(metadata.get("score_parts"), dict)
            and bool(metadata.get("original_path") or metadata.get("source"))
        )
    required = {"doc_id", "original_path", "parsed_path"}
    return all(metadata.get(key) for key in required)


def _row_matches_hint(row: dict[str, object], expected_hint: str) -> bool:
    if not expected_hint:
        return True
    text = " ".join(
        [
            str(row.get("source", "")),
            str(row.get("snippet", "")),
            json.dumps(_metadata(row), ensure_ascii=False),
        ]
    ).lower()
    return expected_hint.lower() in text


def _metadata(row: dict[str, object]) -> dict[str, Any]:
    metadata = row.get("metadata", {}) if isinstance(row, dict) else {}
    return metadata if isinstance(metadata, dict) else {}


def _format_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Hybrid RAG Retrieval Evaluation",
        "",
        f"Run ID: `{report['run_id']}`",
        f"Queries: `{summary['query_count']}`",
        f"Top K: `{report['top_k']}`",
        "",
        "## Source Mode Summary",
        "",
        "| Source Mode | Non-empty | Top-1 Expected | Top-k Expected | Metadata Complete | Score Parts Complete | Raw Fallback Used |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for source_mode, item in summary["by_source_mode"].items():
        score_parts = item["score_parts_complete_rate"]
        score_parts_text = "n/a" if score_parts is None else f"{float(score_parts):.2f}"
        lines.append(
            f"| {source_mode} | {float(item['non_empty_rate']):.2f} | "
            f"{float(item['top1_expected_doc_rate']):.2f} | {float(item['topk_expected_doc_rate']):.2f} | "
            f"{float(item['metadata_complete_rate']):.2f} | {score_parts_text} | "
            f"{item['raw_fallback_used_count']} |"
        )
    lines.extend(
        [
            "",
            "## Hybrid Coverage",
            "",
            f"- Fused query count: {summary['hybrid_fused_query_count']}",
            f"- Raw fallback used count: {summary['hybrid_raw_fallback_used_count']}",
            f"- Top-1 BM25 positive count: {summary['hybrid_top1_bm25_positive_count']}",
            f"- Needs review: {summary['needs_review_count']}",
            "",
            "Candidate source distribution:",
            "",
        ]
    )
    for source, count in sorted(summary["hybrid_candidate_source_distribution"].items()):
        lines.append(f"- `{source}`: {count}")
    lines.extend(["", "Block type distribution:", ""])
    for block_type, count in sorted(summary["hybrid_block_type_distribution"].items()):
        lines.append(f"- `{block_type}`: {count}")
    lines.extend(
        [
            "",
            "## Query-Level Results",
            "",
            "| Query ID | Query | Hybrid Top-1 | BM25 | Hybrid Sources | Hybrid Blocks | Review |",
            "|---|---|---:|---:|---|---|---|",
        ]
    )
    for record in report["records"]:
        hybrid = record["source_results"]["hybrid"]
        sources = ", ".join(hybrid.get("candidate_sources", []))
        blocks = ", ".join(hybrid.get("block_types", []))
        review = "; ".join(record.get("review_reasons", []))
        lines.append(
            f"| {record['id']} | {record['query']} | {hybrid.get('top1_has_expected_doc')} | "
            f"{hybrid.get('top1_bm25_score')} | "
            f"{sources} | {blocks} | {review} |"
        )
    lines.append("")
    return "\n".join(lines)


def _shorten(text: str, max_chars: int = 260) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


if __name__ == "__main__":
    raise SystemExit(main())
