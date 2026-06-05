import argparse
import json
import os
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

from agent.evidence_extractor import extract_evidence_from_tool_result
from agent.evidence_memory import EvidenceMemory
from agent.llm_client import LLMClient
from agent.loop import AgentLoop
from agent.trajectory import TrajectoryLogger, TrajectoryStep
from agent.verifier import Verifier, extract_evidence_refs
from demo.app import _load_project_env, build_registry
from tools.search_docs import search_docs


BASELINES = ["direct_real", "rag_only_real", "agent_real"]
DEFAULT_QUERY = "Graduate Software Engineering curriculum evidence"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a small real-baseline preview sample")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--max-steps", type=int, default=4)
    parser.add_argument("--run-real", action="store_true", help="Call the configured model. This may consume quota.")
    parser.add_argument("--model", default=None, help="Override OPENAI_MODEL for --run-real.")
    args = parser.parse_args()

    run_id = args.run_id or datetime.now().strftime("p3_real_baseline_%Y%m%d_%H%M%S")
    if args.run_real:
        _load_project_env()
        client = LLMClient(model=args.model)
        records = [
            _run_direct_real(run_id, args.query, client),
            _run_rag_only_real(run_id, args.query, client),
            _run_agent_real(run_id, args.query, client, args.max_steps),
        ]
    else:
        records = _build_dry_run_records(run_id, args.query, args.max_steps, args.model)

    report = _build_report(run_id, args.query, args.max_steps, args.run_real, records)
    output_dir = PROJECT_ROOT / "outputs" / "eval_results"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{run_id}_real_baseline_sample.json"
    markdown_path = output_dir / f"{run_id}_real_baseline_sample.md"
    report["json_path"] = str(json_path.relative_to(PROJECT_ROOT))
    report["markdown_path"] = str(markdown_path.relative_to(PROJECT_ROOT))
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_format_markdown(report), encoding="utf-8")

    print(f"[real_baseline_sample] json={json_path}")
    print(f"[real_baseline_sample] markdown={markdown_path}")
    print(f"[real_baseline_sample] run_real={args.run_real}")
    print(f"[real_baseline_sample] completed={report['completed']}")
    return 0 if report["completed"] else 1


def _build_dry_run_records(run_id: str, query: str, max_steps: int, model: str | None) -> list[dict[str, Any]]:
    rag_results = search_docs(query=query, source="hybrid", top_k=3)
    common = {
        "run_mode": "dry_run",
        "status": "planned",
        "model": model or os.environ.get("OPENAI_MODEL") or "not_configured",
        "requires_run_real": True,
    }
    return [
        {
            **common,
            "baseline": "direct_real",
            "description": "Direct LLM answer without tool calls or Evidence Memory.",
            "planned_steps": ["llm_complete", "save_report"],
            "expected_risk": "No grounded evidence or repository interaction.",
            "evidence_count": 0,
            "trajectory_steps": 1,
        },
        {
            **common,
            "baseline": "rag_only_real",
            "description": "Hybrid search_docs retrieves evidence, then LLM answers from retrieved snippets only.",
            "planned_steps": ["search_docs", "llm_complete_with_evidence", "verifier"],
            "expected_risk": "Document evidence can answer docs questions but cannot inspect code paths.",
            "evidence_count": len(rag_results),
            "trajectory_steps": 2,
            "retrieval_preview": _preview_rag_results(rag_results),
        },
        {
            **common,
            "baseline": "agent_real",
            "description": "Full AgentLoop with real LLM JSON actions and registered tools.",
            "planned_steps": ["build_agent_messages", "parse_action", "tool_call", "verifier"],
            "expected_risk": "Model may choose invalid JSON, wrong tool, or stop before verifier passes.",
            "evidence_count": None,
            "trajectory_steps": f"up to {max_steps}",
        },
    ]


def _run_direct_real(run_id: str, query: str, client: LLMClient) -> dict[str, Any]:
    task_id = f"{run_id}_direct_real"
    memory = EvidenceMemory()
    trajectory = TrajectoryLogger()
    memory.reset_jsonl(task_id)
    trajectory.reset_task(task_id)
    started = time.perf_counter()
    answer = client.complete(
        [
            {"role": "system", "content": "Answer directly and concisely. Do not invent citations."},
            {"role": "user", "content": query},
        ]
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    verification = Verifier().verify_final_answer(answer, memory, task=query).to_dict()
    trajectory.save_step(
        TrajectoryStep(
            task_id=task_id,
            step=1,
            question=query,
            phase="baseline",
            action="direct_llm",
            args={"model": client.model},
            observation_summary=_shorten(answer),
            verifier=verification,
            success=verification.get("passed") is True,
            latency_ms=latency_ms,
        )
    )
    memory.save_jsonl(task_id)
    return _baseline_record(
        baseline="direct_real",
        task_id=task_id,
        status="completed",
        run_mode="real",
        model=client.model,
        answer=answer,
        verification=verification,
        evidence=memory.to_dicts(),
        trajectory_steps=1,
        latency_ms=latency_ms,
    )


def _run_rag_only_real(run_id: str, query: str, client: LLMClient) -> dict[str, Any]:
    task_id = f"{run_id}_rag_only_real"
    memory = EvidenceMemory()
    trajectory = TrajectoryLogger()
    memory.reset_jsonl(task_id)
    trajectory.reset_task(task_id)

    started = time.perf_counter()
    results = search_docs(query=query, source="hybrid", top_k=3)
    evidence_ids = extract_evidence_from_tool_result(
        tool_name="search_docs",
        args={"query": query, "source": "hybrid", "top_k": 3},
        result=results,
        evidence_memory=memory,
    )
    trajectory.save_step(
        TrajectoryStep(
            task_id=task_id,
            step=1,
            question=query,
            phase="baseline",
            action="search_docs",
            args={"query": query, "source": "hybrid", "top_k": 3},
            observation_summary=f"retrieved {len(results)} document snippets",
            evidence_ids=evidence_ids,
            success=bool(results),
        )
    )
    evidence_prompt = memory.format_for_prompt(max_items=3)
    answer = client.complete(
        [
            {
                "role": "system",
                "content": (
                    "Answer using only the provided Evidence Memory. "
                    "Cite evidence ids like [ev_001]. If evidence is insufficient, say so."
                ),
            },
            {"role": "user", "content": f"Question:\n{query}\n\nEvidence Memory:\n{evidence_prompt}"},
        ]
    )
    memory.mark_used(extract_evidence_refs(answer))
    verification = Verifier().verify_final_answer(answer, memory, task=query).to_dict()
    latency_ms = int((time.perf_counter() - started) * 1000)
    trajectory.save_step(
        TrajectoryStep(
            task_id=task_id,
            step=2,
            question=query,
            phase="baseline",
            action="rag_only_llm",
            args={"model": client.model},
            observation_summary=_shorten(answer),
            evidence_ids=extract_evidence_refs(answer),
            verifier=verification,
            success=verification.get("passed") is True,
            latency_ms=latency_ms,
        )
    )
    memory.save_jsonl(task_id)
    return _baseline_record(
        baseline="rag_only_real",
        task_id=task_id,
        status="completed",
        run_mode="real",
        model=client.model,
        answer=answer,
        verification=verification,
        evidence=memory.to_dicts(),
        trajectory_steps=2,
        latency_ms=latency_ms,
    )


def _run_agent_real(run_id: str, query: str, client: LLMClient, max_steps: int) -> dict[str, Any]:
    task_id = f"{run_id}_agent_real"
    started = time.perf_counter()
    agent = AgentLoop(
        registry=build_registry(),
        llm_client=client,
        max_steps=max_steps,
        trajectory_logger=TrajectoryLogger(),
        task_id=task_id,
    )
    result = agent.run(query)
    latency_ms = int((time.perf_counter() - started) * 1000)
    return _baseline_record(
        baseline="agent_real",
        task_id=task_id,
        status="completed",
        run_mode="real",
        model=client.model,
        answer=result.answer,
        verification=result.verification or {},
        evidence=result.evidence,
        trajectory_steps=len(result.history) + (1 if result.final_action else 0),
        latency_ms=latency_ms,
    )


def _baseline_record(
    baseline: str,
    task_id: str,
    status: str,
    run_mode: str,
    model: str | None,
    answer: str,
    verification: dict[str, Any],
    evidence: list[dict[str, object]],
    trajectory_steps: int,
    latency_ms: int,
) -> dict[str, Any]:
    return {
        "baseline": baseline,
        "task_id": task_id,
        "status": status,
        "run_mode": run_mode,
        "model": model,
        "answer": answer,
        "verification": verification,
        "evidence_count": len(evidence),
        "used_evidence_count": sum(1 for item in evidence if item.get("used_in_final") is True),
        "trajectory_steps": trajectory_steps,
        "latency_ms": latency_ms,
        "evidence_path": f"outputs/evidence/{task_id}.jsonl",
        "trajectory_path": f"outputs/trajectories/{task_id}.jsonl",
    }


def _build_report(
    run_id: str,
    query: str,
    max_steps: int,
    run_real: bool,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    completed = {item["baseline"] for item in records} == set(BASELINES)
    if run_real:
        completed = completed and all(item.get("status") == "completed" for item in records)
    return {
        "run_id": run_id,
        "query": query,
        "max_steps": max_steps,
        "run_real": run_real,
        "completed": completed,
        "baselines": records,
        "notes": [
            "This is a small P3 preview, not a statistically meaningful benchmark.",
            "Default dry-run mode does not call a real model or consume API quota.",
            "Use --run-real to execute direct_real, rag_only_real, and agent_real once.",
        ],
    }


def _format_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# P3 Real Baseline Sample",
        "",
        f"Run ID: `{report['run_id']}`",
        f"Run real model: `{report['run_real']}`",
        f"Query: `{report['query']}`",
        "",
        "| Baseline | Status | Mode | Evidence | Steps | Verifier | Notes |",
        "|---|---|---|---:|---:|---|---|",
    ]
    for item in report["baselines"]:
        verifier = item.get("verification", {})
        verifier_text = str(verifier.get("passed")) if isinstance(verifier, dict) and verifier else "n/a"
        notes = item.get("description") or item.get("expected_risk") or ""
        lines.append(
            f"| {item['baseline']} | {item['status']} | {item['run_mode']} | "
            f"{item.get('evidence_count', 'n/a')} | {item.get('trajectory_steps', 'n/a')} | "
            f"{verifier_text} | {notes} |"
        )
    lines.extend(["", "## Notes", ""])
    for note in report["notes"]:
        lines.append(f"- {note}")
    return "\n".join(lines)


def _preview_rag_results(results: list[dict[str, object]]) -> list[dict[str, object]]:
    preview: list[dict[str, object]] = []
    for item in results[:3]:
        metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
        preview.append(
            {
                "source": item.get("source"),
                "score": item.get("score"),
                "doc_id": metadata.get("doc_id"),
                "retrieval_strategy": metadata.get("retrieval_strategy"),
                "candidate_sources": metadata.get("candidate_sources", []),
                "snippet": _shorten(str(item.get("snippet", "")), 240),
            }
        )
    return preview


def _shorten(text: str, max_chars: int = 500) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


if __name__ == "__main__":
    raise SystemExit(main())
