from tools.grep_code import grep_code
from tools.project_paths import unexpected_args_error


def search_code(
    query: str,
    path: str = ".",
    top_k: int = 10,
    project_root: str | None = None,
    **kwargs: object,
) -> list[dict[str, object]] | dict[str, object]:
    unexpected = unexpected_args_error("search_code", kwargs, {"query", "path", "top_k", "project_root"})
    if unexpected:
        return unexpected
    print(f"[search_code] query={query}, path={path}, project_root={project_root}, top_k={top_k}")
    return grep_code(query, path=path, project_root=project_root, max_results=top_k)
