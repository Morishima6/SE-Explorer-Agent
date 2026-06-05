import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "p3_real_baseline_sample_check"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    checks = [
        _run_dry_sample(),
        _check_json_report(),
        _check_markdown_report(),
        _check_real_mode_is_opt_in(),
    ]
    passed = all(item[1] for item in checks)
    for name, ok, detail in checks:
        status = "passed" if ok else "failed"
        print(f"[P3 real baseline sample] {name}: {status}")
        if detail:
            print(f"  {detail}")
    print(f"[P3 real baseline sample] overall: {'passed' if passed else 'failed'}")
    return 0 if passed else 1


def _run_dry_sample() -> tuple[str, bool, str]:
    command = [
        sys.executable,
        "eval/run_real_baseline_sample.py",
        "--run-id",
        RUN_ID,
    ]
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
    ok = completed.returncode == 0 and "[real_baseline_sample] completed=True" in output
    return "dry-run sample runner", ok, "" if ok else f"returncode={completed.returncode}; output={output[-2000:]}"


def _check_json_report() -> tuple[str, bool, str]:
    report = _read_report()
    baselines = report.get("baselines", [])
    names = {item.get("baseline") for item in baselines if isinstance(item, dict)}
    rag = next((item for item in baselines if isinstance(item, dict) and item.get("baseline") == "rag_only_real"), {})
    ok = (
        report.get("run_id") == RUN_ID
        and report.get("run_real") is False
        and report.get("completed") is True
        and names == {"direct_real", "rag_only_real", "agent_real"}
        and all(item.get("run_mode") == "dry_run" for item in baselines if isinstance(item, dict))
        and int(rag.get("evidence_count", 0)) >= 0
        and "retrieval_preview" in rag
    )
    return "json report", ok, "" if ok else str(report)


def _check_markdown_report() -> tuple[str, bool, str]:
    path = PROJECT_ROOT / "outputs" / "eval_results" / f"{RUN_ID}_real_baseline_sample.md"
    if not path.exists():
        return "markdown report", False, f"missing {path}"
    text = path.read_text(encoding="utf-8", errors="replace")
    required = ["P3 Real Baseline Sample", "direct_real", "rag_only_real", "agent_real", "Run real model: `False`"]
    missing = [item for item in required if item not in text]
    return "markdown report", not missing, "" if not missing else f"missing={missing}"


def _check_real_mode_is_opt_in() -> tuple[str, bool, str]:
    report = _read_report()
    notes = "\n".join(str(item) for item in report.get("notes", []))
    ok = "Default dry-run mode does not call a real model" in notes and "Use --run-real" in notes
    return "real mode opt-in", ok, "" if ok else notes


def _read_report() -> dict[str, object]:
    path = PROJECT_ROOT / "outputs" / "eval_results" / f"{RUN_ID}_real_baseline_sample.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


if __name__ == "__main__":
    raise SystemExit(main())
