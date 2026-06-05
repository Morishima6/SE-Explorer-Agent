import sys
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from agent.evidence_extractor import extract_evidence_from_tool_result
from agent.evidence_memory import EvidenceMemory
from agent.llm_client import MockLLMClient
from agent.verifier import Verifier
from eval.run_real_baseline_sample import _build_dry_run_records
from rag.hybrid_retriever import HybridRetriever
from tools.search_docs import search_docs


QUERY = "Graduate Software Engineering"


def main() -> int:
    checks = [
        _check_hybrid_retriever(),
        _check_search_docs_hybrid_source(),
        _check_search_docs_all_source(),
        _check_evidence_metadata(),
        _check_mock_agent_uses_hybrid_source(),
        _check_verifier_suggests_hybrid_source(),
        _check_real_baseline_preview_uses_hybrid(),
    ]
    passed = all(item[1] for item in checks)
    for name, ok, detail in checks:
        status = "passed" if ok else "failed"
        print(f"[P3 hybrid RAG] {name}: {status}")
        if detail:
            print(f"  {detail}")
    print(f"[P3 hybrid RAG] overall: {'passed' if passed else 'failed'}")
    return 0 if passed else 1


def _check_hybrid_retriever() -> tuple[str, bool, str]:
    rows = HybridRetriever().search(QUERY, top_k=5)
    ok, detail = _validate_hybrid_rows(rows)
    return "hybrid retriever", ok, detail


def _check_search_docs_hybrid_source() -> tuple[str, bool, str]:
    rows = search_docs(QUERY, source="hybrid", top_k=5)
    ok, detail = _validate_hybrid_rows(rows)
    return "search_docs source=hybrid", ok, detail


def _check_search_docs_all_source() -> tuple[str, bool, str]:
    rows = search_docs(QUERY, source="all", top_k=5)
    ok, detail = _validate_hybrid_rows(rows)
    return "search_docs source=all", ok, detail


def _check_evidence_metadata() -> tuple[str, bool, str]:
    rows = search_docs(QUERY, source="hybrid", top_k=3)
    memory = EvidenceMemory()
    evidence_ids = extract_evidence_from_tool_result(
        tool_name="search_docs",
        args={"query": QUERY, "source": "hybrid", "top_k": 3},
        result=rows,
        evidence_memory=memory,
    )
    evidence = memory.to_dicts()
    if not evidence_ids or not evidence:
        return "evidence metadata", False, "no evidence extracted"
    metadata = evidence[0].get("metadata", {})
    ok = (
        isinstance(metadata, dict)
        and metadata.get("retrieval_strategy") == "hybrid_rag_anything"
        and isinstance(metadata.get("score_parts"), dict)
        and bool(metadata.get("candidate_sources"))
        and bool(metadata.get("doc_id"))
    )
    return "evidence metadata", ok, "" if ok else str(evidence[0])


def _check_mock_agent_uses_hybrid_source() -> tuple[str, bool, str]:
    action_text = MockLLMClient("docs").complete(
        [
            {
                "role": "user",
                "content": (
                    "User Task:\nGraduate Software Engineering\n\n"
                    "Available Tools:\nsearch_docs"
                ),
            }
        ]
    )
    action = json.loads(action_text)
    args = action.get("args", {})
    ok = action.get("tool") == "search_docs" and args.get("source") == "hybrid"
    return "mock agent source=hybrid", ok, "" if ok else action_text


def _check_verifier_suggests_hybrid_source() -> tuple[str, bool, str]:
    result = Verifier().verify_final_answer("", EvidenceMemory(), task=QUERY)
    suggested = result.suggested_next_action or {}
    args = suggested.get("args", {}) if isinstance(suggested.get("args"), dict) else {}
    ok = suggested.get("tool") == "search_docs" and args.get("source") == "hybrid"
    return "verifier suggested source=hybrid", ok, "" if ok else str(suggested)


def _check_real_baseline_preview_uses_hybrid() -> tuple[str, bool, str]:
    records = _build_dry_run_records("p3_hybrid_rag_check", QUERY, max_steps=4, model=None)
    rag_record = next((item for item in records if item.get("baseline") == "rag_only_real"), {})
    preview = rag_record.get("retrieval_preview", [])
    if not isinstance(preview, list) or not preview:
        return "real baseline preview source=hybrid", False, "missing retrieval_preview"
    first = preview[0]
    if not isinstance(first, dict):
        return "real baseline preview source=hybrid", False, str(first)
    ok = (
        first.get("retrieval_strategy") == "hybrid_rag_anything"
        and isinstance(first.get("candidate_sources"), list)
        and bool(first.get("candidate_sources"))
    )
    return "real baseline preview source=hybrid", ok, "" if ok else str(first)


def _validate_hybrid_rows(rows: list[dict[str, object]]) -> tuple[bool, str]:
    if not rows:
        return False, "no rows returned"
    scores = [float(row.get("score", 0)) for row in rows]
    if scores != sorted(scores, reverse=True):
        return False, f"scores not reranked descending: {scores}"
    first = rows[0]
    metadata = first.get("metadata", {})
    if not isinstance(metadata, dict):
        return False, f"metadata is not dict: {first}"
    score_parts = metadata.get("score_parts", {})
    required_score_parts = {
        "base_score",
        "keyword_score",
        "coverage_score",
        "phrase_score",
        "bm25_score",
        "metadata_score",
        "source_score",
        "final_score",
    }
    missing = sorted(item for item in required_score_parts if item not in score_parts)
    if metadata.get("retrieval_strategy") != "hybrid_rag_anything":
        return False, f"missing retrieval_strategy: {metadata}"
    if missing:
        return False, f"missing score_parts={missing}: {metadata}"
    if float(score_parts.get("bm25_score", 0)) <= 0:
        return False, f"bm25_score not positive: {metadata}"
    if not metadata.get("candidate_sources"):
        return False, f"missing candidate_sources: {metadata}"
    if not metadata.get("doc_id"):
        return False, f"missing doc_id: {metadata}"
    return True, f"top_source={first.get('source')}, score={first.get('score')}, sources={metadata.get('candidate_sources')}"


if __name__ == "__main__":
    raise SystemExit(main())
