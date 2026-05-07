from tools.search_docs import search_docs


class HybridRetriever:
    def __init__(self, docs_path: str = "books") -> None:
        self.docs_path = docs_path

    def search(self, query: str, top_k: int = 5) -> list[dict[str, object]]:
        print(f"[hybrid_retriever] search query={query}, top_k={top_k}")
        return search_docs(query=query, source="all", path=self.docs_path, top_k=top_k)
