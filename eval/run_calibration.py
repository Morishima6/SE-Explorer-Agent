import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASELINES = ["direct_mock", "rag_only_mock", "agent_mock"]
DIFFICULTIES = ["easy", "medium", "hard"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run difficulty calibration for SE-Explorer benchmark tasks")
    parser.add_argument("--tasks", default="eval/tasks.jsonl")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    run_id = args.run_id or datetime.now().strftime("calibration_%Y%m%d_%H%M%S")
    tasks = _load_tasks(PROJECT_ROOT / args.tasks, limit=args.limit)
    if not tasks:
        print("[calibration] no tasks loaded")
        return 1

    comparison = _run_compare(tasks=args.tasks, run_id=run_id, limit=args.limit)
    baseline_results = _load_baseline_results(run_id)
    calibrations = [_calibrate_task(task, baseline_results) for task in tasks]
    summary = _build_summary(run_id, comparison, calibrations)

    output_dir = PROJECT_ROOT / "outputs" / "eval_results"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"{run_id}_difficulty_calibration.json"
    markdown_path = output_dir / f"{run_id}_difficulty_calibration.md"
    report = {
        "run_id": run_id,
        "tasks_path": args.tasks,
        "summary": summary,
        "calibrations": calibrations,
        "comparison_path": comparison.get("comparison_path"),
        "markdown_path": str(markdown_path.relative_to(PROJECT_ROOT)),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_format_markdown(report), encoding="utf-8")

    print(f"[calibration] report={report_path}")
    print(f"[calibration] markdown={markdown_path}")
    print(f"[calibration] review_needed={summary['review_needed_count']}")
    return 0


def _load_tasks(path: Path, limit: int | None) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        task = json.loads(line)
        if str(task.get("mode", "agent_mock")) == "agent_mock":
            tasks.append(task)
    if limit is not None:
        tasks = tasks[:limit]
    print(f"[calibration] loaded tasks={len(tasks)}")
    return tasks


def _run_compare(tasks: str, run_id: str, limit: int | None) -> dict[str, Any]:
    command = [
        sys.executable,
        "eval/run_compare.py",
        "--tasks",
        tasks,
        "--run-id",
        run_id,
    ]
    if limit is not None:
        command.extend(["--limit", str(limit)])

    print(f"[calibration] run compare: {' '.join(command)}")
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
    if output.strip():
        print(output[-2400:])
    if completed.returncode != 0:
        raise RuntimeError(f"compare failed returncode={completed.returncode}; output={output[-2400:]}")

    comparison_path = PROJECT_ROOT / "outputs" / "eval_results" / f"{run_id}_comparison.json"
    if not comparison_path.exists():
        raise RuntimeError(f"missing comparison json: {comparison_path}")
    return json.loads(comparison_path.read_text(encoding="utf-8"))


def _load_baseline_results(run_id: str) -> dict[str, dict[str, dict[str, Any]]]:
    baseline_results: dict[str, dict[str, dict[str, Any]]] = {}
    for baseline in BASELINES:
        path = PROJECT_ROOT / "outputs" / "eval_results" / f"{run_id}_{baseline}.jsonl"
        rows: dict[str, dict[str, Any]] = {}
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip():
                row = json.loads(line)
                rows[str(row.get("task_id"))] = row
        baseline_results[baseline] = rows
        print(f"[calibration] loaded baseline={baseline}, rows={len(rows)}")
    return baseline_results


def _calibrate_task(
    task: dict[str, Any],
    baseline_results: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    task_id = str(task["task_id"])
    declared = str(task.get("difficulty") or "unknown")
    expected_tools = [str(item) for item in task.get("expected_tools", [])]
    evidence_types = [str(item) for item in task.get("required_evidence_types", [])]
    expected_evidence_count = int(task.get("expected_evidence_count") or 1)
    baseline_pattern = {
        baseline: baseline_results.get(baseline, {}).get(task_id, {}).get("passed") is True
        for baseline in BASELINES
    }
    score_breakdown = _score_breakdown(
        expected_tools=expected_tools,
        evidence_types=evidence_types,
        expected_evidence_count=expected_evidence_count,
        baseline_pattern=baseline_pattern,
    )
    score = sum(score_breakdown.values())
    calibrated = _difficulty_from_score(score)
    capabilities = _infer_required_capabilities(expected_tools, evidence_types)
    reasons = _build_reasons(
        score=score,
        score_breakdown=score_breakdown,
        baseline_pattern=baseline_pattern,
        expected_tools=expected_tools,
        evidence_types=evidence_types,
        expected_evidence_count=expected_evidence_count,
    )
    review_reasons = _review_reasons(declared, calibrated, score, baseline_pattern)

    return {
        "task_id": task_id,
        "type": task.get("type"),
        "category": task.get("category"),
        "declared_difficulty": declared,
        "calibrated_difficulty": calibrated,
        "difficulty_score": score,
        "score_breakdown": score_breakdown,
        "baseline_pattern": baseline_pattern,
        "required_capabilities": capabilities,
        "calibration_reasons": reasons,
        "needs_review": bool(review_reasons),
        "review_reasons": review_reasons,
    }


def _score_breakdown(
    expected_tools: list[str],
    evidence_types: list[str],
    expected_evidence_count: int,
    baseline_pattern: dict[str, bool],
) -> dict[str, int]:
    complex_evidence = {"patch", "test", "test_run", "table", "figure"}
    return {
        "tool_chain": int(len(expected_tools) >= 3) + int(len(expected_tools) >= 5),
        "evidence_volume": int(expected_evidence_count >= 2) + int(expected_evidence_count >= 4),
        "evidence_diversity": int(len(set(evidence_types)) >= 2),
        "complex_evidence": int(bool(complex_evidence & set(evidence_types))),
        "baseline_gap": int(
            baseline_pattern.get("agent_mock") is True
            and baseline_pattern.get("direct_mock") is False
            and baseline_pattern.get("rag_only_mock") is False
        ),
    }


def _difficulty_from_score(score: int) -> str:
    if score <= 2:
        return "easy"
    if score <= 5:
        return "medium"
    return "hard"


def _infer_required_capabilities(expected_tools: list[str], evidence_types: list[str]) -> list[str]:
    capabilities: list[str] = []
    tool_set = set(expected_tools)
    evidence_set = set(evidence_types)
    if "search_docs" in tool_set or "doc" in evidence_set:
        capabilities.append("document_retrieval")
    if {"search_code", "grep_code", "view_file", "list_repo_tree"} & tool_set or {"code", "file"} & evidence_set:
        capabilities.append("repo_navigation")
    if "generate_patch" in tool_set or "patch" in evidence_set:
        capabilities.append("patch_suggestion")
    if {"suggest_tests", "shell_readonly"} & tool_set or {"test", "test_run"} & evidence_set:
        capabilities.append("test_validation")
    if {"search_tables", "search_figures"} & tool_set or {"table", "figure"} & evidence_set:
        capabilities.append("multimodal_retrieval")
    if "final_answer" in tool_set:
        capabilities.append("evidence_citation")
    return capabilities


def _build_reasons(
    score: int,
    score_breakdown: dict[str, int],
    baseline_pattern: dict[str, bool],
    expected_tools: list[str],
    evidence_types: list[str],
    expected_evidence_count: int,
) -> list[str]:
    reasons = [
        f"difficulty score={score}",
        f"requires {len(expected_tools)} expected tools",
        f"requires {expected_evidence_count} final-used evidence item(s)",
        f"requires evidence types: {', '.join(evidence_types)}",
    ]
    for key, value in score_breakdown.items():
        if value:
            reasons.append(f"{key} contributes {value}")
    failed_baselines = [name for name, passed in baseline_pattern.items() if not passed]
    passed_baselines = [name for name, passed in baseline_pattern.items() if passed]
    reasons.append(f"passed baselines: {', '.join(passed_baselines) or 'none'}")
    reasons.append(f"failed baselines: {', '.join(failed_baselines) or 'none'}")
    return reasons


def _review_reasons(
    declared: str,
    calibrated: str,
    score: int,
    baseline_pattern: dict[str, bool],
) -> list[str]:
    reasons: list[str] = []
    if declared != calibrated:
        reasons.append(f"declared difficulty {declared} differs from calibrated {calibrated}")
    if declared == "easy" and score >= 4:
        reasons.append("declared easy but has medium-or-higher tool/evidence complexity")
    if declared == "hard" and baseline_pattern.get("rag_only_mock") is True:
        reasons.append("declared hard but rag_only_mock passed")
    if baseline_pattern.get("agent_mock") is not True:
        reasons.append("agent_mock did not pass; inspect task or implementation before using this task")
    return reasons


def _build_summary(
    run_id: str,
    comparison: dict[str, Any],
    calibrations: list[dict[str, Any]],
) -> dict[str, Any]:
    review_needed_count = sum(1 for item in calibrations if item.get("needs_review") is True)
    match_count = sum(
        1 for item in calibrations if item.get("declared_difficulty") == item.get("calibrated_difficulty")
    )
    return {
        "run_id": run_id,
        "task_count": len(calibrations),
        "review_needed_count": review_needed_count,
        "difficulty_match_count": match_count,
        "difficulty_match_rate": match_count / len(calibrations) if calibrations else 0,
        "declared_distribution": _distribution(calibrations, "declared_difficulty"),
        "calibrated_distribution": _distribution(calibrations, "calibrated_difficulty"),
        "baseline_pass_rates": _baseline_pass_rates(comparison),
        "by_declared_difficulty": _group_calibration_summary(calibrations, "declared_difficulty"),
        "by_calibrated_difficulty": _group_calibration_summary(calibrations, "calibrated_difficulty"),
    }


def _distribution(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    values = {difficulty: 0 for difficulty in DIFFICULTIES}
    for row in rows:
        value = str(row.get(key) or "unknown")
        values[value] = values.get(value, 0) + 1
    return values


def _baseline_pass_rates(comparison: dict[str, Any]) -> dict[str, float]:
    baselines = comparison.get("baselines", {})
    return {
        baseline: float(baselines.get(baseline, {}).get("pass_rate", 0))
        for baseline in BASELINES
    }


def _group_calibration_summary(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row.get(key) or "unknown"), []).append(row)
    result: dict[str, dict[str, Any]] = {}
    for value, items in sorted(groups.items()):
        review_count = sum(1 for item in items if item.get("needs_review") is True)
        avg_score = sum(int(item.get("difficulty_score", 0)) for item in items) / len(items)
        result[value] = {
            "task_count": len(items),
            "review_needed_count": review_count,
            "avg_difficulty_score": avg_score,
        }
    return result


def _format_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Difficulty Calibration Report",
        "",
        f"Run ID: `{report['run_id']}`",
        "",
        "## Overall",
        "",
        f"- Task count: {summary['task_count']}",
        f"- Difficulty match rate: {float(summary['difficulty_match_rate']):.2f}",
        f"- Review needed: {summary['review_needed_count']}",
        "",
        "## Baseline Pass Rates",
        "",
        "| Baseline | Pass Rate |",
        "|---|---:|",
    ]
    for baseline, rate in summary["baseline_pass_rates"].items():
        lines.append(f"| {baseline} | {float(rate):.2f} |")

    lines.extend(
        [
            "",
            "## Difficulty Distribution",
            "",
            "| Difficulty | Declared | Calibrated |",
            "|---|---:|---:|",
        ]
    )
    for difficulty in DIFFICULTIES:
        declared = summary["declared_distribution"].get(difficulty, 0)
        calibrated = summary["calibrated_distribution"].get(difficulty, 0)
        lines.append(f"| {difficulty} | {declared} | {calibrated} |")

    lines.extend(
        [
            "",
            "## Task-Level Calibration",
            "",
            "| Task ID | Declared | Calibrated | Score | Baseline Pattern | Review |",
            "|---|---|---|---:|---|---|",
        ]
    )
    for item in report["calibrations"]:
        pattern = ", ".join(
            f"{baseline}={'pass' if item['baseline_pattern'][baseline] else 'fail'}"
            for baseline in BASELINES
        )
        review = "; ".join(item["review_reasons"]) if item["needs_review"] else ""
        lines.append(
            f"| {item['task_id']} | {item['declared_difficulty']} | {item['calibrated_difficulty']} | "
            f"{item['difficulty_score']} | {pattern} | {review} |"
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
