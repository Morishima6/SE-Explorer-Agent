import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.evidence_memory import EvidenceMemory
from agent.verifier import Verifier


def main() -> int:
    checks = [
        _check_ui_evidence_ref_allowed(),
        _check_missing_unknown_ref_still_fails(),
        _check_memory_and_ui_refs_can_coexist(),
    ]
    passed = all(item[1] for item in checks)
    for name, ok, detail in checks:
        status = "passed" if ok else "failed"
        print(f"[UI evidence alignment] {name}: {status}")
        if detail:
            print(f"      {detail}")
    print(f"[UI evidence alignment] overall: {'passed' if passed else 'failed'}")
    return 0 if passed else 1


def _check_ui_evidence_ref_allowed() -> tuple[str, bool, str]:
    task = """
    离线探索证据：
    [ev_901] UI-provided code evidence: src/pages/Planner.jsx
    ```
    const res = await generatePlan(form);
    ```
    """
    answer = "Planner.jsx 会调用 generatePlan 发起旅行规划请求。[ev_901]"
    result = Verifier().verify_final_answer(answer, EvidenceMemory(), task=task)
    missing_ref_issues = [item for item in result.issues if "references missing evidence ids" in item]
    ok = not missing_ref_issues
    return "task-provided ev_901 is accepted", ok, "; ".join(result.issues)


def _check_missing_unknown_ref_still_fails() -> tuple[str, bool, str]:
    task = "[ev_901] UI-provided code evidence: src/pages/Planner.jsx"
    answer = "这个回答引用了不存在的证据。[ev_999]"
    result = Verifier().verify_final_answer(answer, EvidenceMemory(), task=task)
    ok = any("references missing evidence ids: ev_999" in item for item in result.issues)
    return "unknown ev_999 still fails", ok, "; ".join(result.issues)


def _check_memory_and_ui_refs_can_coexist() -> tuple[str, bool, str]:
    memory = EvidenceMemory()
    memory.add(
        source_type="file",
        source="src/services/llm.js",
        content="fetch('/api/llm/chat')",
        reason="view_file returned requested file segment",
    )
    task = "[ev_901] UI-provided code evidence: src/pages/Planner.jsx"
    answer = "Planner.jsx 负责触发规划流程 [ev_901]，llm.js 调用后端接口 [ev_001]。"
    result = Verifier().verify_final_answer(answer, memory, task=task)
    missing_ref_issues = [item for item in result.issues if "references missing evidence ids" in item]
    ok = not missing_ref_issues
    return "memory ev_001 and ui ev_901 coexist", ok, "; ".join(result.issues)


if __name__ == "__main__":
    raise SystemExit(main())
