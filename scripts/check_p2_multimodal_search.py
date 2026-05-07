import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from agent.evidence_extractor import extract_evidence_from_tool_result
from agent.evidence_memory import EvidenceMemory
from agent.llm_client import MockLLMClient
from agent.loop import AgentLoop
from agent.trajectory import TrajectoryLogger
from demo.app import build_registry
from tools.search_figures import search_figures
from tools.search_tables import search_tables


def main() -> int:
    checks = [
        _check_tool_registry(),
        _check_search_tables_callable(),
        _check_search_figures_metadata(),
        _check_table_evidence_extraction(),
        _check_figure_evidence_extraction(),
        _check_multimodal_agent_chain(),
    ]
    passed = all(item[1] for item in checks)
    for name, ok, detail in checks:
        status = "passed" if ok else "failed"
        print(f"[P2 multimodal] {name}: {status}")
        if detail:
            print(f"      {detail}")
    print(f"[P2 multimodal] overall: {'passed' if passed else 'failed'}")
    return 0 if passed else 1


def _check_tool_registry() -> tuple[str, bool, str]:
    names = {tool.name for tool in build_registry().list_tools()}
    ok = {"search_tables", "search_figures"}.issubset(names)
    return "tool registry", ok, "" if ok else str(sorted(names))


def _check_search_tables_callable() -> tuple[str, bool, str]:
    rows = search_tables("software engineering", top_k=3)
    ok = isinstance(rows, list)
    return "search_tables callable", ok, "" if ok else str(rows)


def _check_search_figures_metadata() -> tuple[str, bool, str]:
    rows = search_figures("image", top_k=3)
    if not rows:
        return "search_figures metadata", False, "no figure/image blocks found in current parsed outputs"
    metadata = rows[0].get("metadata", {})
    required = {"doc_id", "original_path", "parsed_path", "block_type", "page_idx", "page"}
    missing = sorted(key for key in required if key not in metadata or metadata.get(key) in {None, ""})
    ok = not missing and rows[0].get("content_type") in {"image", "figure"}
    return "search_figures metadata", ok, "" if ok else f"missing={missing}, row={rows[0]}"


def _check_table_evidence_extraction() -> tuple[str, bool, str]:
    memory = EvidenceMemory()
    rows = [
        {
            "source": "books/demo.pdf",
            "content_type": "table",
            "score": 1,
            "snippet": "table demo evidence",
            "metadata": {"doc_id": "doc_test", "block_type": "table", "page": 1},
        }
    ]
    evidence_ids = extract_evidence_from_tool_result(
        tool_name="search_tables",
        args={"query": "table demo", "top_k": 1},
        result=rows,
        evidence_memory=memory,
    )
    evidence = memory.to_dicts()
    ok = len(evidence_ids) == 1 and evidence[0]["source_type"] == "table"
    return "table evidence extraction", ok, "" if ok else str(evidence)


def _check_figure_evidence_extraction() -> tuple[str, bool, str]:
    rows = search_figures("image", top_k=1)
    memory = EvidenceMemory()
    evidence_ids = extract_evidence_from_tool_result(
        tool_name="search_figures",
        args={"query": "image", "top_k": 1},
        result=rows,
        evidence_memory=memory,
    )
    evidence = memory.to_dicts()
    ok = (
        len(evidence_ids) == 1
        and len(evidence) == 1
        and evidence[0]["source_type"] == "figure"
        and evidence[0]["metadata"].get("block_type") in {"image", "figure"}
    )
    return "figure evidence extraction", ok, "" if ok else str(evidence)


def _check_multimodal_agent_chain() -> tuple[str, bool, str]:
    agent = AgentLoop(
        registry=build_registry(),
        llm_client=MockLLMClient(scenario="multimodal"),
        max_steps=4,
        trajectory_logger=TrajectoryLogger(),
        task_id="p2_multimodal_demo",
    )
    result = agent.run("Explain document and figure evidence from parsed RAG-Anything outputs")
    evidence_types = {str(item["source_type"]) for item in result.evidence}
    actions = [str(item["action"]) for item in result.history]
    ok = (
        result.verification is not None
        and result.verification.get("passed") is True
        and {"doc", "figure"}.issubset(evidence_types)
        and any("search_figures" in action for action in actions)
        and "[ev_001]" in result.answer
        and "[ev_002]" in result.answer
    )
    detail = {
        "verification": result.verification,
        "evidence_types": sorted(evidence_types),
        "actions": actions,
        "answer": result.answer,
    }
    return "multimodal agent chain", ok, "" if ok else str(detail)


if __name__ == "__main__":
    raise SystemExit(main())
