from pathlib import Path

from tools.project_paths import resolve_project_path, unexpected_args_error


def view_file(
    path: str,
    start: int = 1,
    end: int = 120,
    project_root: str | None = None,
    **kwargs: object,
) -> dict[str, object]:
    unexpected = unexpected_args_error("view_file", kwargs, {"path", "start", "end", "project_root"})
    if unexpected:
        return unexpected

    file_path = resolve_project_path(path, project_root)
    print(f"[view_file] path={file_path}, project_root={project_root}, start={start}, end={end}")
    if not file_path.exists() or not file_path.is_file():
        return {"success": False, "tool": "view_file", "error": f"file not found: {file_path}"}

    lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    safe_start = max(start, 1)
    safe_end = min(end, safe_start + 299, len(lines))
    selected = lines[safe_start - 1 : safe_end]
    content = "\n".join(f"{index}: {line}" for index, line in enumerate(selected, start=safe_start))
    return {
        "path": str(file_path),
        "start": safe_start,
        "end": safe_end,
        "line_range": f"{safe_start}-{safe_end}",
        "total_lines": len(lines),
        "content": content,
    }
