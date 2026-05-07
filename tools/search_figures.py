from rag.rag_anything_loader import RAGAnythingLoader


def search_figures(
    query: str,
    path: str = "data/parsed",
    top_k: int = 5,
) -> list[dict[str, object]]:
    print(f"[search_figures] query={query}, path={path}, top_k={top_k}")
    return RAGAnythingLoader().search_parsed_blocks(
        query=query,
        block_types={"figure", "image"},
        top_k=top_k,
    )
