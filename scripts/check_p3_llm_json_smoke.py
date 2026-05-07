import argparse
import os
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from agent.action_parser import ActionParseError, parse_action
from agent.evidence_memory import EvidenceMemory
from agent.llm_client import LLMClient
from agent.loop import AgentLoop
from agent.prompts import SYSTEM_PROMPT, build_agent_messages
from agent.trajectory import TrajectoryLogger
from agent.verifier import Verifier
from demo.app import build_registry


class StaticLLMClient:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.index = 0

    def complete(self, messages: list[dict[str, str]]) -> str:
        if self.index >= len(self.outputs):
            return self.outputs[-1]
        output = self.outputs[self.index]
        self.index += 1
        return output


def main() -> int:
    parser = argparse.ArgumentParser(description="P3 real LLM JSON action smoke checks")
    parser.add_argument(
        "--run-real",
        action="store_true",
        help="Call the configured OpenAI-compatible model once. This may consume API quota.",
    )
    parser.add_argument("--model", default=None, help="Override OPENAI_MODEL for --run-real.")
    args = parser.parse_args()

    checks = [
        _check_action_parser_contract(),
        _check_prompt_contract(),
        _check_missing_llm_env_contract(),
        _check_unknown_tool_loop_contract(),
        _check_final_answer_verifier_contract(),
        _check_real_llm_json_action(run_real=args.run_real, model=args.model),
    ]
    passed = all(item[1] for item in checks)
    for name, ok, detail in checks:
        status = "passed" if ok else "failed"
        print(f"[P3 LLM JSON smoke] {name}: {status}")
        if detail:
            print(f"  {detail}")
    print(f"[P3 LLM JSON smoke] overall: {'passed' if passed else 'failed'}")
    return 0 if passed else 1


def _check_action_parser_contract() -> tuple[str, bool, str]:
    raw_json = '{"tool": "search_code", "args": {"query": "LLMClient", "path": "agent", "top_k": 1}}'
    fenced_json = '```json\n{"tool": "list_repo_tree", "args": {"path": ".", "max_depth": 1}}\n```'
    try:
        first = parse_action(raw_json)
        second = parse_action(fenced_json)
    except ActionParseError as exc:
        return "action parser contract", False, str(exc)

    invalid_rejected = False
    try:
        parse_action("not-json")
    except ActionParseError:
        invalid_rejected = True

    ok = (
        first.tool == "search_code"
        and first.args.get("query") == "LLMClient"
        and second.tool == "list_repo_tree"
        and invalid_rejected
    )
    return "action parser contract", ok, "" if ok else f"first={first}, second={second}, invalid={invalid_rejected}"


def _check_prompt_contract() -> tuple[str, bool, str]:
    registry = build_registry()
    messages = build_agent_messages(
        task="请先查看仓库目录结构，然后再回答。",
        registry=registry,
        history=[],
        evidence_memory=EvidenceMemory(),
    )
    prompt_text = "\n".join(message["content"] for message in messages)
    required = [
        "只输出 JSON action",
        '{"tool": "...", "args": {...}}',
        "final_answer 必须直接回答用户问题",
        "引用 Evidence Memory",
        "Output exactly one JSON action.",
    ]
    missing = [item for item in required if item not in prompt_text and item not in SYSTEM_PROMPT]
    known_tools = {"list_repo_tree", "search_docs", "search_code", "view_file", "run_tests", "final_answer"}
    registered_tools = {tool.name for tool in registry.list_tools()}
    ok = not missing and known_tools.issubset(registered_tools)
    detail = "" if ok else f"missing={missing}, registered_tools={sorted(registered_tools)}"
    return "prompt contract", ok, detail


def _check_missing_llm_env_contract() -> tuple[str, bool, str]:
    old_values = {
        "OPENAI_API_KEY": os.environ.pop("OPENAI_API_KEY", None),
        "OPENAI_MODEL": os.environ.pop("OPENAI_MODEL", None),
    }
    try:
        try:
            LLMClient()
        except ValueError as exc:
            message = str(exc)
            ok = "OPENAI_MODEL" in message or "OPENAI_API_KEY" in message
            return "missing LLM env contract", ok, message
        return "missing LLM env contract", False, "LLMClient did not reject missing configuration"
    finally:
        for key, value in old_values.items():
            if value is not None:
                os.environ[key] = value


def _check_unknown_tool_loop_contract() -> tuple[str, bool, str]:
    llm_client = StaticLLMClient(
        [
            '{"tool": "definitely_unknown_tool", "args": {}}',
            '{"tool": "final_answer", "args": {"answer": "unknown tool smoke 已触发 Unknown tool 反馈，并由 Agent Loop 继续进入 final_answer。"}}',
        ]
    )
    agent = AgentLoop(
        registry=build_registry(),
        llm_client=llm_client,
        max_steps=2,
        trajectory_logger=TrajectoryLogger(),
        task_id="p3_llm_unknown_tool_smoke",
    )
    result = agent.run("unknown tool smoke")
    actions = [item["action"] for item in result.history]
    ok = (
        result.verification is not None
        and result.verification.get("passed") is True
        and any(action == "definitely_unknown_tool" for action in actions)
        and "unknown tool smoke" in result.answer
    )
    detail = "" if ok else f"verification={result.verification}, actions={actions}, answer={result.answer}"
    return "unknown tool loop contract", ok, detail


def _check_final_answer_verifier_contract() -> tuple[str, bool, str]:
    memory = EvidenceMemory()
    evidence = memory.add(
        source_type="doc",
        source="docs/smoke.md",
        content="LLM JSON action smoke evidence",
        reason="verifier contract fixture",
    )
    verifier = Verifier()
    missing_ref = verifier.verify_final_answer("LLM JSON action smoke evidence", memory, task="LLM JSON action smoke")
    valid = verifier.verify_final_answer(
        f"LLM JSON action smoke 已有文档证据支撑。[{evidence.evidence_id}]",
        memory,
        task="LLM JSON action smoke",
    )
    ok = missing_ref.passed is False and valid.passed is True
    detail = "" if ok else f"missing_ref={missing_ref.to_dict()}, valid={valid.to_dict()}"
    return "final_answer verifier contract", ok, detail


def _check_real_llm_json_action(run_real: bool, model: str | None) -> tuple[str, bool, str]:
    if not run_real:
        return "real LLM JSON action", True, "skipped; pass --run-real to call the configured model once"

    _load_project_env()
    try:
        llm_client = LLMClient(model=model)
    except ValueError as exc:
        return "real LLM JSON action", False, str(exc)

    registry = build_registry()
    messages = build_agent_messages(
        task=(
            "这是一次 smoke test。请只调用 list_repo_tree 查看仓库根目录，"
            "不要直接 final_answer。"
        ),
        registry=registry,
        history=[],
        evidence_memory=EvidenceMemory(),
    )
    raw = llm_client.complete(messages)
    try:
        action = parse_action(raw)
    except ActionParseError as exc:
        return "real LLM JSON action", False, f"{exc}; raw={_shorten(raw)}"

    ok = action.tool != "final_answer" and registry.has_tool(action.tool)
    detail: dict[str, Any] = {"tool": action.tool, "args": action.args}
    if not ok:
        detail["raw"] = _shorten(raw)
    return "real LLM JSON action", ok, str(detail)


def _load_project_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(env_path)


def _shorten(text: str, max_chars: int = 500) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


if __name__ == "__main__":
    raise SystemExit(main())
