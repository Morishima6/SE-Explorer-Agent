import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "p2_difficulty_check"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    checks = [
        _run_calibration(),
        _check_calibration_json(),
        _check_calibration_markdown(),
        _check_baseline_pattern(),
        _check_review_flags(),
    ]

    passed = all(item[1] for item in checks)
    for name, ok, detail in checks:
        status = "passed" if ok else "failed"
        print(f"[P2 difficulty] {name}: {status}")
        if detail:
            print(f"      {detail}")
    print(f"[P2 difficulty] overall: {'passed' if passed else 'failed'}")
    return 0 if passed else 1


def _run_calibration() -> tuple[str, bool, str]:
    command = [
        sys.executable,
        "eval/run_calibration.py",
        "--tasks",
        "eval/tasks.jsonl",
        "--run-id",
        RUN_ID,
    ]
    print(f"[check_p2_difficulty] run calibration: {' '.join(command)}")
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=420,
    )
    output = completed.stdout + completed.stderr
    ok = completed.returncode == 0 and "[calibration] report=" in output
    return "calibration runner", ok, "" if ok else f"returncode={completed.returncode}; output={output[-2000:]}"


def _check_calibration_json() -> tuple[str, bool, str]:
    report = _load_report()
    if not report:
        return "calibration json", False, "report missing or invalid"
    summary = report.get("summary", {})
    calibrations = report.get("calibrations", [])
    declared = summary.get("declared_distribution", {})
    calibrated = summary.get("calibrated_distribution", {})
    ok = (
        summary.get("task_count", 0) >= 20
        and len(calibrations) == summary.get("task_count")
        and isinstance(summary.get("baseline_pass_rates"), dict)
        and {"easy", "medium", "hard"}.issubset(set(declared))
        and {"easy", "medium", "hard"}.issubset(set(calibrated))
    )
    return "calibration json", ok, "" if ok else str(summary)


def _check_calibration_markdown() -> tuple[str, bool, str]:
    path = PROJECT_ROOT / "outputs" / "eval_results" / f"{RUN_ID}_difficulty_calibration.md"
    if not path.exists():
        return "calibration markdown", False, f"missing {path}"
    text = path.read_text(encoding="utf-8", errors="replace")
    required = [
        "# Difficulty Calibration Report",
        "## Baseline Pass Rates",
        "## Difficulty Distribution",
        "## Task-Level Calibration",
    ]
    missing = [item for item in required if item not in text]
    return "calibration markdown", not missing, "" if not missing else f"missing={missing}"


def _check_baseline_pattern() -> tuple[str, bool, str]:
    report = _load_report()
    baselines = {"direct_mock", "rag_only_mock", "agent_mock"}
    bad: list[str] = []
    for item in report.get("calibrations", []):
        pattern = item.get("baseline_pattern", {})
        if set(pattern) != baselines:
            bad.append(f"{item.get('task_id')}: pattern={pattern}")
        if pattern.get("agent_mock") is not True:
            bad.append(f"{item.get('task_id')}: agent_mock did not pass")
    return "baseline pattern", not bad, "; ".join(bad)


def _check_review_flags() -> tuple[str, bool, str]:
    report = _load_report()
    calibrations = report.get("calibrations", [])
    bad: list[str] = []
    for item in calibrations:
        if "needs_review" not in item or "review_reasons" not in item:
            bad.append(f"{item.get('task_id')}: missing review fields")
        declared = item.get("declared_difficulty")
        calibrated = item.get("calibrated_difficulty")
        if declared != calibrated and item.get("needs_review") is not True:
            bad.append(f"{item.get('task_id')}: mismatch without needs_review")
    review_count = sum(1 for item in calibrations if item.get("needs_review") is True)
    summary_count = report.get("summary", {}).get("review_needed_count")
    if review_count != summary_count:
        bad.append(f"review_count={review_count}, summary_count={summary_count}")
    return "review flags", not bad, "; ".join(bad)


def _load_report() -> dict[str, object]:
    path = PROJECT_ROOT / "outputs" / "eval_results" / f"{RUN_ID}_difficulty_calibration.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
