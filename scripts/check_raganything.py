import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rag.rag_anything_config import RAGAnythingProjectConfig
from rag.rag_anything_loader import RAGAnythingLoader


def main() -> int:
    parser = argparse.ArgumentParser(description="Check RAG-Anything availability")
    parser.add_argument("--parser", default=None, choices=["mineru", "docling", "paddleocr"])
    parser.add_argument("--parse-method", default="auto", choices=["auto", "ocr", "txt"])
    args = parser.parse_args()

    config = RAGAnythingProjectConfig.from_env()
    if args.parser is not None:
        config.parser = args.parser
    config.parse_method = args.parse_method
    loader = RAGAnythingLoader(config)
    result = loader.check_installation()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["raganything_imported"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
