from pathlib import Path


def resolve_project_path(path: str = ".", project_root: str | None = None) -> Path:
    normalized = str(path or ".").strip()
    if project_root and normalized in {"", ".", "/", "\\"}:
        return Path(project_root)

    raw_path = Path(normalized)
    if raw_path.is_absolute() or not project_root:
        return raw_path
    return Path(project_root) / raw_path


def unexpected_args_error(tool_name: str, kwargs: dict[str, object], allowed: set[str]) -> dict[str, object] | None:
    unexpected = sorted(set(kwargs) - allowed)
    if not unexpected:
        return None
    return {
        "success": False,
        "tool": tool_name,
        "error": f"unexpected args for {tool_name}: {', '.join(unexpected)}; allowed args: {', '.join(sorted(allowed))}",
    }
