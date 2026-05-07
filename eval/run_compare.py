import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASELINES = ["direct_mock", "rag_only_mock", "agent_mock"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run baseline comparison for SE-Explorer Agent eval")
    parser.add_argument("--tasks", default="eval/tasks.jsonl")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    run_id = args.run_id or datetime.now().strftime("compare_%Y%m%d_%H%M%S")
    summaries: dict[str, dict[str, object]] = {}
    for baseline in BASELINES:
        summaries[baseline] = _run_baseline(tasks=args.tasks, run_id=run_id, baseline=baseline, limit=args.limit)

    comparison = _build_comparison(run_id, summaries)
    output_dir = PROJECT_ROOT / "outputs" / "eval_results"
    output_dir.mkdir(parents=True, exist_ok=True)
    comparison_path = output_dir / f"{run_id}_comparison.json"
    markdown_path = output_dir / f"{run_id}_comparison.md"
    comparison["comparison_path"] = str(comparison_path.relative_to(PROJECT_ROOT))
    comparison["markdown_path"] = str(markdown_path.relative_to(PROJECT_ROOT))

    comparison_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_format_markdown(comparison), encoding="utf-8")

    print(f"[compare] comparison={comparison_path}")
    print(f"[compare] markdown={markdown_path}")
    print(f"[compare] agent_advantage={comparison['agent_advantage']}")
    return 0 if comparison["agent_advantage"] else 1


def _run_baseline(tasks: str, run_id: str, baseline: str, limit: int | None) -> dict[str, object]:
    baseline_run_id = f"{run_id}_{baseline}"
    command = [
        sys.executable,
        "eval/run_eval.py",
        "--tasks",
        tasks,
        "--mode",
        baseline,
        "--run-id",
        baseline_run_id,
    ]
    if limit is not None:
        command.extend(["--limit", str(limit)])

    print(f"[compare] run baseline={baseline}: {' '.join(command)}")
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    output = completed.stdout + completed.stderr
    if output.strip():
        print(output[-2000:])

    summary_path = PROJECT_ROOT / "outputs" / "eval_results" / f"{baseline_run_id}_summary.json"
    if not summary_path.exists():
        raise RuntimeError(f"missing baseline summary: {summary_path}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["returncode"] = completed.returncode
    return summary


def _build_comparison(run_id: str, summaries: dict[str, dict[str, object]]) -> dict[str, object]:
    baselines: dict[str, dict[str, object]] = {}
    for baseline, summary in summaries.items():
        baselines[baseline] = {
            "task_count": summary.get("task_count", 0),
            "passed_count": summary.get("passed_count", 0),
            "pass_rate": summary.get("pass_rate", 0),
            "avg_latency_ms": summary.get("avg_latency_ms", 0),
            "avg_trajectory_steps": summary.get("avg_trajectory_steps", 0),
            "overall_passed": summary.get("overall_passed", False),
            "summary_path": summary.get("summary_path"),
            "returncode": summary.get("returncode"),
        }

    agent_rate = float(baselines["agent_mock"]["pass_rate"])
    rag_rate = float(baselines["rag_only_mock"]["pass_rate"])
    direct_rate = float(baselines["direct_mock"]["pass_rate"])
    return {
        "run_id": run_id,
        "baselines": baselines,
        "agent_advantage": agent_rate >= rag_rate and agent_rate >= direct_rate,
        "notes": [
            "direct_mock does not call tools or collect evidence",
            "rag_only_mock uses document evidence only",
            "agent_mock uses the full multi-tool SE-Explorer Agent loop",
        ],
    }


def _format_markdown(comparison: dict[str, object]) -> str:
    labels = {
        "direct_mock": "Direct Mock",
        "rag_only_mock": "RAG-only Mock",
        "agent_mock": "SE-Explorer Agent Mock",
    }
    lines = [
        "# Evaluation Baseline Comparison",
        "",
        f"Run ID: `{comparison['run_id']}`",
        "",
        "| Baseline | Tasks | Passed | Pass Rate | Avg Steps | Notes |",
        "|---|---:|---:|---:|---:|---|",
    ]
    baselines = comparison["baselines"]
    for key in BASELINES:
        item = baselines[key]
        note = _baseline_note(key)
        lines.append(
            f"| {labels[key]} | {item['task_count']} | {item['passed_count']} | "
            f"{float(item['pass_rate']):.2f} | {float(item['avg_trajectory_steps']):.2f} | {note} |"
        )
    lines.extend(
        [
            "",
            f"Agent advantage: `{comparison['agent_advantage']}`",
            "",
        ]
    )
    return "\n".join(lines)


def _baseline_note(key: str) -> str:
    if key == "direct_mock":
        return "no tools, no Evidence Memory"
    if key == "rag_only_mock":
        return "document evidence only"
    return "full Agent Loop with evidence, verifier, patch/test chain"


if __name__ == "__main__":
    raise SystemExit(main())
