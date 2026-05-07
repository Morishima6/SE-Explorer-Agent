def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 150) -> list[str]:
    print(f"[chunker] chunk text length={len(text)}, chunk_size={chunk_size}, overlap={overlap}")
    chunks: list[str] = []
    step = max(chunk_size - overlap, 1)

    for start in range(0, len(text), step):
        chunks.append(text[start : start + chunk_size])

    return chunks

