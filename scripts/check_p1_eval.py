import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "p1_eval_check"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks: list[tuple[str, bool, str]] = []
    checks.append(_run_eval())
    checks.append(_check_results_file())
    checks.append(_check_summary())
    checks.append(_check_result_metrics())

    passed = all(item[1] for item in checks)
    for name, ok, detail in checks:
        status = "passed" if ok else "failed"
        print(f"[P1 eval] {name}: {status}")
        if detail:
            print(f"      {detail}")
    print(f"[P1 eval] overall: {'passed' if passed else 'failed'}")
    return 0 if passed else 1


def _run_eval() -> tuple[str, bool, str]:
    command = [
        sys.executable,
        "eval/run_eval.py",
        "--tasks",
        "eval/tasks.jsonl",
        "--mode",
        "agent_mock",
        "--run-id",
        RUN_ID,
    ]
    print(f"[check_p1_eval] run eval: {' '.join(command)}")
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
    ok = completed.returncode == 0 and "[eval] overall_passed=True" in output
    detail = "" if ok else f"returncode={completed.returncode}; output={output[-1200:]}"
    return "eval runner", ok, detail


def _check_results_file() -> tuple[str, bool, str]:
    records = _read_results()
    scenarios = {item.get("mock_scenario") for item in records}
    task_types = {item.get("type") for item in records}
    ok = (
        len(records) >= 20
        and {"docs", "code", "fix"}.issubset(scenarios)
        and {"DocsQA", "Where", "RepoQA", "How", "VerifierQA", "FixSuggestion"}.issubset(task_types)
    )
    detail = (
        ""
        if ok
        else f"records={len(records)}, scenarios={sorted(str(item) for item in scenarios)}, types={sorted(str(item) for item in task_types)}"
    )
    return "results file", ok, detail


def _check_summary() -> tuple[str, bool, str]:
    path = PROJECT_ROOT / "outputs" / "eval_results" / f"{RUN_ID}_summary.json"
    if not path.exists():
        return "summary", False, f"missing {path}"
    summary = json.loads(path.read_text(encoding="utf-8"))
    records = _read_results()
    grouped_keys = ["by_type", "by_scenario", "by_difficulty"]
    ok = (
        summary.get("overall_passed") is True
        and summary.get("task_count", 0) >= 20
        and summary.get("task_count") == len(records)
        and summary.get("passed_count") == summary.get("task_count")
        and all(isinstance(summary.get(key), dict) and summary.get(key) for key in grouped_keys)
        and {"docs", "code", "fix"}.issubset(set(summary.get("by_scenario", {})))
        and {"easy", "medium", "hard"}.issubset(set(summary.get("by_difficulty", {})))
    )
    return "summary", ok, "" if ok else str(summary)


def _check_result_metrics() -> tuple[str, bool, str]:
    records = _read_results()
    required_metric_keys = {
        "final_verifier_passed",
        "expected_tools_covered",
        "required_evidence_types_covered",
        "used_evidence_count",
        "expected_evidence_count",
        "expected_evidence_count_met",
        "trajectory_steps",
        "latency_ms",
    }
    bad: list[str] = []
    for item in records:
        metrics = item.get("metrics", {})
        missing = sorted(required_metric_keys - set(metrics))
        if missing or item.get("passed") is not True or metrics.get("expected_evidence_count_met") is not True:
            bad.append(
                f"{item.get('task_id')}: missing={missing}, passed={item.get('passed')}, "
                f"expected_evidence_count_met={metrics.get('expected_evidence_count_met')}"
            )
    return "result metrics", not bad, "; ".join(bad)


def _read_results() -> list[dict[str, object]]:
    path = PROJECT_ROOT / "outputs" / "eval_results" / f"{RUN_ID}.jsonl"
    if not path.exists():
        return []
    records: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


if __name__ == "__main__":
    raise SystemExit(main())
