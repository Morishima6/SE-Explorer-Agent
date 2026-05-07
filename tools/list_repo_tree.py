from pathlib import Path


def list_repo_tree(path: str = ".", max_depth: int = 2) -> list[str]:
    root = Path(path)
    print(f"[list_repo_tree] path={root}, max_depth={max_depth}")
    rows: list[str] = []

    for item in sorted(root.rglob("*")):
        relative = item.relative_to(root)
        if len(relative.parts) > max_depth:
            continue
        rows.append(str(relative) + ("/" if item.is_dir() else ""))

    return rows

