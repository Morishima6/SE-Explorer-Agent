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
from tools.run_tests import run_tests


def main() -> int:
    checks = [
        _check_compileall_execution(),
        _check_blocked_command(),
        _check_test_run_evidence(),
        _check_registry(),
        _check_agent_test_chain(),
    ]
    passed = all(item[1] for item in checks)
    for name, ok, detail in checks:
        status = "passed" if ok else "failed"
        print(f"[P3 run_tests] {name}: {status}")
        if detail:
            print(f"      {detail}")
    print(f"[P3 run_tests] overall: {'passed' if passed else 'failed'}")
    return 0 if passed else 1


def _check_compileall_execution() -> tuple[str, bool, str]:
    result = run_tests(
        command="python -m compileall agent tools rag demo scripts eval",
        timeout=60,
        test_type="compileall",
    )
    ok = (
        result.get("success") is True
        and result.get("passed") is True
        and result.get("returncode") == 0
        and result.get("test_type") == "compileall"
        and "stdout_tail" in result
        and "elapsed_ms" in result
    )
    return "compileall execution", ok, "" if ok else str(result)


def _check_blocked_command() -> tuple[str, bool, str]:
    result = run_tests("python -m pip install demo-package", timeout=10, test_type="pytest")
    ok = (
        result.get("success") is False
        and result.get("passed") is False
        and "blocked token" in str(result.get("error", ""))
    )
    return "blocked command", ok, "" if ok else str(result)


def _check_test_run_evidence() -> tuple[str, bool, str]:
    memory = EvidenceMemory()
    result = run_tests("python -m compileall agent", timeout=60, test_type="compileall")
    evidence_ids = extract_evidence_from_tool_result(
        tool_name="run_tests",
        args={"command": "python -m compileall agent", "timeout": 60, "test_type": "compileall"},
        result=result,
        evidence_memory=memory,
    )
    evidence = memory.to_dicts()
    ok = (
        len(evidence_ids) == 1
        and len(evidence) == 1
        and evidence[0]["source_type"] == "test_run"
        and evidence[0]["source"] == "run_tests"
        and evidence[0]["metadata"].get("test_type") == "compileall"
        and evidence[0]["metadata"].get("passed") is True
    )
    return "test_run evidence", ok, "" if ok else str(evidence)


def _check_registry() -> tuple[str, bool, str]:
    names = {tool.name for tool in build_registry().list_tools()}
    ok = "run_tests" in names and "shell_readonly" in names
    return "tool registry", ok, "" if ok else str(sorted(names))


def _check_agent_test_chain() -> tuple[str, bool, str]:
    agent = AgentLoop(
        registry=build_registry(),
        llm_client=MockLLMClient(scenario="test"),
        max_steps=5,
        trajectory_logger=TrajectoryLogger(),
        task_id="p3_run_tests_chain",
    )
    result = agent.run("compileall validation through run_tests evidence")
    evidence_types = {str(item["source_type"]) for item in result.evidence}
    evidence_sources = {str(item["source"]) for item in result.evidence}
    actions = [str(item["action"]) for item in result.history]
    ok = (
        result.verification is not None
        and result.verification.get("passed") is True
        and "test_run" in evidence_types
        and "run_tests" in evidence_sources
        and any(action.startswith("run_tests(") or action == "run_tests" for action in actions)
        and "[ev_003]" in result.answer
    )
    detail = {
        "verification": result.verification,
        "evidence_types": sorted(evidence_types),
        "evidence_sources": sorted(evidence_sources),
        "actions": actions,
        "answer": result.answer,
    }
    return "agent test chain", ok, "" if ok else str(detail)


if __name__ == "__main__":
    raise SystemExit(main())
