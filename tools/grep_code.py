import re
from pathlib import Path

from tools.project_paths import resolve_project_path, unexpected_args_error


TEXT_EXTENSIONS = {
    ".py",
    ".java",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".css",
    ".html",
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".xml",
    ".properties",
}


def grep_code(
    pattern: str | None = None,
    path: str = ".",
    max_results: int = 50,
    project_root: str | None = None,
    **kwargs: object,
) -> list[dict[str, object]] | dict[str, object]:
    unexpected = unexpected_args_error("grep_code", kwargs, {"pattern", "path", "max_results", "project_root"})
    if unexpected:
        return unexpected

    if not pattern:
        return {"success": False, "tool": "grep_code", "error": "grep_code requires pattern"}

    search_path = resolve_project_path(path, project_root)
    print(f"[grep_code] pattern={pattern}, path={search_path}, project_root={project_root}, max_results={max_results}")
    if not search_path.exists():
        return {"success": False, "tool": "grep_code", "error": f"path not found: {search_path}"}

    regex = re.compile(pattern)
    results: list[dict[str, object]] = []

    for file_path in Path(search_path).rglob("*"):
        if not file_path.is_file() or file_path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line_no, line in enumerate(lines, start=1):
            if regex.search(line):
                results.append({"path": str(file_path), "line": line_no, "text": line.strip()})
                if len(results) >= max_results:
                    return results

    return results
