from dataclasses import dataclass, field


@dataclass
class CompressedContext:
    history_summary: str
    recent_steps: list[dict[str, str]] = field(default_factory=list)
    total_steps: int = 0
    compressed_steps: int = 0

    def has_summary(self) -> bool:
        return bool(self.history_summary.strip())


def compress_history(
    history: list[dict[str, str]],
    max_recent_steps: int = 4,
    max_observation_chars: int = 700,
) -> CompressedContext:
    if not history:
        print("[context_manager] compressed history: total=0, recent=0, compressed=0")
        return CompressedContext(history_summary="", recent_steps=[], total_steps=0, compressed_steps=0)

    recent_steps = [_shorten_step(item, max_observation_chars) for item in history[-max_recent_steps:]]
    old_steps = history[:-max_recent_steps] if len(history) > max_recent_steps else []
    summary = _summarize_old_steps(old_steps, max_observation_chars)
    context = CompressedContext(
        history_summary=summary,
        recent_steps=recent_steps,
        total_steps=len(history),
        compressed_steps=len(old_steps),
    )
    print(
        "[context_manager] compressed history: "
        f"total={context.total_steps}, recent={len(context.recent_steps)}, compressed={context.compressed_steps}"
    )
    return context


def format_recent_steps(recent_steps: list[dict[str, str]]) -> str:
    if not recent_steps:
        return "No previous steps."

    rows: list[str] = []
    for item in recent_steps:
        rows.append(
            f"Step {item.get('step', '?')}:\n"
            f"Action: {item.get('action', '')}\n"
            f"Observation: {item.get('observation', '')}"
        )
    return "\n\n".join(rows)


def _summarize_old_steps(old_steps: list[dict[str, str]], max_observation_chars: int) -> str:
    if not old_steps:
        return "No compressed history."

    rows = [f"Compressed {len(old_steps)} earlier step(s):"]
    for item in old_steps:
        observation = _shorten(str(item.get("observation", "")), max_observation_chars // 2)
        rows.append(f"- Step {item.get('step', '?')} action={item.get('action', '')}; observation={observation}")
    return "\n".join(rows)


def _shorten_step(item: dict[str, str], max_observation_chars: int) -> dict[str, str]:
    return {
        "step": str(item.get("step", "")),
        "action": str(item.get("action", "")),
        "observation": _shorten(str(item.get("observation", "")), max_observation_chars),
    }


def _shorten(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."
