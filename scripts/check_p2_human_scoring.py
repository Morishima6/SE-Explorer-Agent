import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "p2_human_scoring_check"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    checks = [
        _run_calibration(),
        _run_human_scoring(),
        _check_human_scoring_json(),
        _check_human_scoring_markdown(),
        _check_score_validation(),
        _check_revision_and_conflict_flags(),
    ]

    passed = all(item[1] for item in checks)
    for name, ok, detail in checks:
        status = "passed" if ok else "failed"
        print(f"[P2 human scoring] {name}: {status}")
        if detail:
            print(f"      {detail}")
    print(f"[P2 human scoring] overall: {'passed' if passed else 'failed'}")
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
    print(f"[check_p2_human_scoring] run calibration: {' '.join(command)}")
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
    return "calibration prerequisite", ok, "" if ok else f"returncode={completed.returncode}; output={output[-2000:]}"


def _run_human_scoring() -> tuple[str, bool, str]:
    command = [
        sys.executable,
        "eval/run_human_scoring.py",
        "--tasks",
        "eval/tasks.jsonl",
        "--scores",
        "eval/human_scores.example.jsonl",
        "--eval-results",
        f"outputs/eval_results/{RUN_ID}_agent_mock.jsonl",
        "--calibration",
        f"outputs/eval_results/{RUN_ID}_difficulty_calibration.json",
        "--run-id",
        RUN_ID,
    ]
    print(f"[check_p2_human_scoring] run human scoring: {' '.join(command)}")
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    output = completed.stdout + completed.stderr
    ok = completed.returncode == 0 and "[human_scoring] report=" in output
    return "human scoring runner", ok, "" if ok else f"returncode={completed.returncode}; output={output[-2000:]}"


def _check_human_scoring_json() -> tuple[str, bool, str]:
    report = _load_report()
    summary = report.get("summary", {})
    records = report.get("records", [])
    ok = (
        summary.get("total_task_count", 0) >= 20
        and summary.get("scored_task_count") == summary.get("total_task_count")
        and len(records) == summary.get("scored_task_count")
        and float(summary.get("coverage_rate", 0)) == 1.0
        and "average_scores" in summary
        and "by_category" in summary
    )
    return "human scoring json", ok, "" if ok else str(summary)


def _check_human_scoring_markdown() -> tuple[str, bool, str]:
    path = PROJECT_ROOT / "outputs" / "eval_results" / f"{RUN_ID}_human_scoring.md"
    if not path.exists():
        return "human scoring markdown", False, f"missing {path}"
    text = path.read_text(encoding="utf-8", errors="replace")
    required = [
        "# Human Scoring Report",
        "## Summary",
        "## Average Scores",
        "## Category Summary",
        "## Task-Level Scores",
    ]
    missing = [item for item in required if item not in text]
    return "human scoring markdown", not missing, "" if not missing else f"missing={missing}"


def _check_score_validation() -> tuple[str, bool, str]:
    report = _load_report()
    bad: list[str] = []
    for record in report.get("records", []):
        scores = record.get("human_scores", {})
        for field, value in scores.items():
            if not isinstance(value, int) or not 1 <= value <= 5:
                bad.append(f"{record.get('task_id')}: {field}={value}")
        if not record.get("review_notes"):
            bad.append(f"{record.get('task_id')}: missing review_notes")
    return "score validation", not bad, "; ".join(bad)


def _check_revision_and_conflict_flags() -> tuple[str, bool, str]:
    report = _load_report()
    summary = report.get("summary", {})
    records = report.get("records", [])
    revision_count = sum(1 for record in records if record.get("needs_revision") is True)
    conflict_count = sum(1 for record in records if record.get("calibration_conflict") is True)
    bad: list[str] = []
    if revision_count != summary.get("needs_revision_count"):
        bad.append(f"revision_count={revision_count}, summary={summary.get('needs_revision_count')}")
    if conflict_count != summary.get("calibration_conflict_count"):
        bad.append(f"conflict_count={conflict_count}, summary={summary.get('calibration_conflict_count')}")
    if revision_count < 1:
        bad.append("expected at least one needs_revision example")
    if conflict_count < 1:
        bad.append("expected at least one calibration conflict example")
    return "revision and conflict flags", not bad, "; ".join(bad)


def _load_report() -> dict[str, object]:
    path = PROJECT_ROOT / "outputs" / "eval_results" / f"{RUN_ID}_human_scoring.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
