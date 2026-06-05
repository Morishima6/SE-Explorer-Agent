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
from agent.verifier import Verifier
from demo.app import build_registry
from tools.edit_file import edit_file


FIXTURE = PROJECT_ROOT / "outputs" / "edit_file_sandbox" / "mock_edit_fixture.py"


def main() -> int:
    _reset_fixture()
    checks = [
        _check_registry(),
        _check_blocked_outside_sandbox(),
        _check_dry_run_no_write(),
        _check_apply_edit_with_backup(),
        _check_edit_evidence(),
        _check_verifier_edit_claim(),
        _check_agent_edit_chain(),
    ]
    passed = all(item[1] for item in checks)
    for name, ok, detail in checks:
        status = "passed" if ok else "failed"
        print(f"[P3 edit_file sandbox] {name}: {status}")
        if detail:
            print(f"      {detail}")
    print(f"[P3 edit_file sandbox] overall: {'passed' if passed else 'failed'}")
    return 0 if passed else 1


def _reset_fixture() -> None:
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text('VALUE = "before"\n', encoding="utf-8")


def _check_registry() -> tuple[str, bool, str]:
    names = {tool.name for tool in build_registry().list_tools()}
    ok = "edit_file" in names
    return "tool registry", ok, "" if ok else str(sorted(names))


def _check_blocked_outside_sandbox() -> tuple[str, bool, str]:
    result = edit_file(
        path="README.md",
        operation="append",
        append_text="\nblocked edit\n",
        apply=True,
    )
    ok = result.get("success") is False and "outside allowed edit sandbox" in str(result.get("error", ""))
    return "blocked outside sandbox", ok, "" if ok else str(result)


def _check_dry_run_no_write() -> tuple[str, bool, str]:
    _reset_fixture()
    result = edit_file(
        path="outputs/edit_file_sandbox/mock_edit_fixture.py",
        operation="replace",
        old_text='VALUE = "before"\n',
        new_text='VALUE = "after"\n',
        apply=False,
    )
    text = FIXTURE.read_text(encoding="utf-8")
    ok = (
        result.get("success") is True
        and result.get("apply") is False
        and result.get("changed") is True
        and 'VALUE = "before"' in text
        and "VALUE = \"after\"" in str(result.get("diff", ""))
    )
    return "dry-run no write", ok, "" if ok else str({"result": result, "text": text})


def _check_apply_edit_with_backup() -> tuple[str, bool, str]:
    _reset_fixture()
    result = edit_file(
        path="outputs/edit_file_sandbox/mock_edit_fixture.py",
        operation="replace",
        old_text='VALUE = "before"\n',
        new_text='VALUE = "after"\n',
        apply=True,
        evidence_ids=["ev_001"],
    )
    text = FIXTURE.read_text(encoding="utf-8")
    backup_path = PROJECT_ROOT / str(result.get("backup_path", ""))
    ok = (
        result.get("success") is True
        and result.get("apply") is True
        and result.get("changed") is True
        and 'VALUE = "after"' in text
        and backup_path.exists()
        and result.get("before_hash") != result.get("after_hash")
    )
    return "apply edit with backup", ok, "" if ok else str({"result": result, "text": text})


def _check_edit_evidence() -> tuple[str, bool, str]:
    _reset_fixture()
    memory = EvidenceMemory()
    result = edit_file(
        path="outputs/edit_file_sandbox/mock_edit_fixture.py",
        operation="replace",
        old_text='VALUE = "before"\n',
        new_text='VALUE = "after"\n',
        apply=True,
    )
    evidence_ids = extract_evidence_from_tool_result(
        tool_name="edit_file",
        args={"path": "outputs/edit_file_sandbox/mock_edit_fixture.py", "operation": "replace", "apply": True},
        result=result,
        evidence_memory=memory,
    )
    evidence = memory.to_dicts()
    ok = (
        len(evidence_ids) == 1
        and len(evidence) == 1
        and evidence[0]["source_type"] == "edit"
        and evidence[0]["metadata"].get("apply") is True
        and evidence[0]["metadata"].get("backup_path")
    )
    return "edit evidence", ok, "" if ok else str(evidence)


def _check_verifier_edit_claim() -> tuple[str, bool, str]:
    _reset_fixture()
    verifier = Verifier()
    empty_memory = EvidenceMemory()
    missing = verifier.verify_final_answer(
        "已经修改文件 outputs/edit_file_sandbox/mock_edit_fixture.py。",
        empty_memory,
    )

    memory = EvidenceMemory()
    result = edit_file(
        path="outputs/edit_file_sandbox/mock_edit_fixture.py",
        operation="replace",
        old_text='VALUE = "before"\n',
        new_text='VALUE = "after"\n',
        apply=True,
    )
    extract_evidence_from_tool_result(
        tool_name="edit_file",
        args={"path": "outputs/edit_file_sandbox/mock_edit_fixture.py", "operation": "replace", "apply": True},
        result=result,
        evidence_memory=memory,
    )
    valid = verifier.verify_final_answer(
        "已经修改文件 outputs/edit_file_sandbox/mock_edit_fixture.py。[ev_001]",
        memory,
    )
    ok = (
        missing.passed is False
        and any("modified without applied edit_file evidence" in issue for issue in missing.issues)
        and valid.passed is True
    )
    detail = {"missing": missing.to_dict(), "valid": valid.to_dict()}
    return "verifier edit claim", ok, "" if ok else str(detail)


def _check_agent_edit_chain() -> tuple[str, bool, str]:
    _reset_fixture()
    agent = AgentLoop(
        registry=build_registry(),
        llm_client=MockLLMClient(scenario="edit"),
        max_steps=5,
        trajectory_logger=TrajectoryLogger(),
        task_id="p3_edit_file_chain",
    )
    result = agent.run("sandbox edit_file validation")
    text = FIXTURE.read_text(encoding="utf-8")
    evidence_types = {str(item["source_type"]) for item in result.evidence}
    actions = [str(item["action"]) for item in result.history]
    ok = (
        result.verification is not None
        and result.verification.get("passed") is True
        and {"file", "edit", "test_run"}.issubset(evidence_types)
        and any(action.startswith("edit_file(") or action == "edit_file" for action in actions)
        and 'VALUE = "after"' in text
        and "[ev_002]" in result.answer
    )
    detail = {
        "verification": result.verification,
        "evidence_types": sorted(evidence_types),
        "actions": actions,
        "answer": result.answer,
        "fixture": text,
    }
    return "agent edit chain", ok, "" if ok else str(detail)


if __name__ == "__main__":
    raise SystemExit(main())
