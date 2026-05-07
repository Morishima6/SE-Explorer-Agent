import re
from pathlib import Path


TEXT_EXTENSIONS = {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".html", ".css", ".js", ".ts"}


def grep_code(pattern: str, path: str = ".", max_results: int = 50) -> list[dict[str, object]]:
    print(f"[grep_code] pattern={pattern}, path={path}, max_results={max_results}")
    regex = re.compile(pattern)
    results: list[dict[str, object]] = []

    for file_path in Path(path).rglob("*"):
        if not file_path.is_file() or file_path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line_no, line in enumerate(lines, start=1):
            if regex.search(line):
                results.append({"path": str(file_path), "line": line_no, "text": line.strip()})
                if len(results) >= max_results:
                    return results

    return results

