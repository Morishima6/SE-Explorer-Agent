from tools.grep_code import grep_code


def search_code(query: str, path: str = ".", top_k: int = 10) -> list[dict[str, object]]:
    print(f"[search_code] query={query}, path={path}, top_k={top_k}")
    return grep_code(query, path=path, max_results=top_k)

