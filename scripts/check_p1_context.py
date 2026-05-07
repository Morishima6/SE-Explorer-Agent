import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from agent.context_manager import compress_history
from agent.evidence_memory import EvidenceMemory
from agent.prompts import build_agent_messages
from agent.tool_registry import ToolRegistry


def main() -> int:
    checks = [
        _check_history_compression(),
        _check_prompt_sections(),
        _check_evidence_memory_preserved(),
    ]
    passed = all(item[1] for item in checks)
    for name, ok, detail in checks:
        status = "passed" if ok else "failed"
        print(f"[P1 context] {name}: {status}")
        if detail:
            print(f"      {detail}")
    print(f"[P1 context] overall: {'passed' if passed else 'failed'}")
    return 0 if passed else 1


def _check_history_compression() -> tuple[str, bool, str]:
    history = _build_history(6)
    context = compress_history(history, max_recent_steps=2, max_observation_chars=60)

    ok = (
        context.total_steps == 6
        and context.compressed_steps == 4
        and [item["step"] for item in context.recent_steps] == ["5", "6"]
        and "Step 1" in context.history_summary
        and "Step 4" in context.history_summary
        and "Step 5" not in context.history_summary
        and len(context.recent_steps[0]["observation"]) <= 63
    )
    return "history compression", ok, "" if ok else str(context)


def _check_prompt_sections() -> tuple[str, bool, str]:
    history = _build_history(5)
    context = compress_history(history, max_recent_steps=2, max_observation_chars=80)
    registry = ToolRegistry()
    registry.register("final_answer", "return final answer", lambda answer: {"answer": answer})

    messages = build_agent_messages(
        task="explain context compression",
        registry=registry,
        history=history,
        evidence_memory=EvidenceMemory(),
        compressed_context=context,
    )
    prompt = messages[-1]["content"]
    ok = (
        "History Summary:" in prompt
        and "Recent Steps:" in prompt
        and "Evidence Memory:" in prompt
        and "Step 5:" in prompt
        and "Step 1 action=" in prompt
    )
    return "prompt sections", ok, "" if ok else prompt


def _check_evidence_memory_preserved() -> tuple[str, bool, str]:
    history = _build_history(5)
    context = compress_history(history, max_recent_steps=1, max_observation_chars=40)
    memory = EvidenceMemory()
    memory.add("doc", "docs/context.md", "Context compression keeps evidence memory unchanged.", "context test")
    registry = ToolRegistry()
    registry.register("final_answer", "return final answer", lambda answer: {"answer": answer})

    messages = build_agent_messages(
        task="explain context compression",
        registry=registry,
        history=history,
        evidence_memory=memory,
        compressed_context=context,
    )
    prompt = messages[-1]["content"]
    ok = "[ev_001]" in prompt and "Context compression keeps evidence memory unchanged." in prompt
    return "evidence memory preserved", ok, "" if ok else prompt


def _build_history(count: int) -> list[dict[str, str]]:
    return [
        {
            "step": str(index),
            "action": f"tool_{index}({{'query': 'item_{index}'}})",
            "observation": f"observation_{index} " + ("detail " * 30),
        }
        for index in range(1, count + 1)
    ]


if __name__ == "__main__":
    raise SystemExit(main())
