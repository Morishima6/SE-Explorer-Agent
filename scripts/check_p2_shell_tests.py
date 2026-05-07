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
from tools.shell_readonly import shell_readonly


def main() -> int:
    checks = [
        _check_compileall_execution(),
        _check_blocked_command(),
        _check_test_run_evidence(),
        _check_agent_test_chain(),
    ]
    passed = all(item[1] for item in checks)
    for name, ok, detail in checks:
        status = "passed" if ok else "failed"
        print(f"[P2 shell tests] {name}: {status}")
        if detail:
            print(f"      {detail}")
    print(f"[P2 shell tests] overall: {'passed' if passed else 'failed'}")
    return 0 if passed else 1


def _check_compileall_execution() -> tuple[str, bool, str]:
    result = shell_readonly("python -m compileall agent tools rag demo scripts eval", timeout=60)
    ok = (
        result.get("success") is True
        and result.get("returncode") == 0
        and result.get("command_type") == "python -m compileall"
        and "stdout_tail" in result
        and "elapsed_ms" in result
    )
    return "compileall execution", ok, "" if ok else str(result)


def _check_blocked_command() -> tuple[str, bool, str]:
    result = shell_readonly("python -m pip install demo-package", timeout=10)
    ok = result.get("success") is False and "blocked token" in str(result.get("error", ""))
    return "blocked command", ok, "" if ok else str(result)


def _check_test_run_evidence() -> tuple[str, bool, str]:
    memory = EvidenceMemory()
    result = shell_readonly("python -m compileall agent", timeout=60)
    evidence_ids = extract_evidence_from_tool_result(
        tool_name="shell_readonly",
        args={"command": "python -m compileall agent", "timeout": 60},
        result=result,
        evidence_memory=memory,
    )
    evidence = memory.to_dicts()
    ok = (
        len(evidence_ids) == 1
        and len(evidence) == 1
        and evidence[0]["source_type"] == "test_run"
        and "python -m compileall agent" in str(evidence[0]["content"])
    )
    return "test_run evidence", ok, "" if ok else str(evidence)


def _check_agent_test_chain() -> tuple[str, bool, str]:
    agent = AgentLoop(
        registry=build_registry(),
        llm_client=MockLLMClient(scenario="test"),
        max_steps=5,
        trajectory_logger=TrajectoryLogger(),
        task_id="p2_shell_test_chain",
    )
    result = agent.run("compileall validation for shell_readonly test_run evidence")
    evidence_types = {str(item["source_type"]) for item in result.evidence}
    actions = [str(item["action"]) for item in result.history]
    ok = (
        result.verification is not None
        and result.verification.get("passed") is True
        and "test_run" in evidence_types
        and any(
            action == "shell_readonly"
            or action == "run_tests"
            or action.startswith("shell_readonly(")
            or action.startswith("run_tests(")
            for action in actions
        )
        and "[ev_003]" in result.answer
    )
    detail = {
        "verification": result.verification,
        "evidence_types": sorted(evidence_types),
        "actions": actions,
        "answer": result.answer,
    }
    return "agent test chain", ok, "" if ok else str(detail)


if __name__ == "__main__":
    raise SystemExit(main())
