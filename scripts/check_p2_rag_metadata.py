import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from agent.evidence_extractor import extract_evidence_from_tool_result
from agent.evidence_memory import EvidenceMemory
from rag.rag_anything_loader import RAGAnythingLoader
from tools.search_docs import search_docs


def main() -> int:
    checks = [
        _check_document_lookup(),
        _check_parsed_search_metadata(),
        _check_search_docs_compatibility(),
        _check_evidence_metadata_preserved(),
    ]
    passed = all(item[1] for item in checks)
    for name, ok, detail in checks:
        status = "passed" if ok else "failed"
        print(f"[P2 RAG metadata] {name}: {status}")
        if detail:
            print(f"      {detail}")
    print(f"[P2 RAG metadata] overall: {'passed' if passed else 'failed'}")
    return 0 if passed else 1


def _check_document_lookup() -> tuple[str, bool, str]:
    loader = RAGAnythingLoader()
    lookup = loader.get_document_metadata_lookup()
    if not lookup:
        return "document lookup", False, "missing outputs/parse_logs manifest records"
    first = next(iter(lookup.values()))
    ok = bool(first.get("doc_id")) and bool(first.get("original_path") or first.get("path"))
    return "document lookup", ok, "" if ok else str(first)


def _check_parsed_search_metadata() -> tuple[str, bool, str]:
    loader = RAGAnythingLoader()
    rows = loader.search_parsed_outputs("Graduate Software Engineering", top_k=5)
    if not rows:
        return "parsed search metadata", False, "no parsed search results; run RAG-Anything parsing first"
    required = {"doc_id", "original_path", "parsed_path", "parser", "parse_method", "source_kind"}
    missing_details: list[str] = []
    has_block = False
    for row in rows:
        metadata = row.get("metadata", {})
        if not isinstance(metadata, dict):
            missing_details.append("metadata is not dict")
            continue
        missing = sorted(key for key in required if not metadata.get(key))
        if missing:
            missing_details.append(f"missing={missing} metadata={metadata}")
        if metadata.get("source_kind") == "rag_anything_block":
            has_block = True
            if "block_type" not in metadata or "page_idx" not in metadata or "page" not in metadata:
                missing_details.append(f"block metadata incomplete: {metadata}")
    ok = not missing_details and has_block
    return "parsed search metadata", ok, "" if ok else " | ".join(missing_details[:3])


def _check_search_docs_compatibility() -> tuple[str, bool, str]:
    rows = search_docs("Graduate Software Engineering", top_k=3)
    ok = (
        isinstance(rows, list)
        and bool(rows)
        and all(isinstance(row, dict) for row in rows)
        and all("snippet" in row and "metadata" in row for row in rows)
    )
    return "search_docs compatibility", ok, "" if ok else str(rows[:1])


def _check_evidence_metadata_preserved() -> tuple[str, bool, str]:
    rows = search_docs("Graduate Software Engineering", top_k=3)
    memory = EvidenceMemory()
    evidence_ids = extract_evidence_from_tool_result(
        tool_name="search_docs",
        args={"query": "Graduate Software Engineering", "source": "hybrid", "top_k": 3},
        result=rows,
        evidence_memory=memory,
    )
    evidence = memory.to_dicts()
    if not evidence_ids or not evidence:
        return "evidence metadata preserved", False, "no evidence extracted"
    metadata = evidence[0].get("metadata", {})
    ok = (
        isinstance(metadata, dict)
        and bool(metadata.get("doc_id"))
        and bool(metadata.get("original_path"))
        and bool(metadata.get("parsed_path"))
    )
    return "evidence metadata preserved", ok, "" if ok else str(evidence[0])


if __name__ == "__main__":
    raise SystemExit(main())
