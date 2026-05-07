import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks: list[tuple[str, bool, str]] = []
    checks.append(_run_command("compileall", [sys.executable, "-m", "compileall", "agent", "tools", "rag", "demo", "scripts"]))
    checks.append(_run_command("tool registry", [sys.executable, "demo/app.py", "list"], required_text="shell_readonly"))
    checks.append(
        _run_command(
            "docs demo",
            [
                sys.executable,
                "demo/app.py",
                "ask",
                "software architecture",
                "--mock",
                "--mock-scenario",
                "docs",
                "--max-steps",
                "3",
                "--task-id",
                "p0_demo_docs",
            ],
            required_text='"passed": true',
        )
    )
    checks.append(
        _run_command(
            "code demo",
            [
                sys.executable,
                "demo/app.py",
                "ask",
                "search_docs 工具在哪里注册和调用？",
                "--mock",
                "--mock-scenario",
                "code",
                "--max-steps",
                "4",
                "--task-id",
                "p0_demo_code",
            ],
            required_text='"passed": true',
        )
    )
    checks.append(
        _run_command(
            "fix demo",
            [
                sys.executable,
                "demo/app.py",
                "ask",
                "请给出 verifier 缺少证据引用时的轻量修复建议和测试建议",
                "--mock",
                "--mock-scenario",
                "fix",
                "--max-steps",
                "6",
                "--task-id",
                "p0_demo_fix",
            ],
            required_text='"passed": true',
        )
    )

    checks.append(_check_jsonl("docs evidence", "outputs/evidence/p0_demo_docs.jsonl", required_types={"doc"}))
    checks.append(_check_jsonl("code evidence", "outputs/evidence/p0_demo_code.jsonl", required_types={"code", "file"}))
    checks.append(_check_jsonl("fix evidence", "outputs/evidence/p0_demo_fix.jsonl", required_types={"code", "file", "patch", "test"}))
    checks.append(_check_trajectory("docs trajectory", "outputs/trajectories/p0_demo_docs.jsonl", ["search_docs", "final_answer"]))
    checks.append(_check_trajectory("code trajectory", "outputs/trajectories/p0_demo_code.jsonl", ["search_code", "view_file", "final_answer"]))
    checks.append(
        _check_trajectory(
            "fix trajectory",
            "outputs/trajectories/p0_demo_fix.jsonl",
            ["search_code", "view_file", "generate_patch", "suggest_tests", "final_answer"],
        )
    )

    passed = all(item[1] for item in checks)
    for name, ok, detail in checks:
        status = "passed" if ok else "failed"
        print(f"[P0] {name}: {status}")
        if detail:
            print(f"      {detail}")
    print(f"[P0] overall: {'passed' if passed else 'failed'}")
    return 0 if passed else 1


def _run_command(name: str, command: list[str], required_text: str | None = None) -> tuple[str, bool, str]:
    print(f"[check_p0_chain] run {name}: {' '.join(command)}")
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
    ok = completed.returncode == 0 and (required_text is None or required_text in output)
    detail = "" if ok else f"returncode={completed.returncode}"
    if required_text and required_text not in output:
        detail = f"{detail}; missing text: {required_text}".strip("; ")
    return name, ok, detail


def _check_jsonl(name: str, relative_path: str, required_types: set[str]) -> tuple[str, bool, str]:
    path = PROJECT_ROOT / relative_path
    records = _read_jsonl(path)
    types = {str(item.get("source_type")) for item in records}
    used = [item for item in records if item.get("used_in_final") is True]
    missing = sorted(required_types - types)
    ok = bool(records) and not missing and bool(used)
    detail = "" if ok else f"missing_types={missing}, used_in_final={len(used)}, records={len(records)}"
    return name, ok, detail


def _check_trajectory(name: str, relative_path: str, expected_actions: list[str]) -> tuple[str, bool, str]:
    path = PROJECT_ROOT / relative_path
    records = _read_jsonl(path)
    actions = [str(item.get("action")) for item in records]
    missing = [item for item in expected_actions if item not in actions]
    final_steps = [item for item in records if item.get("action") == "final_answer"]
    final_passed = bool(final_steps) and final_steps[-1].get("verifier", {}).get("passed") is True
    ok = bool(records) and not missing and final_passed
    detail = "" if ok else f"missing_actions={missing}, final_passed={final_passed}, actions={actions}"
    return name, ok, detail


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    records: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


if __name__ == "__main__":
    raise SystemExit(main())
