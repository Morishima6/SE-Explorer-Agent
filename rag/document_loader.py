from pathlib import Path


SUPPORTED_TEXT_EXTENSIONS = {".md", ".txt", ".html"}


def load_text_documents(root: str = "books") -> list[dict[str, str]]:
    print(f"[document_loader] load documents from {root}")
    documents: list[dict[str, str]] = []

    for file_path in Path(root).rglob("*"):
        if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_TEXT_EXTENSIONS:
            documents.append(
                {
                    "path": str(file_path),
                    "text": file_path.read_text(encoding="utf-8", errors="replace"),
                }
            )

    print(f"[document_loader] loaded {len(documents)} text documents")
    return documents

