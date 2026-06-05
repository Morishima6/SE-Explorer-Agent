import json
import os
from pathlib import Path

from agent.llm_client import LLMClient, MockLLMClient
from agent.loop import AgentLoop
from agent.trajectory import TrajectoryLogger
from demo.app import _load_project_env, _validate_real_llm_env, build_registry


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VALID_MOCK_SCENARIOS = {"docs", "code", "fix", "test", "multimodal", "edit"}
TEXT_EXTENSIONS = {
    ".c",
    ".cpp",
    ".cs",
    ".css",
    ".go",
    ".h",
    ".html",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".properties",
    ".py",
    ".rs",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
SKIP_DIRS = {
    ".cache",
    ".git",
    ".idea",
    ".vscode",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "outputs",
    "target",
    "venv",
}
MAX_TEXT_FILE_BYTES = 512 * 1024
MAX_INDEXED_PROJECT_FILES = 800
MAX_RETURNED_TEXT_CHARS = 30000

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


def get_examples() -> list[dict[str, object]]:
    print(f"[backend_services] get examples count={len(EXAMPLES)}")
    return EXAMPLES


def get_tools() -> list[dict[str, object]]:
    tools = [
        {"name": tool.name, "description": tool.description}
        for tool in build_registry().list_tools()
    ]
    print(f"[backend_services] get tools count={len(tools)}")
    return tools


def select_project_root() -> dict[str, object]:
    test_root = os.environ.get("SE_EXPLORER_TEST_PROJECT_ROOT")
    if test_root:
        selected = Path(test_root).resolve()
        print(f"[backend_services] select project root from test env path={selected}")
        if not selected.exists() or not selected.is_dir():
            raise ValueError(f"project root not found: {selected}")
        return _build_project_root_response(selected)

    print("[backend_services] open local project directory dialog")
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected_path = filedialog.askdirectory(title="Select project directory")
    finally:
        root.destroy()

    if not selected_path:
        raise ValueError("project directory selection cancelled")

    selected = Path(selected_path).resolve()
    if not selected.exists() or not selected.is_dir():
        raise ValueError(f"project root not found: {selected}")
    print(f"[backend_services] selected project root path={selected}")
    return _build_project_root_response(selected)


def _build_project_root_response(root: Path) -> dict[str, object]:
    files = _index_project_files(root)
    print(f"[backend_services] indexed selected project root files={len(files)}")
    return {
        "project_root": str(root),
        "project_name": root.name,
        "files": files,
        "indexed_file_count": len(files),
    }


def _index_project_files(root: Path) -> list[dict[str, object]]:
    indexed: list[dict[str, object]] = []
    for path in root.rglob("*"):
        if len(indexed) >= MAX_INDEXED_PROJECT_FILES:
            break
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if _should_skip_relative_path(relative):
            continue
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        size = path.stat().st_size
        if size > MAX_TEXT_FILE_BYTES:
            continue
        normalized = relative.as_posix()
        indexed.append(
            {
                "path": normalized,
                "name": path.name,
                "ext": path.suffix.lower(),
                "size": size,
                "text": path.read_text(encoding="utf-8", errors="replace")[:MAX_RETURNED_TEXT_CHARS],
            }
        )
    indexed.sort(key=lambda item: str(item["path"]))
    return indexed


def _should_skip_relative_path(path: Path) -> bool:
    parts = path.parts
    if any(part in SKIP_DIRS for part in parts):
        return True
    return any(part.startswith(".") and part != ".env.example" for part in parts)


def run_agent_from_payload(payload: dict[str, object]) -> dict[str, object]:
    normalized = normalize_ask_payload(payload)
    question = str(normalized["question"])
    task_id = str(normalized["task_id"])
    mock = bool(normalized["mock"])
    scenario = str(normalized["mock_scenario"])
    max_steps = int(normalized["max_steps"])
    model = normalized.get("model")

    print(
        "[backend_services] run ask "
        f"task_id={task_id}, mock={mock}, scenario={scenario}, max_steps={max_steps}"
    )
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
        "trajectory": read_jsonl(trajectory_path),
        "evidence_path": str(evidence_path.relative_to(PROJECT_ROOT)),
        "trajectory_path": str(trajectory_path.relative_to(PROJECT_ROOT)),
    }


def normalize_ask_payload(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")

    question = str(payload.get("question") or "software architecture").strip()
    task_id = safe_task_id(str(payload.get("task_id") or "ui_demo_task"))
    mock = parse_bool(payload.get("mock", True), "mock")
    scenario = str(payload.get("mock_scenario") or "docs").strip()
    max_steps = parse_max_steps(payload.get("max_steps", 10))
    model_value = payload.get("model")
    model = str(model_value).strip() if model_value else None

    if scenario not in VALID_MOCK_SCENARIOS:
        allowed = ", ".join(sorted(VALID_MOCK_SCENARIOS))
        raise ValueError(f"mock_scenario must be one of: {allowed}")

    return {
        "question": question or "software architecture",
        "task_id": task_id,
        "mock": mock,
        "mock_scenario": scenario,
        "max_steps": max_steps,
        "model": model,
    }


def parse_bool(value: object, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    if value in {0, 1}:
        return bool(value)
    raise ValueError(f"{field_name} must be boolean")


def parse_max_steps(value: object) -> int:
    try:
        max_steps = int(value or 10)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_steps must be an integer") from exc
    if not 1 <= max_steps <= 50:
        raise ValueError("max_steps must be between 1 and 50")
    return max_steps


def read_evidence(task_id: str) -> dict[str, object]:
    cleaned_task_id = safe_task_id(task_id)
    print(f"[backend_services] read evidence task_id={cleaned_task_id}")
    path = PROJECT_ROOT / "outputs" / "evidence" / f"{cleaned_task_id}.jsonl"
    return {"task_id": cleaned_task_id, "evidence": read_jsonl(path)}


def read_trajectory(task_id: str) -> dict[str, object]:
    cleaned_task_id = safe_task_id(task_id)
    print(f"[backend_services] read trajectory task_id={cleaned_task_id}")
    path = PROJECT_ROOT / "outputs" / "trajectories" / f"{cleaned_task_id}.jsonl"
    return {"task_id": cleaned_task_id, "trajectory": read_jsonl(path)}


def read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def load_reports() -> list[dict[str, object]]:
    report_specs = [
        ("baseline", PROJECT_ROOT / "outputs" / "eval_results" / "p1_compare_check_comparison.md"),
        ("difficulty", PROJECT_ROOT / "outputs" / "eval_results" / "p2_difficulty_check_difficulty_calibration.md"),
        ("human_scoring", PROJECT_ROOT / "outputs" / "eval_results" / "p2_human_scoring_check_human_scoring.md"),
        ("real_baseline_sample", PROJECT_ROOT / "outputs" / "eval_results" / "p3_real_baseline_sample_check_real_baseline_sample.md"),
        ("hybrid_rag_eval", PROJECT_ROOT / "outputs" / "eval_results" / "p3_hybrid_rag_eval_check_hybrid_rag_eval.md"),
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
    print(f"[backend_services] load reports count={len(reports)}")
    return reports


def safe_task_id(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in value.strip())
    return cleaned[:80] or "ui_demo_task"
