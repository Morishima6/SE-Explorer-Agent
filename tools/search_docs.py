import re
from pathlib import Path

from rag.rag_anything_loader import RAGAnythingLoader


RAW_TEXT_EXTENSIONS = {".md", ".txt", ".html", ".htm"}


def _fallback_raw_search(query: str, path: str, top_k: int) -> list[dict[str, object]]:
    print(f"[search_docs] fallback raw search path={path}")
    query_terms = [term for term in re.split(r"\W+", query.lower()) if term]
    results: list[dict[str, object]] = []

    for file_path in Path(path).rglob("*"):
        if not file_path.is_file() or file_path.suffix.lower() not in RAW_TEXT_EXTENSIONS:
            continue
        text = file_path.read_text(encoding="utf-8", errors="replace")
        lowered = text.lower()
        score = sum(lowered.count(term) for term in query_terms)
        if score <= 0:
            continue
        positions = [lowered.find(term) for term in query_terms if lowered.find(term) >= 0]
        position = min(positions) if positions else 0
        snippet = text[max(0, position - 160) : position + 420].replace("\n", " ")
        results.append(
            {
                "source": str(file_path),
                "content_type": file_path.suffix.lower().lstrip("."),
                "score": score,
                "snippet": snippet,
                "metadata": {"source": "raw_text_fallback"},
            }
        )

    results.sort(key=lambda item: item["score"], reverse=True)
    return results[:top_k]


def search_docs(
    query: str,
    source: str = "rag_anything",
    path: str = "books",
    top_k: int = 5,
) -> list[dict[str, object]]:
    print(f"[search_docs] query={query}, source={source}, path={path}, top_k={top_k}")

    if source in {"rag_anything", "all"}:
        loader = RAGAnythingLoader()
        parsed_results = loader.search_parsed_outputs(query=query, top_k=top_k)
        if parsed_results or source == "rag_anything":
            return parsed_results

    return _fallback_raw_search(query=query, path=path, top_k=top_k)

