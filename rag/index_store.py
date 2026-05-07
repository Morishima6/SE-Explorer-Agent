from pathlib import Path


class IndexStore:
    def __init__(self, root: str = "data/indexes") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        print(f"[index_store] root={self.root}")

