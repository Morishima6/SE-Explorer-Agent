from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Evidence:
    evidence_id: str
    source_type: str
    source: str
    content: str
    reason: str
    line_range: str | None = None
    score: float | int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    used_in_final: bool = False


class EvidenceMemory:
    def __init__(self) -> None:
        self._items: list[Evidence] = []

    def add(
        self,
        source_type: str,
        source: str,
        content: str,
        reason: str,
        line_range: str | None = None,
        score: float | int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Evidence:
        evidence = Evidence(
            evidence_id=f"ev_{len(self._items) + 1:03d}",
            source_type=source_type,
            source=source,
            line_range=line_range,
            content=content,
            reason=reason,
            score=score,
            metadata=metadata or {},
        )
        print(f"[evidence_memory] add evidence: {evidence.evidence_id} from {source}")
        self._items.append(evidence)
        return evidence

    def list(self) -> list[Evidence]:
        return self._items

    def get(self, evidence_id: str) -> Evidence | None:
        for item in self._items:
            if item.evidence_id == evidence_id:
                return item
        return None

    def mark_used(self, evidence_ids: list[str]) -> None:
        used = set(evidence_ids)
        for item in self._items:
            if item.evidence_id in used:
                item.used_in_final = True

    def to_dicts(self) -> list[dict[str, object]]:
        return [asdict(item) for item in self._items]

    def format_for_prompt(self, max_items: int = 6, max_content_chars: int = 500) -> str:
        if not self._items:
            return "No evidence collected yet."

        rows: list[str] = []
        for item in self._items[:max_items]:
            content = item.content
            if len(content) > max_content_chars:
                content = content[:max_content_chars].rstrip() + "..."
            location = item.source
            if item.line_range:
                location = f"{location}:{item.line_range}"
            rows.append(
                f"[{item.evidence_id}] {item.source_type} source={location}\n"
                f"Reason: {item.reason}\n"
                f"Content: {content}"
            )
        return "\n\n".join(rows)

    def save_jsonl(self, task_id: str, output_dir: str = "outputs/evidence") -> Path:
        output_path = Path(output_dir) / f"{task_id}.jsonl"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"[evidence_memory] save evidence to {output_path}")
        with output_path.open("w", encoding="utf-8") as file:
            for item in self.to_dicts():
                file.write(json.dumps(item, ensure_ascii=False) + "\n")
        return output_path

    def reset_jsonl(self, task_id: str, output_dir: str = "outputs/evidence") -> Path:
        output_path = Path(output_dir) / f"{task_id}.jsonl"
        if output_path.exists():
            print(f"[evidence_memory] reset evidence log: {output_path}")
            output_path.unlink()
        return output_path
