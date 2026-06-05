import math
import re
from collections import Counter


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_\u4e00-\u9fff]+")


class BM25Scorer:
    def __init__(self, documents: list[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.document_tokens = [_tokenize(document) for document in documents]
        self.document_count = len(self.document_tokens)
        self.avg_doc_len = _average_length(self.document_tokens)
        self.document_frequencies = _document_frequencies(self.document_tokens)

    def score(self, query: str, document_index: int) -> float:
        if self.document_count == 0 or document_index >= self.document_count:
            return 0.0

        tokens = self.document_tokens[document_index]
        if not tokens:
            return 0.0

        query_terms = _dedupe(_tokenize(query))
        term_counts = Counter(tokens)
        doc_len = len(tokens)
        score = 0.0
        for term in query_terms:
            term_frequency = term_counts.get(term, 0)
            if term_frequency <= 0:
                continue
            idf = self._idf(term)
            denominator = term_frequency + self.k1 * (1 - self.b + self.b * doc_len / self.avg_doc_len)
            score += idf * (term_frequency * (self.k1 + 1)) / denominator
        return score

    def _idf(self, term: str) -> float:
        document_frequency = self.document_frequencies.get(term, 0)
        return math.log(1 + (self.document_count - document_frequency + 0.5) / (document_frequency + 0.5))


def _tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_PATTERN.finditer(text)]


def _dedupe(items: list[str]) -> list[str]:
    deduped: list[str] = []
    for item in items:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _average_length(documents: list[list[str]]) -> float:
    if not documents:
        return 1.0
    total_length = sum(len(document) for document in documents)
    return max(total_length / len(documents), 1.0)


def _document_frequencies(documents: list[list[str]]) -> dict[str, int]:
    frequencies: dict[str, int] = {}
    for document in documents:
        for term in set(document):
            frequencies[term] = frequencies.get(term, 0) + 1
    return frequencies
