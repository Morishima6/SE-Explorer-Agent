import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(__file__).resolve().parent / "ui_static"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from agent.llm_client import LLMClient, MockLLMClient
from agent.loop import AgentLoop
from agent.trajectory import TrajectoryLogger
from demo.app import _load_project_env, _validate_real_llm_env, build_registry


EXAMPLES = [
    {
        "id": "docs",
        "label": "Docs QA",
        "question": "software architecture",
        "mock_scenario": "docs",
        "max_steps": 3,
        "task_id": "ui_demo_docs",
    },
    {
        "id": "code",
        "label": "Code QA",
        "question": "search_docs 工具在哪里注册和调用？",
        "mock_scenario": "code",
        "max_steps": 4,
        "task_id": "ui_demo_code",
    },
    {
        "id": "fix",
        "label": "Fix Suggestion",
        "question": "请给出 verifier 缺少证据引用时的轻量修复建议和测试建议",
        "mock_scenario": "fix",
        "max_steps": 6,
        "task_id": "ui_demo_fix",
    },
    {
        "id": "test",
        "label": "Test Run",
        "question": "compileall validation for shell_readonly test_run evidence",
        "mock_scenario": "test",
        "max_steps": 5,
        "task_id": "ui_demo_test",
    },
    {
        "id": "multimodal",
        "label": "Multimodal",
        "question": "Explain document and figure evidence from parsed RAG-Anything outputs",
        "mock_scenario": "multimodal",
        "max_steps": 4,
        "task_id": "ui_demo_multimodal",
    },
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run SE-Explorer Agent demo UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), DemoUIHandler)
    print(f"[demo_ui] serving http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[demo_ui] shutdown requested")
    finally:
        server.server_close()
    return 0


class DemoUIHandler(BaseHTTPRequestHandler):
    server_version = "SEExplorerDemoUI/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json({"ok": True, "service": "se-explorer-demo-ui"})
            return
        if parsed.path == "/api/examples":
            self._send_json({"examples": EXAMPLES})
            return
        if parsed.path == "/api/tools":
            tools = [
                {"name": tool.name, "description": tool.description}
                for tool in build_registry().list_tools()
            ]
            self._send_json({"tools": tools})
            return
        if parsed.path == "/api/evidence":
            task_id = _safe_task_id(parse_qs(parsed.query).get("task_id", ["ui_demo_docs"])[0])
            self._send_json({"task_id": task_id, "evidence": _read_jsonl(PROJECT_ROOT / "outputs" / "evidence" / f"{task_id}.jsonl")})
            return
        if parsed.path == "/api/trajectory":
            task_id = _safe_task_id(parse_qs(parsed.query).get("task_id", ["ui_demo_docs"])[0])
            self._send_json({"task_id": task_id, "trajectory": _read_jsonl(PROJECT_ROOT / "outputs" / "trajectories" / f"{task_id}.jsonl")})
            return
        if parsed.path == "/api/reports":
            self._send_json({"reports": _load_reports()})
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/ask":
            self._send_json({"error": "not found"}, status=404)
            return
        payload = self._read_payload()
        try:
            response = run_agent_from_payload(payload)
        except Exception as exc:
            print(f"[demo_ui] ask failed: {exc}")
            self._send_json({"error": str(exc)}, status=500)
            return
        self._send_json(response)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[demo_ui] {self.address_string()} - {format % args}")

    def _read_payload(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        return json.loads(raw or "{}")

    def _serve_static(self, path: str) -> None:
        relative = "index.html" if path in {"", "/"} else path.lstrip("/")
        file_path = (STATIC_DIR / relative).resolve()
        if STATIC_DIR.resolve() not in file_path.parents and file_path != STATIC_DIR.resolve():
            self._send_json({"error": "invalid static path"}, status=400)
            return
        if not file_path.exists() or not file_path.is_file():
            self._send_json({"error": "not found"}, status=404)
            return
        content_type = _content_type(file_path.suffix)
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, data: object, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_agent_from_payload(payload: dict[str, object]) -> dict[str, object]:
    question = str(payload.get("question") or "software architecture")
    task_id = _safe_task_id(str(payload.get("task_id") or "ui_demo_task"))
    mock = bool(payload.get("mock", True))
    scenario = str(payload.get("mock_scenario") or "docs")
    max_steps = int(payload.get("max_steps") or 6)
    model = payload.get("model")

    print(f"[demo_ui] run ask task_id={task_id}, mock={mock}, scenario={scenario}, max_steps={max_steps}")
    registry = build_registry()
    if mock:
        llm_client = MockLLMClient(scenario=scenario)
    else:
        _load_project_env()
        _validate_real_llm_env(str(model) if model else None)
        llm_client = LLMClient(model=str(model) if model else None)

    agent = AgentLoop(
        registry=registry,
        llm_client=llm_client,
        max_steps=max_steps,
        trajectory_logger=TrajectoryLogger(),
        task_id=task_id,
    )
    result = agent.run(question)
    trajectory_path = PROJECT_ROOT / "outputs" / "trajectories" / f"{task_id}.jsonl"
    evidence_path = PROJECT_ROOT / "outputs" / "evidence" / f"{task_id}.jsonl"
    return {
        "task_id": task_id,
        "question": question,
        "answer": result.answer,
        "verification": result.verification or {},
        "evidence": result.evidence,
        "history": result.history,
        "trajectory": _read_jsonl(trajectory_path),
        "evidence_path": str(evidence_path.relative_to(PROJECT_ROOT)),
        "trajectory_path": str(trajectory_path.relative_to(PROJECT_ROOT)),
    }


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _load_reports() -> list[dict[str, object]]:
    report_specs = [
        ("baseline", PROJECT_ROOT / "outputs" / "eval_results" / "p1_compare_check_comparison.md"),
        ("difficulty", PROJECT_ROOT / "outputs" / "eval_results" / "p2_difficulty_check_difficulty_calibration.md"),
        ("human_scoring", PROJECT_ROOT / "outputs" / "eval_results" / "p2_human_scoring_check_human_scoring.md"),
    ]
    reports: list[dict[str, object]] = []
    for report_type, path in report_specs:
        reports.append(
            {
                "type": report_type,
                "path": str(path.relative_to(PROJECT_ROOT)),
                "exists": path.exists(),
                "content": path.read_text(encoding="utf-8", errors="replace") if path.exists() else "",
            }
        )
    return reports


def _safe_task_id(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in value.strip())
    return cleaned[:80] or "ui_demo_task"


def _content_type(suffix: str) -> str:
    return {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".json": "application/json; charset=utf-8",
    }.get(suffix.lower(), "application/octet-stream")


if __name__ == "__main__":
    os.chdir(PROJECT_ROOT)
    raise SystemExit(main())
