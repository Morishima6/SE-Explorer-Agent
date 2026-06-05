import math
import re
from pathlib import Path
from typing import Any

from rag.bm25 import BM25Scorer
from rag.rag_anything_loader import RAGAnythingLoader


RAW_TEXT_EXTENSIONS = {".md", ".txt", ".html", ".htm"}
STRUCTURED_BLOCK_TYPES = {"text", "table", "figure", "image"}


class HybridRetriever:
    """Deterministic hybrid retrieval over RAG-Anything parsed artifacts.

    当前版本不引入 embedding / LLM rerank，避免模型下载和 API 波动；它把
    RAG-Anything parsed markdown、content_list block 和 raw text fallback 合并后
    用关键词、覆盖率、短语、元数据、来源和 BM25-lite 做稳定 rerank。
    """

    def __init__(self, docs_path: str = "books", loader: RAGAnythingLoader | None = None) -> None:
        self.docs_path = docs_path
        self.loader = loader or RAGAnythingLoader()

    def search(self, query: str, top_k: int = 5) -> list[dict[str, object]]:
        print(f"[hybrid_retriever] search query={query}, top_k={top_k}")
        query_terms = _query_terms(query)
        if not query_terms:
            return []

        candidate_limit = max(top_k * 4, 12)
        candidates: list[dict[str, Any]] = []
        candidates.extend(
            self._tag_candidates(
                self.loader.search_parsed_outputs(query=query, top_k=candidate_limit),
                "rag_anything_parsed",
            )
        )
        candidates.extend(
            self._tag_candidates(
                self.loader.search_parsed_blocks(
                    query=query,
                    block_types=STRUCTURED_BLOCK_TYPES,
                    top_k=candidate_limit,
                ),
                "rag_anything_block",
            )
        )
        candidates.extend(self._raw_search(query=query, query_terms=query_terms, top_k=candidate_limit))

        merged = self._dedupe(candidates)
        bm25_scorer = BM25Scorer([str(item.get("snippet", "")) for item in merged])
        reranked = [
            self._rerank_candidate(
                item=item,
                query=query,
                query_terms=query_terms,
                bm25_score=bm25_scorer.score(query, index),
            )
            for index, item in enumerate(merged)
        ]
        reranked.sort(key=_rank_key)
        return reranked[:top_k]

    def _tag_candidates(self, rows: list[dict[str, Any]], source_name: str) -> list[dict[str, Any]]:
        tagged: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            metadata = dict(item.get("metadata", {})) if isinstance(item.get("metadata"), dict) else {}
            sources = list(metadata.get("candidate_sources", [])) if isinstance(metadata.get("candidate_sources"), list) else []
            if source_name not in sources:
                sources.append(source_name)
            metadata["candidate_sources"] = sources
            item["metadata"] = metadata
            tagged.append(item)
        return tagged

    def _raw_search(self, query: str, query_terms: list[str], top_k: int) -> list[dict[str, Any]]:
        print(f"[hybrid_retriever] raw fallback scan path={self.docs_path}")
        results: list[dict[str, Any]] = []
        for file_path in Path(self.docs_path).rglob("*"):
            if not file_path.is_file() or file_path.suffix.lower() not in RAW_TEXT_EXTENSIONS:
                continue
            text = file_path.read_text(encoding="utf-8", errors="replace")
            lowered = text.lower()
            score = sum(lowered.count(term) for term in query_terms)
            if score <= 0:
                continue
            positions = [lowered.find(term) for term in query_terms if lowered.find(term) >= 0]
            position = min(positions) if positions else 0
            snippet = text[max(0, position - 180) : position + 520].replace("\n", " ")
            results.append(
                {
                    "source": str(file_path),
                    "content_type": file_path.suffix.lower().lstrip("."),
                    "score": score,
                    "snippet": snippet,
                    "metadata": {
                        "source_kind": "raw_text_fallback",
                        "candidate_sources": ["raw_text_fallback"],
                        "original_path": str(file_path),
                    },
                }
            )
        results.sort(key=lambda item: float(item.get("score", 0)), reverse=True)
        return results[:top_k]

    def _dedupe(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_key: dict[str, dict[str, Any]] = {}
        for item in candidates:
            metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
            key = _candidate_key(item, metadata)
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = item
                continue

            existing_metadata = existing.get("metadata", {}) if isinstance(existing.get("metadata"), dict) else {}
            sources = set(existing_metadata.get("candidate_sources", []))
            sources.update(metadata.get("candidate_sources", []))
            existing_metadata["candidate_sources"] = sorted(str(source) for source in sources)
            existing["metadata"] = existing_metadata
            existing["score"] = max(float(existing.get("score", 0)), float(item.get("score", 0)))
            if len(str(item.get("snippet", ""))) > len(str(existing.get("snippet", ""))):
                existing["snippet"] = item.get("snippet", "")
        return list(by_key.values())

    def _rerank_candidate(
        self,
        item: dict[str, Any],
        query: str,
        query_terms: list[str],
        bm25_score: float,
    ) -> dict[str, Any]:
        snippet = str(item.get("snippet", ""))
        metadata = dict(item.get("metadata", {})) if isinstance(item.get("metadata"), dict) else {}
        base_score = float(item.get("score", 0))
        keyword_score = _keyword_score(snippet, query_terms)
        coverage_score = _coverage_score(snippet, query_terms)
        phrase_score = _phrase_score(snippet, query)
        metadata_score = _metadata_score(metadata)
        source_score = _source_score(metadata)
        normalized_base_score = math.log1p(base_score)
        final_score = (
            normalized_base_score
            + keyword_score * 2.0
            + coverage_score * 6.0
            + phrase_score * 4.0
            + bm25_score * 1.5
            + metadata_score
            + source_score
        )
        score_parts = {
            "base_score": round(base_score, 4),
            "normalized_base_score": round(normalized_base_score, 4),
            "keyword_score": round(keyword_score, 4),
            "coverage_score": round(coverage_score, 4),
            "phrase_score": round(phrase_score, 4),
            "bm25_score": round(bm25_score, 4),
            "metadata_score": round(metadata_score, 4),
            "source_score": round(source_score, 4),
            "final_score": round(final_score, 4),
        }
        metadata["retrieval_strategy"] = "hybrid_rag_anything"
        metadata["score_parts"] = score_parts
        metadata.setdefault("candidate_sources", ["unknown"])

        ranked = dict(item)
        ranked["score"] = round(final_score, 4)
        ranked["metadata"] = metadata
        return ranked


def _query_terms(query: str) -> list[str]:
    terms = [term for term in re.split(r"\W+", query.lower()) if len(term) >= 2]
    deduped: list[str] = []
    for term in terms:
        if term not in deduped:
            deduped.append(term)
    return deduped


def _keyword_score(snippet: str, query_terms: list[str]) -> float:
    lowered = snippet.lower()
    return sum(math.log1p(lowered.count(term)) for term in query_terms)


def _coverage_score(snippet: str, query_terms: list[str]) -> float:
    if not query_terms:
        return 0.0
    lowered = snippet.lower()
    matched = sum(1 for term in query_terms if term in lowered)
    return matched / len(query_terms)


def _phrase_score(snippet: str, query: str) -> float:
    normalized_query = " ".join(query.lower().split())
    if not normalized_query:
        return 0.0
    normalized_snippet = " ".join(snippet.lower().split())
    return 1.0 if normalized_query in normalized_snippet else 0.0


def _metadata_score(metadata: dict[str, Any]) -> float:
    score = 0.0
    if metadata.get("doc_id"):
        score += 1.0
    if metadata.get("page") is not None or metadata.get("page_idx") is not None:
        score += 0.5
    block_type = str(metadata.get("block_type", "")).lower()
    if block_type in {"text", "md", "markdown"}:
        score += 0.6
    elif block_type in {"table", "figure", "image"}:
        score += 0.4
    return score


def _source_score(metadata: dict[str, Any]) -> float:
    sources = metadata.get("candidate_sources", [])
    if not isinstance(sources, list):
        sources = []
    source_set = {str(source) for source in sources}
    score = 0.0
    if "rag_anything_parsed" in source_set:
        score += 5.0
    if "rag_anything_block" in source_set:
        score += 3.0
    if "raw_text_fallback" in source_set:
        score += 0.3
    if len(source_set) >= 2:
        score += 1.0
    return score


def _candidate_key(item: dict[str, Any], metadata: dict[str, Any]) -> str:
    doc_id = str(metadata.get("doc_id") or "")
    block_index = metadata.get("block_index")
    parsed_path = str(metadata.get("parsed_path") or "")
    source = str(metadata.get("original_path") or item.get("source") or "")
    snippet = " ".join(str(item.get("snippet", "")).lower().split())[:180]
    if doc_id and block_index is not None:
        return f"{doc_id}:block:{block_index}"
    if parsed_path:
        return f"parsed:{parsed_path}:{snippet}"
    return f"source:{source}:{snippet}"


def _rank_key(item: dict[str, Any]) -> tuple[float, float, str]:
    metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
    score_parts = metadata.get("score_parts", {}) if isinstance(metadata.get("score_parts"), dict) else {}
    coverage = float(score_parts.get("coverage_score", 0))
    source = str(item.get("source", ""))
    return (-float(item.get("score", 0)), -coverage, source)
