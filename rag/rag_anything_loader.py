import json
import re
import shutil
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from rag.rag_anything_config import (
    RAGAnythingProjectConfig,
    ensure_raganything_import_path,
)


FALLBACK_SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".tiff",
    ".tif",
    ".gif",
    ".webp",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".txt",
    ".md",
    ".html",
    ".htm",
}


@dataclass
class DocumentTask:
    doc_id: str
    path: str
    extension: str
    size_bytes: int
    status: str = "pending"


@dataclass
class StagedDocumentTask:
    doc_id: str
    original_path: str
    staged_path: str
    extension: str
    size_bytes: int


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"[rag_anything_loader] write {len(records)} records to {path}")


class RAGAnythingLoader:
    def __init__(self, config: RAGAnythingProjectConfig | None = None) -> None:
        self.config = config or RAGAnythingProjectConfig.from_env()
        self.config.apply_environment()
        ensure_raganything_import_path()

    def get_supported_extensions(self) -> set[str]:
        try:
            from raganything.batch_parser import BatchParser

            batch_parser = BatchParser(
                parser_type=self.config.parser,
                max_workers=self.config.max_workers,
                show_progress=False,
                timeout_per_file=self.config.timeout_per_file,
                skip_installation_check=True,
            )
            extensions = set(batch_parser.get_supported_extensions())
            extensions.update({".html", ".htm"})
            print(f"[rag_anything_loader] supported extensions from RAG-Anything: {sorted(extensions)}")
            return extensions
        except Exception as exc:
            print(f"[rag_anything_loader] use fallback supported extensions: {exc}")
            return FALLBACK_SUPPORTED_EXTENSIONS

    def scan_documents(self, limit: int | None = None) -> list[DocumentTask]:
        supported_extensions = self.get_supported_extensions()
        books_path = self.config.books_path
        print(f"[rag_anything_loader] scan books path: {books_path}")

        tasks: list[DocumentTask] = []
        for index, file_path in enumerate(sorted(books_path.rglob("*")), start=1):
            if not file_path.is_file():
                continue
            extension = file_path.suffix.lower()
            if extension not in supported_extensions:
                continue
            tasks.append(
                DocumentTask(
                    doc_id=f"doc_{len(tasks) + 1:06d}",
                    path=str(file_path),
                    extension=extension,
                    size_bytes=file_path.stat().st_size,
                )
            )
            if limit is not None and len(tasks) >= limit:
                break

        print(f"[rag_anything_loader] scanned supported files: {len(tasks)}")
        return tasks

    def dry_run(self, limit: int | None = None) -> dict[str, Any]:
        tasks = self.scan_documents(limit=limit)
        manifest_path = self.config.parse_log_path / "raganything_manifest.jsonl"
        _write_jsonl(manifest_path, [asdict(task) for task in tasks])
        return {
            "total_files": len(tasks),
            "manifest_path": str(manifest_path),
            "files": [asdict(task) for task in tasks],
        }

    def check_installation(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "raganything_imported": False,
            "parser": self.config.parser,
            "parser_installed": False,
            "error": None,
        }
        try:
            from raganything import RAGAnything, RAGAnythingConfig

            result["raganything_imported"] = True
            rag_config = RAGAnythingConfig(
                working_dir=str(self.config.working_path),
                parser_output_dir=str(self.config.parser_output_path),
                parser=self.config.parser,
                parse_method=self.config.parse_method,
            )
            rag = RAGAnything(config=rag_config)
            result["parser_installed"] = bool(rag.check_parser_installation())
        except Exception as exc:
            result["error"] = str(exc)

        print(f"[rag_anything_loader] check installation: {result}")
        return result

    def stage_documents(self, tasks: list[DocumentTask]) -> list[StagedDocumentTask]:
        if not self.config.use_staging:
            return [
                StagedDocumentTask(
                    doc_id=task.doc_id,
                    original_path=task.path,
                    staged_path=task.path,
                    extension=task.extension,
                    size_bytes=task.size_bytes,
                )
                for task in tasks
            ]

        staged_tasks: list[StagedDocumentTask] = []
        for task in tasks:
            source = Path(task.path)
            staged_path = self.config.staging_path / f"{task.doc_id}{task.extension}"
            shutil.copy2(source, staged_path)
            print(f"[rag_anything_loader] staged {source.name} -> {staged_path.name}")
            staged_tasks.append(
                StagedDocumentTask(
                    doc_id=task.doc_id,
                    original_path=task.path,
                    staged_path=str(staged_path),
                    extension=task.extension,
                    size_bytes=task.size_bytes,
                )
            )
        return staged_tasks

    def process(self, limit: int | None = None, dry_run: bool = False) -> dict[str, Any]:
        tasks = self.scan_documents(limit=limit)
        staged_tasks = self.stage_documents(tasks)
        file_paths = [task.staged_path for task in staged_tasks]
        manifest_path = self.config.parse_log_path / "raganything_manifest.jsonl"
        _write_jsonl(manifest_path, [asdict(task) for task in tasks])
        staged_manifest_path = self.config.parse_log_path / "raganything_staged_manifest.jsonl"
        _write_jsonl(staged_manifest_path, [asdict(task) for task in staged_tasks])

        if dry_run:
            print("[rag_anything_loader] dry run enabled, skip parser execution")
            return {
                "dry_run": True,
                "total_files": len(tasks),
                "successful_files": file_paths,
                "failed_files": [],
                "errors": {},
                "output_dir": str(self.config.parser_output_path),
                "manifest_path": str(manifest_path),
                "staged_manifest_path": str(staged_manifest_path),
            }

        if self.config.enable_text_fallback and staged_tasks and all(
            task.extension in {".md", ".txt"} for task in staged_tasks
        ):
            fallback_files = self._apply_text_fallbacks(staged_tasks, file_paths)
            summary = {
                "dry_run": False,
                "total_files": len(staged_tasks),
                "successful_files": fallback_files,
                "failed_files": [],
                "errors": {},
                "fallback_files": fallback_files,
                "processing_time": 0.0,
                "output_dir": str(self.config.parser_output_path),
                "manifest_path": str(manifest_path),
                "staged_manifest_path": str(staged_manifest_path),
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
            summary_path = self.config.parse_log_path / "raganything_last_run.json"
            summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[rag_anything_loader] write parse summary to {summary_path}")
            return summary

        from raganything.batch_parser import BatchParser

        print(f"[rag_anything_loader] start RAG-Anything batch parse, total={len(file_paths)}")
        start_time = time.time()
        batch_parser = BatchParser(
            parser_type=self.config.parser,
            max_workers=self.config.max_workers,
            show_progress=True,
            timeout_per_file=self.config.timeout_per_file,
            skip_installation_check=self.config.skip_installation_check,
        )
        result = batch_parser.process_batch(
            file_paths=file_paths,
            output_dir=str(self.config.parser_output_path),
            parse_method=self.config.parse_method,
            recursive=False,
            dry_run=False,
            timeout=self.config.mineru_timeout,
            start_page=self.config.start_page,
            end_page=self.config.end_page,
            backend=self.config.backend,
            device=self.config.device,
        )
        elapsed = time.time() - start_time
        fallback_files: list[str] = []
        failed_files = list(result.failed_files)
        errors = dict(result.errors)
        successful_files = list(result.successful_files)
        if self.config.enable_text_fallback and failed_files:
            fallback_files = self._apply_text_fallbacks(staged_tasks, failed_files)
            if fallback_files:
                fallback_set = set(fallback_files)
                failed_files = [item for item in failed_files if item not in fallback_set]
                errors = {key: value for key, value in errors.items() if key not in fallback_set}
                successful_files.extend(item for item in fallback_files if item not in successful_files)

        summary = {
            "dry_run": False,
            "total_files": result.total_files,
            "successful_files": successful_files,
            "failed_files": failed_files,
            "errors": errors,
            "fallback_files": fallback_files,
            "processing_time": elapsed,
            "output_dir": result.output_dir,
            "manifest_path": str(manifest_path),
            "staged_manifest_path": str(staged_manifest_path),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        summary_path = self.config.parse_log_path / "raganything_last_run.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[rag_anything_loader] write parse summary to {summary_path}")
        return summary

    def _apply_text_fallbacks(
        self,
        staged_tasks: list[StagedDocumentTask],
        failed_files: list[str],
    ) -> list[str]:
        failed_set = {str(Path(item)) for item in failed_files}
        fallback_files: list[str] = []
        for task in staged_tasks:
            staged_path = Path(task.staged_path)
            if str(staged_path) not in failed_set or task.extension not in {".md", ".txt"}:
                continue
            text = staged_path.read_text(encoding="utf-8", errors="replace")
            output_dir = self.config.parser_output_path / task.doc_id
            output_dir.mkdir(parents=True, exist_ok=True)
            parsed_md = output_dir / f"{task.doc_id}.md"
            content_list_path = output_dir / f"{task.doc_id}_content_list.json"
            parsed_md.write_text(text, encoding="utf-8")
            content_list = [
                {
                    "type": "text",
                    "text": text,
                    "page_idx": 0,
                    "fallback_parser": "text",
                    "original_path": task.original_path,
                }
            ]
            content_list_path.write_text(json.dumps(content_list, ensure_ascii=False, indent=2), encoding="utf-8")
            fallback_files.append(str(staged_path))
            print(f"[rag_anything_loader] text fallback parsed {staged_path} -> {output_dir}")
        return fallback_files

    def get_document_metadata_lookup(self) -> dict[str, dict[str, Any]]:
        return self._build_doc_lookup()

    def search_parsed_outputs(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        print(f"[rag_anything_loader] search parsed outputs query={query}, top_k={top_k}")
        query_terms = [term for term in re.split(r"\W+", query.lower()) if term]
        if not query_terms:
            return []

        doc_lookup = self._build_doc_lookup()
        candidates: list[dict[str, Any]] = []
        for file_path in self.config.parser_output_path.rglob("*"):
            if not file_path.is_file() or file_path.suffix.lower() not in {".md", ".json", ".txt"}:
                continue
            if file_path.name.endswith("_content_list.json"):
                candidates.extend(self._search_content_list(file_path, query_terms, doc_lookup))
                continue
            if file_path.suffix.lower() == ".json":
                continue
            text = file_path.read_text(encoding="utf-8", errors="replace")
            lowered = text.lower()
            score = sum(lowered.count(term) for term in query_terms)
            if score <= 0:
                continue
            first_positions = [lowered.find(term) for term in query_terms if lowered.find(term) >= 0]
            position = min(first_positions) if first_positions else 0
            snippet = text[max(0, position - 220) : position + 520].replace("\n", " ")
            metadata = self._build_result_metadata(file_path=file_path, doc_lookup=doc_lookup)
            candidates.append(
                {
                    "source": metadata.get("original_path") or str(file_path),
                    "content_type": metadata.get("block_type") or file_path.suffix.lower().lstrip("."),
                    "score": score,
                    "snippet": snippet,
                    "metadata": metadata,
                }
            )

        candidates.sort(key=lambda item: self._rank_search_result(item), reverse=True)
        return candidates[:top_k]

    def search_parsed_blocks(
        self,
        query: str,
        block_types: set[str],
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        print(
            "[rag_anything_loader] search parsed blocks "
            f"query={query}, block_types={sorted(block_types)}, top_k={top_k}"
        )
        normalized_types = {item.lower() for item in block_types}
        query_terms = [term for term in re.split(r"\W+", query.lower()) if term]
        if not normalized_types:
            return []

        doc_lookup = self._build_doc_lookup()
        candidates: list[dict[str, Any]] = []
        for file_path in self.config.parser_output_path.rglob("*_content_list.json"):
            if not file_path.is_file():
                continue
            candidates.extend(
                self._search_content_list(
                    file_path=file_path,
                    query_terms=query_terms,
                    doc_lookup=doc_lookup,
                    block_types=normalized_types,
                    allow_empty_query=True,
                )
            )

        candidates.sort(key=lambda item: self._rank_search_result(item), reverse=True)
        return candidates[:top_k]

    def _rank_search_result(self, item: dict[str, Any]) -> float:
        metadata = item.get("metadata", {})
        source = str(metadata.get("parsed_path") if isinstance(metadata, dict) else item.get("source", "")).lower()
        score = float(item.get("score", 0))
        if isinstance(metadata, dict) and metadata.get("source_kind") == "rag_anything_block":
            score += 4
        if source.endswith(".md"):
            score += 3
        elif "content_list" in source:
            score += 1
        return score

    def _search_content_list(
        self,
        file_path: Path,
        query_terms: list[str],
        doc_lookup: dict[str, dict[str, Any]],
        block_types: set[str] | None = None,
        allow_empty_query: bool = False,
    ) -> list[dict[str, Any]]:
        try:
            blocks = json.loads(file_path.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            print(f"[rag_anything_loader] skip invalid content_list {file_path}: {exc}")
            return []
        if not isinstance(blocks, list):
            return []

        candidates: list[dict[str, Any]] = []
        for index, block in enumerate(blocks):
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type", "block")).lower()
            if block_types is not None and block_type not in block_types:
                continue
            text = self._block_text(block)
            lowered = text.lower()
            score = sum(lowered.count(term) for term in query_terms)
            if score <= 0 and not allow_empty_query:
                continue
            if score <= 0:
                score = 0.1
            snippet = text[:740].replace("\n", " ")
            if not snippet:
                snippet = f"{block_type} block at index {index}"
            metadata = self._build_result_metadata(
                file_path=file_path,
                doc_lookup=doc_lookup,
                block=block,
                block_index=index,
            )
            candidates.append(
                {
                    "source": metadata.get("original_path") or str(file_path),
                    "content_type": str(metadata.get("block_type") or "block"),
                    "score": score,
                    "snippet": snippet,
                    "metadata": metadata,
                }
            )
        return candidates

    def _block_text(self, block: dict[str, Any]) -> str:
        parts: list[str] = []
        for key in [
            "text",
            "table_body",
            "table_caption",
            "table_footnote",
            "image_caption",
            "image_footnote",
            "img_path",
        ]:
            value = block.get(key)
            if isinstance(value, list):
                parts.extend(str(item) for item in value)
            elif value is not None:
                parts.append(str(value))
        return " ".join(item for item in parts if item).strip()

    def _build_result_metadata(
        self,
        file_path: Path,
        doc_lookup: dict[str, dict[str, Any]],
        block: dict[str, Any] | None = None,
        block_index: int | None = None,
    ) -> dict[str, Any]:
        doc_id = self._infer_doc_id_from_path(file_path)
        doc_info = doc_lookup.get(doc_id or "", {})
        metadata: dict[str, Any] = {
            "source_kind": "rag_anything_block" if block is not None else "rag_anything_parsed",
            "doc_id": doc_id,
            "original_path": doc_info.get("original_path") or doc_info.get("path"),
            "staged_path": doc_info.get("staged_path"),
            "original_extension": doc_info.get("extension"),
            "parsed_path": str(file_path),
            "parser": self.config.parser,
            "parse_method": self.config.parse_method,
            "parse_log_dir": str(self.config.parse_log_path),
        }
        if block is not None:
            page_idx = block.get("page_idx")
            metadata.update(
                {
                    "block_index": block_index,
                    "block_type": str(block.get("type", "block")),
                    "page_idx": page_idx,
                    "page": int(page_idx) + 1 if isinstance(page_idx, int) else None,
                    "bbox": block.get("bbox"),
                    "image_path": block.get("img_path"),
                }
            )
        else:
            metadata["block_type"] = file_path.suffix.lower().lstrip(".")
        return metadata

    def _build_doc_lookup(self) -> dict[str, dict[str, Any]]:
        lookup: dict[str, dict[str, Any]] = {}
        for record in self._read_jsonl(self.config.parse_log_path / "raganything_manifest.jsonl"):
            doc_id = str(record.get("doc_id", ""))
            if doc_id:
                lookup.setdefault(doc_id, {}).update(record)
        for record in self._read_jsonl(self.config.parse_log_path / "raganything_staged_manifest.jsonl"):
            doc_id = str(record.get("doc_id", ""))
            if doc_id:
                lookup.setdefault(doc_id, {}).update(record)
        print(f"[rag_anything_loader] loaded doc metadata records: {len(lookup)}")
        return lookup

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
        return records

    def _infer_doc_id_from_path(self, file_path: Path) -> str | None:
        for part in file_path.parts:
            if re.fullmatch(r"doc_\d{6}", part):
                return part
        match = re.search(r"(doc_\d{6})", file_path.name)
        return match.group(1) if match else None
