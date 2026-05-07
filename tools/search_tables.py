from rag.rag_anything_loader import RAGAnythingLoader


def search_tables(
    query: str,
    path: str = "data/parsed",
    top_k: int = 5,
) -> list[dict[str, object]]:
    print(f"[search_tables] query={query}, path={path}, top_k={top_k}")
    return RAGAnythingLoader().search_parsed_blocks(
        query=query,
        block_types={"table"},
        top_k=top_k,
    )
