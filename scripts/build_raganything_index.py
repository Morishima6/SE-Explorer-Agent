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
    parser = argparse.ArgumentParser(description="Build RAG-Anything parsed document index")
    parser.add_argument("--books-dir", default="books")
    parser.add_argument("--parser", default=None, choices=["mineru", "docling", "paddleocr"])
    parser.add_argument("--parse-method", default="auto", choices=["auto", "ocr", "txt"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--mineru-timeout", type=int, default=600)
    parser.add_argument("--start-page", type=int, default=None)
    parser.add_argument("--end-page", type=int, default=None)
    parser.add_argument("--backend", default=None, help="MinerU backend, default uses SE_MINERU_BACKEND or pipeline")
    parser.add_argument("--device", default=None, help="MinerU device, default uses SE_MINERU_DEVICE or cuda:0")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-staging", action="store_true", help="Pass original file paths to MinerU instead of short staged copies")
    parser.add_argument("--skip-installation-check", action="store_true")
    args = parser.parse_args()

    config = RAGAnythingProjectConfig.from_env()
    config.books_dir = args.books_dir
    if args.parser is not None:
        config.parser = args.parser
    config.parse_method = args.parse_method
    config.max_workers = args.workers
    config.timeout_per_file = args.timeout
    config.mineru_timeout = args.mineru_timeout
    config.start_page = args.start_page
    config.end_page = args.end_page
    if args.backend is not None:
        config.backend = args.backend
    if args.device is not None:
        config.device = args.device
    config.use_staging = not args.no_staging
    config.skip_installation_check = args.skip_installation_check

    loader = RAGAnythingLoader(config)
    result = loader.process(limit=args.limit, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result.get("failed_files") else 1


if __name__ == "__main__":
    raise SystemExit(main())
