from pathlib import Path

from tools.project_paths import resolve_project_path, unexpected_args_error


def list_repo_tree(
    path: str = ".",
    max_depth: int = 2,
    project_root: str | None = None,
    **kwargs: object,
) -> list[str] | dict[str, object]:
    unexpected = unexpected_args_error("list_repo_tree", kwargs, {"path", "max_depth", "project_root"})
    if unexpected:
        return unexpected

    root = resolve_project_path(path, project_root)
    print(f"[list_repo_tree] path={root}, project_root={project_root}, max_depth={max_depth}")
    if not root.exists() or not root.is_dir():
        return {"success": False, "tool": "list_repo_tree", "error": f"directory not found: {root}"}

    rows: list[str] = []

    for item in sorted(root.rglob("*")):
        relative = item.relative_to(root)
        if len(relative.parts) > max_depth:
            continue
        rows.append(str(relative) + ("/" if item.is_dir() else ""))

    return rows
