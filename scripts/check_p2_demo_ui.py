import json
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "p2_demo_ui_check_docs"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    port = _free_port()
    process = _start_server(port)
    try:
        checks = [
            _check_server_start(process, port),
            _check_health(port),
            _check_examples(port),
            _check_tools(port),
            _check_static_index(port),
            _check_static_app(port),
            _check_mock_ask(port),
            _check_evidence_output(port),
            _check_trajectory_output(port),
            _check_reports(port),
        ]
    finally:
        _stop_server(process)

    passed = all(item[1] for item in checks)
    for name, ok, detail in checks:
        status = "passed" if ok else "failed"
        print(f"[P2 demo UI] {name}: {status}")
        if detail:
            print(f"      {detail}")
    print(f"[P2 demo UI] overall: {'passed' if passed else 'failed'}")
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
    print(f"[check_p2_demo_ui] start server: {' '.join(command)}")
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


def _check_health(port: int) -> tuple[str, bool, str]:
    data = _get_json(port, "/api/health")
    ok = data.get("ok") is True and data.get("service") == "se-explorer-demo-ui"
    return "health endpoint", ok, "" if ok else str(data)


def _check_examples(port: int) -> tuple[str, bool, str]:
    data = _get_json(port, "/api/examples")
    examples = data.get("examples", [])
    scenarios = {item.get("mock_scenario") for item in examples if isinstance(item, dict)}
    ok = {"docs", "code", "fix", "test", "multimodal"}.issubset(scenarios)
    return "examples endpoint", ok, "" if ok else str(data)


def _check_tools(port: int) -> tuple[str, bool, str]:
    data = _get_json(port, "/api/tools")
    names = {item.get("name") for item in data.get("tools", []) if isinstance(item, dict)}
    required = {"search_docs", "search_code", "view_file", "search_tables", "search_figures", "run_tests", "shell_readonly"}
    missing = sorted(required - names)
    return "tools endpoint", not missing, "" if not missing else f"missing={missing}"


def _check_static_index(port: int) -> tuple[str, bool, str]:
    text = _get_text(port, "/")
    ok = (
        "SE-Explorer Agent" in text
        and "Trajectory" in text
        and "Evidence" in text
        and "Project Explorer" in text
        and "selectProjectButton" in text
        and "projectRoot" in text
        and "applyProjectPromptButton" in text
        and "project-workspace" in text
        and "code-viewer" in text
        and 'id="reportOutput" class="report-output"' in text
        and "<pre id=\"reportOutput\"" not in text
        and 'id="maxStepsInput" type="number" min="1" max="50" value="10"' in text
    )
    return "static index", ok, "" if ok else text[:300]


def _check_static_app(port: int) -> tuple[str, bool, str]:
    text = _get_text(port, "/app.js")
    ok = (
        "UI-provided code evidence" in text
        and "901 + index" in text
        and "/api/select-project-root" in text
        and "Project Root:" in text
        and "project_root" in text
        and "renderReportMarkdown" in text
        and "renderMarkdownTable" in text
    )
    return "static app.js", ok, "" if ok else text[:300]


def _check_mock_ask(port: int) -> tuple[str, bool, str]:
    payload = {
        "question": "software architecture",
        "mock": True,
        "mock_scenario": "docs",
        "max_steps": 3,
        "task_id": TASK_ID,
    }
    data = _post_json(port, "/api/ask", payload)
    ok = (
        data.get("task_id") == TASK_ID
        and data.get("verification", {}).get("passed") is True
        and "ev_001" in str(data.get("answer", ""))
        and len(data.get("evidence", [])) >= 1
        and len(data.get("trajectory", [])) >= 2
    )
    return "mock ask endpoint", ok, "" if ok else str(data)[:1000]


def _check_evidence_output(port: int) -> tuple[str, bool, str]:
    data = _get_json(port, f"/api/evidence?task_id={TASK_ID}")
    evidence = data.get("evidence", [])
    ok = bool(evidence) and evidence[0].get("source_type") == "doc"
    return "evidence output", ok, "" if ok else str(data)


def _check_trajectory_output(port: int) -> tuple[str, bool, str]:
    data = _get_json(port, f"/api/trajectory?task_id={TASK_ID}")
    actions = [item.get("action") for item in data.get("trajectory", [])]
    ok = "search_docs" in actions and "final_answer" in actions
    return "trajectory output", ok, "" if ok else str(data)


def _check_reports(port: int) -> tuple[str, bool, str]:
    data = _get_json(port, "/api/reports")
    reports = data.get("reports", [])
    report_types = {item.get("type") for item in reports if isinstance(item, dict)}
    ok = {"baseline", "difficulty", "human_scoring", "real_baseline_sample", "hybrid_rag_eval"}.issubset(report_types)
    return "reports endpoint", ok, "" if ok else str(data)


def _get_json(port: int, path: str) -> dict[str, object]:
    text = _get_text(port, path)
    return json.loads(text)


def _get_text(port: int, path: str) -> str:
    with urlopen(f"http://127.0.0.1:{port}{path}", timeout=20) as response:
        return response.read().decode("utf-8")


def _post_json(port: int, path: str, payload: dict[str, object]) -> dict[str, object]:
    request = Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


if __name__ == "__main__":
    raise SystemExit(main())
