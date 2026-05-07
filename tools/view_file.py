from pathlib import Path


def view_file(path: str, start: int = 1, end: int = 120) -> dict[str, object]:
    file_path = Path(path)
    print(f"[view_file] path={file_path}, start={start}, end={end}")
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
