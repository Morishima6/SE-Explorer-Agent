import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass
class AgentAction:
    tool: str
    args: dict[str, Any]


class ActionParseError(ValueError):
    pass


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return stripped


def parse_action(text: str) -> AgentAction:
    print("[action_parser] parse LLM action")
    payload = _strip_code_fence(text)

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ActionParseError(f"LLM output is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ActionParseError("LLM output must be a JSON object")

    tool = data.get("tool")
    args = data.get("args", {})

    if not isinstance(tool, str) or not tool:
        raise ActionParseError("JSON action must contain a non-empty string field: tool")
    if not isinstance(args, dict):
        raise ActionParseError("JSON action field args must be an object")

    return AgentAction(tool=tool, args=args)

