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

from demo.backend_services import (
    get_examples,
    get_tools,
    load_reports,
    read_evidence,
    read_trajectory,
    run_agent_from_payload,
    select_project_root,
)


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
            self._send_json({"examples": get_examples()})
            return
        if parsed.path == "/api/tools":
            self._send_json({"tools": get_tools()})
            return
        if parsed.path == "/api/evidence":
            task_id = parse_qs(parsed.query).get("task_id", ["ui_demo_docs"])[0]
            self._send_json(read_evidence(task_id))
            return
        if parsed.path == "/api/trajectory":
            task_id = parse_qs(parsed.query).get("task_id", ["ui_demo_docs"])[0]
            self._send_json(read_trajectory(task_id))
            return
        if parsed.path == "/api/reports":
            self._send_json({"reports": load_reports()})
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/select-project-root":
            try:
                self._send_json(select_project_root())
            except ValueError as exc:
                print(f"[demo_ui] select project root failed: {exc}")
                self._send_error(str(exc), status=400)
            except Exception as exc:
                print(f"[demo_ui] select project root failed: {exc}")
                self._send_error(str(exc), status=500)
            return
        if parsed.path != "/api/ask":
            self._send_error("not found", status=404)
            return
        try:
            payload = self._read_payload()
            response = run_agent_from_payload(payload)
        except json.JSONDecodeError as exc:
            print(f"[demo_ui] invalid json payload: {exc}")
            self._send_error("invalid json payload", status=400)
            return
        except ValueError as exc:
            print(f"[demo_ui] bad request: {exc}")
            self._send_error(str(exc), status=400)
            return
        except Exception as exc:
            print(f"[demo_ui] ask failed: {exc}")
            self._send_error(str(exc), status=500)
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
            self._send_error("invalid static path", status=400)
            return
        if not file_path.exists() or not file_path.is_file():
            self._send_error("not found", status=404)
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

    def _send_error(self, message: str, status: int) -> None:
        self._send_json({"error": message}, status=status)


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
