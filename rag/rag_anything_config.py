import os
import sys
from dataclasses import dataclass
from pathlib import Path

from rag.cache_config import configure_project_cache, get_project_root


@dataclass
class RAGAnythingProjectConfig:
    books_dir: str = "books"
    working_dir: str = "data/rag_storage"
    parser_output_dir: str = "data/parsed"
    parse_log_dir: str = "outputs/parse_logs"
    staging_dir: str = ".cache/raganything_inputs"
    parser: str = "paddleocr"
    parse_method: str = "auto"
    max_workers: int = 1
    timeout_per_file: int = 600
    mineru_timeout: int = 600
    start_page: int | None = None
    end_page: int | None = None
    backend: str | None = "pipeline"
    device: str | None = "cuda:0"
    recursive: bool = True
    use_staging: bool = True
    skip_installation_check: bool = False
    enable_text_fallback: bool = True
    enable_image_processing: bool = True
    enable_table_processing: bool = True
    enable_equation_processing: bool = True

    @classmethod
    def from_env(cls) -> "RAGAnythingProjectConfig":
        return cls(
            books_dir=os.environ.get("SE_BOOKS_DIR", "books"),
            working_dir=os.environ.get("SE_RAG_WORKING_DIR", "data/rag_storage"),
            parser_output_dir=os.environ.get("SE_RAG_OUTPUT_DIR", "data/parsed"),
            parse_log_dir=os.environ.get("SE_PARSE_LOG_DIR", "outputs/parse_logs"),
            staging_dir=os.environ.get("SE_RAG_STAGING_DIR", ".cache/raganything_inputs"),
            parser=os.environ.get("RAGANYTHING_PARSER", os.environ.get("PARSER", "paddleocr")),
            parse_method=os.environ.get("RAGANYTHING_PARSE_METHOD", os.environ.get("PARSE_METHOD", "auto")),
            max_workers=int(os.environ.get("SE_RAG_MAX_WORKERS", "1")),
            timeout_per_file=int(os.environ.get("SE_RAG_TIMEOUT_PER_FILE", "600")),
            mineru_timeout=int(os.environ.get("SE_MINERU_TIMEOUT", "600")),
            backend=os.environ.get("SE_MINERU_BACKEND", "pipeline"),
            device=os.environ.get("SE_MINERU_DEVICE", "cuda:0"),
        )

    def resolve_path(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return get_project_root() / path

    @property
    def books_path(self) -> Path:
        return self.resolve_path(self.books_dir)

    @property
    def working_path(self) -> Path:
        return self.resolve_path(self.working_dir)

    @property
    def parser_output_path(self) -> Path:
        return self.resolve_path(self.parser_output_dir)

    @property
    def parse_log_path(self) -> Path:
        return self.resolve_path(self.parse_log_dir)

    @property
    def staging_path(self) -> Path:
        return self.resolve_path(self.staging_dir)

    def apply_environment(self) -> None:
        configure_project_cache(get_project_root())
        self.working_path.mkdir(parents=True, exist_ok=True)
        self.parser_output_path.mkdir(parents=True, exist_ok=True)
        self.parse_log_path.mkdir(parents=True, exist_ok=True)
        self.staging_path.mkdir(parents=True, exist_ok=True)

        env_defaults = {
            "WORKING_DIR": str(self.working_path),
            "OUTPUT_DIR": str(self.parser_output_path),
            "PARSER": self.parser,
            "PARSE_METHOD": self.parse_method,
            "MAX_CONCURRENT_FILES": str(self.max_workers),
            "ENABLE_IMAGE_PROCESSING": str(self.enable_image_processing),
            "ENABLE_TABLE_PROCESSING": str(self.enable_table_processing),
            "ENABLE_EQUATION_PROCESSING": str(self.enable_equation_processing),
        }
        for key, value in env_defaults.items():
            os.environ[key] = value

        print(f"[rag_anything_config] books_dir={self.books_path}")
        print(f"[rag_anything_config] parser_output_dir={self.parser_output_path}")
        print(f"[rag_anything_config] staging_dir={self.staging_path}")
        print(f"[rag_anything_config] parser={self.parser}, parse_method={self.parse_method}")
        print(f"[rag_anything_config] mineru_backend={self.backend}, mineru_device={self.device}")


def ensure_raganything_import_path(project_root: Path | None = None) -> Path | None:
    root = project_root or get_project_root()
    local_source = root / "RAG-Anything"
    if local_source.exists() and str(local_source) not in sys.path:
        sys.path.insert(0, str(local_source))
        print(f"[rag_anything_config] add local RAG-Anything path: {local_source}")
    return local_source if local_source.exists() else None


def build_raganything_config(config: RAGAnythingProjectConfig):
    config.apply_environment()
    ensure_raganything_import_path()

    from raganything import RAGAnythingConfig

    return RAGAnythingConfig(
        working_dir=str(config.working_path),
        parser_output_dir=str(config.parser_output_path),
        parser=config.parser,
        parse_method=config.parse_method,
        enable_image_processing=config.enable_image_processing,
        enable_table_processing=config.enable_table_processing,
        enable_equation_processing=config.enable_equation_processing,
        max_concurrent_files=config.max_workers,
    )
