import json
import socket
import subprocess
import sys
import time
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "backend_api_check_docs"
PROJECT_PICKER_FIXTURE = PROJECT_ROOT / "outputs" / "project_picker_fixture"


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
            _check_mock_ask(port),
            _check_evidence(port),
            _check_trajectory(port),
            _check_reports(port),
            _check_select_project_root(port),
            _check_max_steps_upper_bound(port),
            _check_invalid_max_steps(port),
            _check_invalid_json(port),
            _check_invalid_scenario(port),
        ]
    finally:
        _stop_server(process)

    passed = all(item[1] for item in checks)
    for name, ok, detail in checks:
        status = "passed" if ok else "failed"
        print(f"[backend API] {name}: {status}")
        if detail:
            print(f"      {detail}")
    print(f"[backend API] overall: {'passed' if passed else 'failed'}")
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
    print(f"[check_backend_api] start server: {' '.join(command)}")
    env = os.environ.copy()
    _prepare_project_picker_fixture()
    env["SE_EXPLORER_TEST_PROJECT_ROOT"] = str(PROJECT_PICKER_FIXTURE)
    return subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        env=env,
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
    return "GET /api/health", ok, "" if ok else str(data)


def _check_examples(port: int) -> tuple[str, bool, str]:
    data = _get_json(port, "/api/examples")
    scenarios = {item.get("mock_scenario") for item in data.get("examples", []) if isinstance(item, dict)}
    ok = {"docs", "code", "fix", "test", "multimodal"}.issubset(scenarios)
    return "GET /api/examples", ok, "" if ok else str(data)


def _check_tools(port: int) -> tuple[str, bool, str]:
    data = _get_json(port, "/api/tools")
    names = {item.get("name") for item in data.get("tools", []) if isinstance(item, dict)}
    required = {"search_docs", "search_code", "view_file", "search_tables", "search_figures", "run_tests"}
    missing = sorted(required - names)
    return "GET /api/tools", not missing, "" if not missing else f"missing={missing}"


def _check_mock_ask(port: int) -> tuple[str, bool, str]:
    payload = {
        "question": "software architecture",
        "mock": "true",
        "mock_scenario": "docs",
        "max_steps": "3",
        "task_id": TASK_ID,
    }
    data = _post_json(port, "/api/ask", payload)
    ok = (
        data.get("task_id") == TASK_ID
        and data.get("verification", {}).get("passed") is True
        and len(data.get("evidence", [])) >= 1
        and len(data.get("trajectory", [])) >= 2
        and data.get("answer")
    )
    return "POST /api/ask", ok, "" if ok else str(data)[:1000]


def _check_evidence(port: int) -> tuple[str, bool, str]:
    data = _get_json(port, f"/api/evidence?task_id={TASK_ID}")
    ok = data.get("task_id") == TASK_ID and bool(data.get("evidence"))
    return "GET /api/evidence", ok, "" if ok else str(data)


def _check_trajectory(port: int) -> tuple[str, bool, str]:
    data = _get_json(port, f"/api/trajectory?task_id={TASK_ID}")
    actions = {item.get("action") for item in data.get("trajectory", []) if isinstance(item, dict)}
    ok = data.get("task_id") == TASK_ID and {"search_docs", "final_answer"}.issubset(actions)
    return "GET /api/trajectory", ok, "" if ok else str(data)


def _check_reports(port: int) -> tuple[str, bool, str]:
    data = _get_json(port, "/api/reports")
    report_types = {item.get("type") for item in data.get("reports", []) if isinstance(item, dict)}
    required = {"baseline", "difficulty", "human_scoring", "real_baseline_sample", "hybrid_rag_eval"}
    missing = sorted(required - report_types)
    return "GET /api/reports", not missing, "" if not missing else f"missing={missing}"


def _check_select_project_root(port: int) -> tuple[str, bool, str]:
    data = _post_json(port, "/api/select-project-root", {})
    files = data.get("files", [])
    ok = (
        data.get("project_root") == str(PROJECT_PICKER_FIXTURE.resolve())
        and data.get("project_name") == PROJECT_PICKER_FIXTURE.name
        and isinstance(files, list)
        and any(item.get("path") == "src/App.jsx" for item in files if isinstance(item, dict))
    )
    return "POST /api/select-project-root", ok, "" if ok else str(data)


def _prepare_project_picker_fixture() -> None:
    src = PROJECT_PICKER_FIXTURE / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "App.jsx").write_text("export default function App() { return <main>demo</main>; }\n", encoding="utf-8")
    (PROJECT_PICKER_FIXTURE / "README.md").write_text("# Project Picker Fixture\n", encoding="utf-8")


def _check_max_steps_upper_bound(port: int) -> tuple[str, bool, str]:
    payload = {
        "question": "software architecture",
        "mock": True,
        "mock_scenario": "docs",
        "max_steps": 50,
        "task_id": "backend_api_check_max_steps_50",
    }
    data = _post_json(port, "/api/ask", payload)
    ok = data.get("task_id") == "backend_api_check_max_steps_50" and data.get("answer")
    return "POST /api/ask max_steps=50", ok, "" if ok else str(data)[:1000]


def _check_invalid_max_steps(port: int) -> tuple[str, bool, str]:
    payload = {
        "question": "software architecture",
        "mock": True,
        "mock_scenario": "docs",
        "max_steps": 51,
        "task_id": "backend_api_check_invalid_max_steps",
    }
    status, data = _post_json_with_status(port, "/api/ask", payload)
    ok = status == 400 and "max_steps must be between 1 and 50" in str(data.get("error", ""))
    return "POST /api/ask invalid max_steps", ok, "" if ok else str({"status": status, "data": data})


def _check_invalid_json(port: int) -> tuple[str, bool, str]:
    status, data = _post_raw(port, "/api/ask", b"{bad json")
    ok = status == 400 and data.get("error") == "invalid json payload"
    return "POST /api/ask invalid json", ok, "" if ok else str({"status": status, "data": data})


def _check_invalid_scenario(port: int) -> tuple[str, bool, str]:
    payload = {
        "question": "software architecture",
        "mock": True,
        "mock_scenario": "unknown",
        "max_steps": 3,
        "task_id": "backend_api_check_invalid",
    }
    status, data = _post_json_with_status(port, "/api/ask", payload)
    ok = status == 400 and "mock_scenario must be one of" in str(data.get("error", ""))
    return "POST /api/ask invalid scenario", ok, "" if ok else str({"status": status, "data": data})


def _get_json(port: int, path: str) -> dict[str, object]:
    with urlopen(f"http://127.0.0.1:{port}{path}", timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json(port: int, path: str, payload: dict[str, object]) -> dict[str, object]:
    status, data = _post_json_with_status(port, path, payload)
    if status != 200:
        raise RuntimeError(f"unexpected status={status}, data={data}")
    return data


def _post_json_with_status(port: int, path: str, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
    return _post_raw(port, path, json.dumps(payload).encode("utf-8"))


def _post_raw(port: int, path: str, body: bytes) -> tuple[int, dict[str, object]]:
    request = Request(
        f"http://127.0.0.1:{port}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


if __name__ == "__main__":
    raise SystemExit(main())
