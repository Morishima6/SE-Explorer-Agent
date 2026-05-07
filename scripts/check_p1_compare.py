import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "p1_compare_check"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks: list[tuple[str, bool, str]] = []
    checks.append(_run_compare())
    checks.append(_check_comparison_json())
    checks.append(_check_agent_advantage())
    checks.append(_check_markdown_table())

    passed = all(item[1] for item in checks)
    for name, ok, detail in checks:
        status = "passed" if ok else "failed"
        print(f"[P1 compare] {name}: {status}")
        if detail:
            print(f"      {detail}")
    print(f"[P1 compare] overall: {'passed' if passed else 'failed'}")
    return 0 if passed else 1


def _run_compare() -> tuple[str, bool, str]:
    command = [
        sys.executable,
        "eval/run_compare.py",
        "--tasks",
        "eval/tasks.jsonl",
        "--run-id",
        RUN_ID,
    ]
    print(f"[check_p1_compare] run compare: {' '.join(command)}")
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=360,
    )
    output = completed.stdout + completed.stderr
    ok = completed.returncode == 0 and "[compare] agent_advantage=True" in output
    return "compare runner", ok, "" if ok else f"returncode={completed.returncode}; output={output[-2000:]}"


def _check_comparison_json() -> tuple[str, bool, str]:
    comparison = _read_comparison()
    baselines = comparison.get("baselines", {})
    required = {"direct_mock", "rag_only_mock", "agent_mock"}
    ok = (
        comparison.get("run_id") == RUN_ID
        and comparison.get("agent_advantage") is True
        and required.issubset(set(baselines))
        and all(int(baselines[item].get("task_count", 0)) >= 20 for item in required)
    )
    return "comparison json", ok, "" if ok else str(comparison)


def _check_agent_advantage() -> tuple[str, bool, str]:
    baselines = _read_comparison().get("baselines", {})
    agent = baselines.get("agent_mock", {})
    rag = baselines.get("rag_only_mock", {})
    direct = baselines.get("direct_mock", {})
    agent_rate = float(agent.get("pass_rate", 0))
    rag_rate = float(rag.get("pass_rate", 0))
    direct_rate = float(direct.get("pass_rate", 0))
    ok = (
        agent_rate >= rag_rate
        and agent_rate >= direct_rate
        and int(agent.get("passed_count", 0)) == int(agent.get("task_count", -1))
    )
    detail = "" if ok else f"agent={agent_rate}, rag={rag_rate}, direct={direct_rate}, agent={agent}"
    return "agent advantage", ok, detail


def _check_markdown_table() -> tuple[str, bool, str]:
    path = PROJECT_ROOT / "outputs" / "eval_results" / f"{RUN_ID}_comparison.md"
    if not path.exists():
        return "comparison markdown", False, f"missing {path}"
    text = path.read_text(encoding="utf-8", errors="replace")
    required = ["| Baseline | Tasks | Passed | Pass Rate |", "Direct Mock", "RAG-only Mock", "SE-Explorer Agent Mock"]
    missing = [item for item in required if item not in text]
    return "comparison markdown", not missing, "" if not missing else f"missing={missing}"


def _read_comparison() -> dict[str, object]:
    path = PROJECT_ROOT / "outputs" / "eval_results" / f"{RUN_ID}_comparison.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
