import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCORE_FIELDS = [
    "answer_correctness",
    "evidence_relevance",
    "citation_sufficiency",
    "trajectory_interpretability",
    "difficulty_label_quality",
]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate human scoring for SE-Explorer benchmark tasks")
    parser.add_argument("--tasks", default="eval/tasks.jsonl")
    parser.add_argument("--scores", default="eval/human_scores.example.jsonl")
    parser.add_argument("--eval-results", default="outputs/eval_results/p2_human_scoring_check_agent_mock.jsonl")
    parser.add_argument("--calibration", default="outputs/eval_results/p2_human_scoring_check_difficulty_calibration.json")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    run_id = args.run_id or datetime.now().strftime("human_scoring_%Y%m%d_%H%M%S")
    tasks = _load_tasks(PROJECT_ROOT / args.tasks)
    scores = _load_scores(PROJECT_ROOT / args.scores, tasks)
    eval_results = _load_jsonl(PROJECT_ROOT / args.eval_results)
    calibrations = _load_calibrations(PROJECT_ROOT / args.calibration)
    records = [_build_record(score, tasks, eval_results, calibrations) for score in scores]
    summary = _build_summary(run_id, tasks, records)

    output_dir = PROJECT_ROOT / "outputs" / "eval_results"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"{run_id}_human_scoring.json"
    markdown_path = output_dir / f"{run_id}_human_scoring.md"
    report = {
        "run_id": run_id,
        "tasks_path": args.tasks,
        "scores_path": args.scores,
        "eval_results_path": args.eval_results,
        "calibration_path": args.calibration,
        "summary": summary,
        "records": records,
        "markdown_path": str(markdown_path.relative_to(PROJECT_ROOT)),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_format_markdown(report), encoding="utf-8")

    print(f"[human_scoring] report={report_path}")
    print(f"[human_scoring] markdown={markdown_path}")
    print(f"[human_scoring] scored_tasks={summary['scored_task_count']}")
    print(f"[human_scoring] needs_revision={summary['needs_revision_count']}")
    return 0


def _load_tasks(path: Path) -> dict[str, dict[str, Any]]:
    tasks: dict[str, dict[str, Any]] = {}
    for row in _load_jsonl(path):
        if str(row.get("mode", "agent_mock")) == "agent_mock":
            tasks[str(row["task_id"])] = row
    print(f"[human_scoring] loaded tasks={len(tasks)}")
    return tasks


def _load_scores(path: Path, tasks: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = _load_jsonl(path)
    seen: set[str] = set()
    errors: list[str] = []
    for row in rows:
        task_id = str(row.get("task_id", ""))
        if task_id not in tasks:
            errors.append(f"unknown task_id={task_id}")
        if task_id in seen:
            errors.append(f"duplicate task_id={task_id}")
        seen.add(task_id)
        for field in SCORE_FIELDS:
            value = row.get(field)
            if not isinstance(value, int) or not 1 <= value <= 5:
                errors.append(f"{task_id}: {field} must be integer 1..5")
        if not isinstance(row.get("needs_revision"), bool):
            errors.append(f"{task_id}: needs_revision must be boolean")
    if errors:
        raise ValueError("; ".join(errors))
    print(f"[human_scoring] loaded scores={len(rows)}")
    return rows


def _load_calibrations(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        print(f"[human_scoring] calibration missing: {path}")
        return {}
    report = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(item.get("task_id")): item
        for item in report.get("calibrations", [])
        if item.get("task_id")
    }


def _build_record(
    score: dict[str, Any],
    tasks: dict[str, dict[str, Any]],
    eval_results: list[dict[str, Any]],
    calibrations: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    task_id = str(score["task_id"])
    eval_by_id = {str(item.get("task_id")): item for item in eval_results}
    task = tasks[task_id]
    eval_row = eval_by_id.get(task_id, {})
    calibration = calibrations.get(task_id, {})
    average_score = sum(int(score[field]) for field in SCORE_FIELDS) / len(SCORE_FIELDS)
    low_fields = [field for field in SCORE_FIELDS if int(score[field]) <= 3]
    calibration_conflict = _calibration_conflict(score, calibration)
    return {
        "task_id": task_id,
        "type": task.get("type"),
        "category": task.get("category"),
        "declared_difficulty": task.get("difficulty"),
        "calibrated_difficulty": calibration.get("calibrated_difficulty"),
        "agent_passed": eval_row.get("passed"),
        "human_scores": {field: score[field] for field in SCORE_FIELDS},
        "average_score": round(average_score, 2),
        "needs_revision": score["needs_revision"],
        "review_notes": score.get("review_notes", ""),
        "low_score_fields": low_fields,
        "calibration_needs_review": calibration.get("needs_review"),
        "calibration_conflict": calibration_conflict,
    }


def _calibration_conflict(score: dict[str, Any], calibration: dict[str, Any]) -> bool:
    if not calibration:
        return False
    label_quality = int(score["difficulty_label_quality"])
    if calibration.get("needs_review") is True and label_quality >= 4:
        return True
    if calibration.get("needs_review") is not True and label_quality <= 2:
        return True
    return False


def _build_summary(
    run_id: str,
    tasks: dict[str, dict[str, Any]],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    average_scores = {
        field: round(sum(int(record["human_scores"][field]) for record in records) / len(records), 2)
        for field in SCORE_FIELDS
    }
    needs_revision = [record for record in records if record["needs_revision"] is True]
    low_score_tasks = [record for record in records if record["low_score_fields"]]
    calibration_conflicts = [record for record in records if record["calibration_conflict"] is True]
    return {
        "run_id": run_id,
        "total_task_count": len(tasks),
        "scored_task_count": len(records),
        "coverage_rate": len(records) / len(tasks) if tasks else 0,
        "average_scores": average_scores,
        "overall_average_score": round(
            sum(record["average_score"] for record in records) / len(records),
            2,
        ),
        "needs_revision_count": len(needs_revision),
        "needs_revision_task_ids": [str(record["task_id"]) for record in needs_revision],
        "low_score_task_count": len(low_score_tasks),
        "low_score_task_ids": [str(record["task_id"]) for record in low_score_tasks],
        "calibration_conflict_count": len(calibration_conflicts),
        "calibration_conflict_task_ids": [str(record["task_id"]) for record in calibration_conflicts],
        "by_category": _group_records(records, "category"),
    }


def _group_records(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        groups.setdefault(str(record.get(key) or "unknown"), []).append(record)
    summary: dict[str, dict[str, Any]] = {}
    for value, rows in sorted(groups.items()):
        summary[value] = {
            "task_count": len(rows),
            "avg_human_score": round(sum(float(row["average_score"]) for row in rows) / len(rows), 2),
            "needs_revision_count": sum(1 for row in rows if row["needs_revision"] is True),
        }
    return summary


def _format_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Human Scoring Report",
        "",
        f"Run ID: `{report['run_id']}`",
        "",
        "## Summary",
        "",
        f"- Scored tasks: {summary['scored_task_count']} / {summary['total_task_count']}",
        f"- Coverage rate: {float(summary['coverage_rate']):.2f}",
        f"- Overall average score: {float(summary['overall_average_score']):.2f}",
        f"- Needs revision: {summary['needs_revision_count']}",
        f"- Calibration conflicts: {summary['calibration_conflict_count']}",
        "",
        "## Average Scores",
        "",
        "| Dimension | Average |",
        "|---|---:|",
    ]
    for field, value in summary["average_scores"].items():
        lines.append(f"| {field} | {float(value):.2f} |")
    lines.extend(["", "## Category Summary", "", "| Category | Tasks | Avg Human Score | Needs Revision |", "|---|---:|---:|---:|"])
    for category, item in summary["by_category"].items():
        lines.append(
            f"| {category} | {item['task_count']} | {float(item['avg_human_score']):.2f} | {item['needs_revision_count']} |"
        )
    lines.extend(["", "## Task-Level Scores", "", "| Task | Category | Avg | Revision | Calibration Conflict | Notes |", "|---|---|---:|---|---|---|"])
    for record in report["records"]:
        notes = str(record.get("review_notes", "")).replace("|", "/")
        lines.append(
            f"| {record['task_id']} | {record.get('category')} | {float(record['average_score']):.2f} | "
            f"{record['needs_revision']} | {record['calibration_conflict']} | {notes} |"
        )
    lines.append("")
    return "\n".join(lines)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
