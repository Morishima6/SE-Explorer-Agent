import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from agent.llm_client import MockLLMClient
from agent.loop import AgentLoop
from agent.evidence_memory import EvidenceMemory
from agent.trajectory import TrajectoryLogger, TrajectoryStep
from agent.verifier import Verifier, extract_evidence_refs
from demo.app import build_registry

MOCK_BASELINE_MODES = {"agent_mock", "direct_mock", "rag_only_mock"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run SE-Explorer Agent evaluation tasks")
    parser.add_argument("--tasks", default="eval/tasks.jsonl")
    parser.add_argument("--mode", default="agent_mock")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    run_id = args.run_id or datetime.now().strftime("eval_%Y%m%d_%H%M%S")
    tasks = _load_tasks(PROJECT_ROOT / args.tasks, mode=args.mode)
    if args.limit is not None:
        tasks = tasks[: args.limit]
    if not tasks:
        print(f"[eval] no tasks found for mode={args.mode}")
        return 1

    results: list[dict[str, object]] = []
    for task in tasks:
        results.append(_run_task(task, run_id, args.mode))

    output_dir = PROJECT_ROOT / "outputs" / "eval_results"
    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / f"{run_id}.jsonl"
    summary_path = output_dir / f"{run_id}_summary.json"
    _write_jsonl(results_path, results)
    summary = _build_summary(run_id, args.mode, results, results_path, summary_path)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[eval] results={results_path}")
    print(f"[eval] summary={summary_path}")
    print(f"[eval] overall_passed={summary['overall_passed']}")
    return 0 if summary["overall_passed"] else 1


def _load_tasks(path: Path, mode: str) -> list[dict[str, object]]:
    tasks: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        task = json.loads(line)
        task_mode = str(task.get("mode", "agent_mock"))
        if task_mode == mode or (mode in MOCK_BASELINE_MODES and task_mode == "agent_mock"):
            tasks.append(task)
    print(f"[eval] loaded tasks={len(tasks)} mode={mode}")
    return tasks


def _run_task(task: dict[str, object], run_id: str, mode: str) -> dict[str, object]:
    task_id = str(task["task_id"])
    eval_task_id = f"{run_id}_{task_id}"
    scenario = str(task.get("mock_scenario") or _infer_mock_scenario(task))
    max_steps = int(task.get("max_steps") or _default_max_steps(scenario))
    query = str(task["query"])

    print(f"[eval] run task={task_id}, mode={mode}, scenario={scenario}, max_steps={max_steps}")
    started_at = time.perf_counter()
    if mode == "direct_mock":
        answer, verification = _run_direct_mock_task(task, eval_task_id, query)
    elif mode == "rag_only_mock":
        answer, verification = _run_rag_only_mock_task(task, eval_task_id, query)
    else:
        answer, verification = _run_agent_mock_task(eval_task_id, scenario, max_steps, query)
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)

    evidence_path = PROJECT_ROOT / "outputs" / "evidence" / f"{eval_task_id}.jsonl"
    trajectory_path = PROJECT_ROOT / "outputs" / "trajectories" / f"{eval_task_id}.jsonl"
    evidence = _read_jsonl(evidence_path)
    trajectory = _read_jsonl(trajectory_path)
    metrics = _score_task(task, verification, evidence, trajectory, answer, elapsed_ms)

    return {
        "task_id": task_id,
        "eval_task_id": eval_task_id,
        "type": task.get("type"),
        "mode": mode,
        "mock_scenario": scenario,
        "difficulty": task.get("difficulty"),
        "category": task.get("category"),
        "tags": task.get("tags", []),
        "query": query,
        "expected_tools": task.get("expected_tools", []),
        "required_evidence_types": task.get("required_evidence_types", []),
        "expected_evidence_count": task.get("expected_evidence_count", 1),
        "metrics": metrics,
        "passed": metrics["passed"],
        "answer": answer,
        "evidence_path": str(evidence_path.relative_to(PROJECT_ROOT)),
        "trajectory_path": str(trajectory_path.relative_to(PROJECT_ROOT)),
    }


def _run_agent_mock_task(
    eval_task_id: str,
    scenario: str,
    max_steps: int,
    query: str,
) -> tuple[str, dict[str, object]]:
    agent = AgentLoop(
        registry=build_registry(),
        llm_client=MockLLMClient(scenario=scenario),
        max_steps=max_steps,
        trajectory_logger=TrajectoryLogger(),
        task_id=eval_task_id,
    )
    run_result = agent.run(query)
    return run_result.answer, run_result.verification or {}


def _run_direct_mock_task(task: dict[str, object], eval_task_id: str, query: str) -> tuple[str, dict[str, object]]:
    print(f"[eval] direct_mock baseline task={task.get('task_id')}")
    evidence_memory = EvidenceMemory()
    trajectory_logger = TrajectoryLogger()
    evidence_memory.reset_jsonl(eval_task_id)
    trajectory_logger.reset_task(eval_task_id)

    answer = f"Direct mock answer for: {query}. This baseline does not call tools or collect Evidence Memory."
    verification = Verifier().verify_final_answer(answer, evidence_memory, task=query).to_dict()
    _save_synthetic_step(
        trajectory_logger=trajectory_logger,
        task_id=eval_task_id,
        step=1,
        action="final_answer",
        args={"answer": answer},
        observation_summary="direct_mock returned an answer without tool evidence",
        question=query,
        evidence_ids=[],
        verifier=verification,
    )
    evidence_memory.mark_used(extract_evidence_refs(answer))
    evidence_memory.save_jsonl(eval_task_id)
    return answer, verification


def _run_rag_only_mock_task(task: dict[str, object], eval_task_id: str, query: str) -> tuple[str, dict[str, object]]:
    print(f"[eval] rag_only_mock baseline task={task.get('task_id')}")
    evidence_memory = EvidenceMemory()
    trajectory_logger = TrajectoryLogger()
    evidence_memory.reset_jsonl(eval_task_id)
    trajectory_logger.reset_task(eval_task_id)

    evidence = evidence_memory.add(
        source_type="doc",
        source="rag_only_mock",
        content=f"Mock document evidence for {query}. Software Engineering docs can support document QA only.",
        reason=f"rag_only_mock retrieved document evidence for query: {query}",
        score=1,
        metadata={"baseline": "rag_only_mock"},
    )
    _save_synthetic_step(
        trajectory_logger=trajectory_logger,
        task_id=eval_task_id,
        step=1,
        action="search_docs",
        args={"query": query, "source": "rag_only_mock", "top_k": 1},
        observation_summary="rag_only_mock retrieved one document evidence item",
        question=query,
        evidence_ids=[evidence.evidence_id],
    )

    answer = (
        f"RAG-only mock answer for {query}. It uses document evidence but does not inspect repository code "
        f"or generate patch/test suggestions. [{evidence.evidence_id}]"
    )
    evidence_memory.mark_used(extract_evidence_refs(answer))
    verification = Verifier().verify_final_answer(answer, evidence_memory, task=query).to_dict()
    _save_synthetic_step(
        trajectory_logger=trajectory_logger,
        task_id=eval_task_id,
        step=2,
        action="final_answer",
        args={"answer": answer},
        observation_summary="rag_only_mock returned final answer with document evidence",
        question=query,
        evidence_ids=[evidence.evidence_id],
        verifier=verification,
    )
    evidence_memory.save_jsonl(eval_task_id)
    return answer, verification


def _save_synthetic_step(
    trajectory_logger: TrajectoryLogger,
    task_id: str,
    step: int,
    action: str,
    args: dict[str, object],
    observation_summary: str,
    question: str,
    evidence_ids: list[str],
    verifier: dict[str, object] | None = None,
) -> None:
    trajectory_logger.save_step(
        TrajectoryStep(
            task_id=task_id,
            step=step,
            action=action,
            args=args,
            observation_summary=observation_summary,
            question=question,
            phase="baseline",
            evidence_ids=evidence_ids,
            verifier=verifier or {},
        )
    )


def _score_task(
    task: dict[str, object],
    verification: dict[str, object],
    evidence: list[dict[str, object]],
    trajectory: list[dict[str, object]],
    answer: str,
    elapsed_ms: int,
) -> dict[str, object]:
    actions = [str(item.get("action", "")) for item in trajectory]
    evidence_types = {str(item.get("source_type", "")) for item in evidence}
    expected_tools = [str(item) for item in task.get("expected_tools", [])]
    required_evidence_types = [str(item) for item in task.get("required_evidence_types", [])]
    expected_evidence_count = int(task.get("expected_evidence_count") or 1)

    missing_tools = [item for item in expected_tools if item not in actions]
    missing_evidence_types = [item for item in required_evidence_types if item not in evidence_types]
    used_evidence_count = sum(1 for item in evidence if item.get("used_in_final") is True)
    expected_evidence_count_met = used_evidence_count >= expected_evidence_count
    final_verifier_passed = verification.get("passed") is True
    answer_point_hits = _count_answer_point_hits(answer, task.get("expected_answer_points", []))
    latency_ms = sum(int(item.get("latency_ms", 0)) for item in trajectory) or elapsed_ms
    passed = (
        final_verifier_passed
        and not missing_tools
        and not missing_evidence_types
        and expected_evidence_count_met
    )

    return {
        "passed": passed,
        "final_verifier_passed": final_verifier_passed,
        "expected_tools_covered": not missing_tools,
        "missing_tools": missing_tools,
        "required_evidence_types_covered": not missing_evidence_types,
        "missing_evidence_types": missing_evidence_types,
        "expected_evidence_count": expected_evidence_count,
        "used_evidence_count": used_evidence_count,
        "expected_evidence_count_met": expected_evidence_count_met,
        "trajectory_steps": len(trajectory),
        "latency_ms": latency_ms,
        "answer_point_hits": answer_point_hits,
        "actions": actions,
        "evidence_types": sorted(evidence_types),
    }


def _count_answer_point_hits(answer: str, expected_answer_points: object) -> int:
    lowered = answer.lower()
    hits = 0
    for item in expected_answer_points if isinstance(expected_answer_points, list) else []:
        words = [word.lower() for word in str(item).replace("/", " ").split() if len(word) >= 4]
        if words and any(word in lowered for word in words):
            hits += 1
    return hits


def _build_summary(
    run_id: str,
    mode: str,
    results: list[dict[str, object]],
    results_path: Path,
    summary_path: Path,
) -> dict[str, object]:
    passed_count = sum(1 for item in results if item.get("passed") is True)
    total_latency_ms = sum(int(item.get("metrics", {}).get("latency_ms", 0)) for item in results)
    total_steps = sum(int(item.get("metrics", {}).get("trajectory_steps", 0)) for item in results)
    return {
        "run_id": run_id,
        "mode": mode,
        "task_count": len(results),
        "passed_count": passed_count,
        "overall_passed": passed_count == len(results),
        "pass_rate": passed_count / len(results) if results else 0,
        "total_latency_ms": total_latency_ms,
        "avg_latency_ms": int(total_latency_ms / len(results)) if results else 0,
        "avg_trajectory_steps": total_steps / len(results) if results else 0,
        "by_type": _group_summary(results, "type"),
        "by_scenario": _group_summary(results, "mock_scenario"),
        "by_difficulty": _group_summary(results, "difficulty"),
        "by_category": _group_summary(results, "category"),
        "results_path": str(results_path.relative_to(PROJECT_ROOT)),
        "summary_path": str(summary_path.relative_to(PROJECT_ROOT)),
    }


def _group_summary(results: list[dict[str, object]], key: str) -> dict[str, dict[str, object]]:
    groups: dict[str, list[dict[str, object]]] = {}
    for item in results:
        value = str(item.get(key) or "unknown")
        groups.setdefault(value, []).append(item)

    summary: dict[str, dict[str, object]] = {}
    for value, rows in sorted(groups.items()):
        passed_count = sum(1 for item in rows if item.get("passed") is True)
        total_latency_ms = sum(int(item.get("metrics", {}).get("latency_ms", 0)) for item in rows)
        total_steps = sum(int(item.get("metrics", {}).get("trajectory_steps", 0)) for item in rows)
        summary[value] = {
            "task_count": len(rows),
            "passed_count": passed_count,
            "pass_rate": passed_count / len(rows) if rows else 0,
            "avg_latency_ms": int(total_latency_ms / len(rows)) if rows else 0,
            "avg_trajectory_steps": total_steps / len(rows) if rows else 0,
        }
    return summary


def _infer_mock_scenario(task: dict[str, object]) -> str:
    task_type = str(task.get("type", "")).lower()
    if "fix" in task_type or "verifier" in task_type:
        return "fix"
    if "where" in task_type or "repo" in task_type:
        return "code"
    return "docs"


def _default_max_steps(scenario: str) -> int:
    if scenario == "fix":
        return 6
    if scenario == "code":
        return 4
    return 3


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    records: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
