import json
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]

SCENARIO_EXPECTATIONS = {
    "docs": {
        "tools": {"search_docs", "final_answer"},
        "evidence_types": {"doc"},
    },
    "code": {
        "tools": {"search_code", "view_file", "final_answer"},
        "evidence_types": {"code", "file"},
    },
    "fix": {
        "tools": {"search_code", "view_file", "generate_patch", "suggest_tests", "final_answer"},
        "evidence_types": {"code", "file", "patch", "test"},
    },
    "test": {
        "tools": {"search_code", "suggest_tests", "run_tests", "final_answer"},
        "evidence_types": {"code", "test", "test_run"},
    },
    "multimodal": {
        "tools": {"search_docs", "search_figures", "final_answer"},
        "evidence_types": {"doc", "figure"},
    },
}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    port = _free_port()
    process = _start_server(port)
    try:
        checks = [_check_server_start(process, port)]
        examples = _get_json(port, "/api/examples").get("examples", [])
        checks.append(_check_examples(examples))
        for example in examples:
            if not isinstance(example, dict):
                continue
            scenario = str(example.get("mock_scenario") or "")
            if scenario in SCENARIO_EXPECTATIONS:
                checks.append(_check_example_task(port, example))
        checks.append(_check_reports(port))
    finally:
        _stop_server(process)

    passed = all(item[1] for item in checks)
    for name, ok, detail in checks:
        status = "passed" if ok else "failed"
        print(f"[UI integration] {name}: {status}")
        if detail:
            print(f"      {detail}")
    print(f"[UI integration] overall: {'passed' if passed else 'failed'}")
    return 0 if passed else 1


def _start_server(port: int) -> subprocess.Popen[str]:
    command = [
        sys.executable,
        "demo/ui_app.py",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    print(f"[check_ui_integration] start server: {' '.join(command)}")
    return subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )


def _stop_server(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def _check_server_start(process: subprocess.Popen[str], port: int) -> tuple[str, bool, str]:
    deadline = time.time() + 20
    last_error = ""
    while time.time() < deadline:
        if process.poll() is not None:
            return "server start", False, f"server exited returncode={process.returncode}"
        try:
            data = _get_json(port, "/api/health")
            if data.get("ok") is True:
                return "server start", True, ""
        except Exception as exc:
            last_error = str(exc)
            time.sleep(0.2)
    return "server start", False, last_error


def _check_examples(examples: object) -> tuple[str, bool, str]:
    if not isinstance(examples, list):
        return "examples loaded", False, "examples is not a list"
    scenarios = {item.get("mock_scenario") for item in examples if isinstance(item, dict)}
    missing = sorted(set(SCENARIO_EXPECTATIONS) - scenarios)
    return "examples loaded", not missing, "" if not missing else f"missing={missing}"


def _check_example_task(port: int, example: dict[str, object]) -> tuple[str, bool, str]:
    scenario = str(example.get("mock_scenario") or "")
    task_id = f"ui_integration_{scenario}"
    payload = {
        "question": example.get("question") or "software architecture",
        "mock": True,
        "mock_scenario": scenario,
        "max_steps": example.get("max_steps") or 6,
        "task_id": task_id,
    }
    data = _post_json(port, "/api/ask", payload)
    evidence_api = _get_json(port, f"/api/evidence?task_id={task_id}")
    trajectory_api = _get_json(port, f"/api/trajectory?task_id={task_id}")

    expected = SCENARIO_EXPECTATIONS[scenario]
    evidence = data.get("evidence", [])
    trajectory = data.get("trajectory", [])
    actions = {item.get("action") for item in trajectory if isinstance(item, dict)}
    evidence_types = {item.get("source_type") for item in evidence if isinstance(item, dict)}

    checks = {
        "answer": bool(data.get("answer")),
        "verification": isinstance(data.get("verification"), dict),
        "evidence": bool(evidence),
        "trajectory": bool(trajectory),
        "evidence_api": bool(evidence_api.get("evidence")),
        "trajectory_api": bool(trajectory_api.get("trajectory")),
        "tools": expected["tools"].issubset(actions),
        "evidence_types": expected["evidence_types"].issubset(evidence_types),
    }
    ok = all(checks.values())
    detail = "" if ok else str(
        {
            "checks": checks,
            "actions": sorted(str(item) for item in actions),
            "evidence_types": sorted(str(item) for item in evidence_types),
        }
    )
    return f"{scenario} task", ok, detail


def _check_reports(port: int) -> tuple[str, bool, str]:
    data = _get_json(port, "/api/reports")
    reports = data.get("reports", [])
    report_types = {item.get("type") for item in reports if isinstance(item, dict)}
    required = {"baseline", "real_baseline_sample", "hybrid_rag_eval"}
    missing = sorted(required - report_types)
    return "reports readable", not missing, "" if not missing else f"missing={missing}"


def _get_json(port: int, path: str) -> dict[str, object]:
    with urlopen(f"http://127.0.0.1:{port}{path}", timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json(port: int, path: str, payload: dict[str, object]) -> dict[str, object]:
    request = Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


if __name__ == "__main__":
    raise SystemExit(main())
