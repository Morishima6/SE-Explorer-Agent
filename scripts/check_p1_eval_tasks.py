import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TASKS_PATH = PROJECT_ROOT / "eval" / "tasks.jsonl"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    tasks = _load_tasks()
    checks = [
        _check_task_count(tasks),
        _check_unique_task_ids(tasks),
        _check_required_fields(tasks),
        _check_metadata(tasks),
        _check_coverage(tasks),
    ]

    passed = all(item[1] for item in checks)
    for name, ok, detail in checks:
        status = "passed" if ok else "failed"
        print(f"[P1 eval tasks] {name}: {status}")
        if detail:
            print(f"      {detail}")
    print(f"[P1 eval tasks] overall: {'passed' if passed else 'failed'}")
    return 0 if passed else 1


def _load_tasks() -> list[dict[str, object]]:
    tasks: list[dict[str, object]] = []
    for line in TASKS_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            tasks.append(json.loads(line))
    print(f"[check_p1_eval_tasks] loaded tasks={len(tasks)}")
    return tasks


def _check_task_count(tasks: list[dict[str, object]]) -> tuple[str, bool, str]:
    ok = 20 <= len(tasks) <= 30
    return "task count", ok, "" if ok else f"expected 20-30 tasks, got {len(tasks)}"


def _check_unique_task_ids(tasks: list[dict[str, object]]) -> tuple[str, bool, str]:
    ids = [str(item.get("task_id", "")) for item in tasks]
    duplicates = sorted({task_id for task_id in ids if ids.count(task_id) > 1})
    missing = [index + 1 for index, task_id in enumerate(ids) if not task_id]
    ok = not duplicates and not missing
    detail = ""
    if not ok:
        detail = f"duplicates={duplicates}, missing_lines={missing}"
    return "unique task_id", ok, detail


def _check_required_fields(tasks: list[dict[str, object]]) -> tuple[str, bool, str]:
    required = {
        "task_id",
        "type",
        "mode",
        "mock_scenario",
        "query",
        "max_steps",
        "expected_tools",
        "required_evidence_types",
        "expected_answer_points",
    }
    bad: list[str] = []
    for item in tasks:
        missing = sorted(required - set(item))
        if missing:
            bad.append(f"{item.get('task_id')}: missing={missing}")
        if item.get("mode") != "agent_mock":
            bad.append(f"{item.get('task_id')}: mode={item.get('mode')}")
        if not isinstance(item.get("expected_tools"), list) or not item.get("expected_tools"):
            bad.append(f"{item.get('task_id')}: expected_tools must be non-empty")
        if not isinstance(item.get("required_evidence_types"), list) or not item.get("required_evidence_types"):
            bad.append(f"{item.get('task_id')}: required_evidence_types must be non-empty")
    return "required fields", not bad, "; ".join(bad)


def _check_metadata(tasks: list[dict[str, object]]) -> tuple[str, bool, str]:
    difficulties = {"easy", "medium", "hard"}
    categories = {"docs", "repo", "workflow", "fix", "verifier"}
    bad: list[str] = []
    for item in tasks:
        if item.get("difficulty") not in difficulties:
            bad.append(f"{item.get('task_id')}: difficulty={item.get('difficulty')}")
        if item.get("category") not in categories:
            bad.append(f"{item.get('task_id')}: category={item.get('category')}")
        if not isinstance(item.get("tags"), list) or not item.get("tags"):
            bad.append(f"{item.get('task_id')}: tags must be non-empty")
        expected_count = item.get("expected_evidence_count")
        if not isinstance(expected_count, int) or expected_count < 1:
            bad.append(f"{item.get('task_id')}: expected_evidence_count={expected_count}")
    return "metadata fields", not bad, "; ".join(bad)


def _check_coverage(tasks: list[dict[str, object]]) -> tuple[str, bool, str]:
    scenarios = {str(item.get("mock_scenario")) for item in tasks}
    task_types = {str(item.get("type")) for item in tasks}
    difficulties = {str(item.get("difficulty")) for item in tasks}
    categories = {str(item.get("category")) for item in tasks}

    required_scenarios = {"docs", "code", "fix"}
    required_types = {"DocsQA", "Where", "RepoQA", "How", "VerifierQA", "FixSuggestion"}
    required_difficulties = {"easy", "medium", "hard"}
    required_categories = {"docs", "repo", "workflow", "fix", "verifier"}

    missing = {
        "scenarios": sorted(required_scenarios - scenarios),
        "types": sorted(required_types - task_types),
        "difficulties": sorted(required_difficulties - difficulties),
        "categories": sorted(required_categories - categories),
    }
    ok = all(not values for values in missing.values())
    return "coverage", ok, "" if ok else str(missing)


if __name__ == "__main__":
    raise SystemExit(main())
