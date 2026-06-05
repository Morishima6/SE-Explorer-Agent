import re
from dataclasses import asdict, dataclass, field
from typing import Any

from agent.evidence_memory import EvidenceMemory


EVIDENCE_REF_PATTERN = re.compile(r"\[(ev_\d{3,})\]")
_SEMANTIC_STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "using",
    "uses",
    "used",
    "only",
    "current",
    "answer",
    "evidence",
    "source",
    "sources",
    "final",
    "tool",
    "tools",
    "agent",
    "mock",
    "证据",
    "当前",
    "根据",
    "来自",
    "显示",
    "主题",
    "相关",
    "建议",
    "实现",
    "验证",
    "引用",
    "文件",
    "代码",
    "工具",
}


@dataclass
class VerificationResult:
    passed: bool
    issues: list[str] = field(default_factory=list)
    suggestion: str | None = None
    suggested_next_action: dict[str, object] | None = None
    semantic_checks: list[dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def extract_evidence_refs(text: str) -> list[str]:
    refs: list[str] = []
    for item in EVIDENCE_REF_PATTERN.findall(text):
        if item not in refs:
            refs.append(item)
    return refs


class Verifier:
    def verify_final_answer(
        self,
        answer: str,
        evidence_memory: EvidenceMemory,
        task: str | None = None,
    ) -> VerificationResult:
        print("[verifier] check final_answer")
        issues: list[str] = []
        stripped = answer.strip()

        if not stripped:
            issues.append("final_answer cannot be empty")

        vague_phrases = [
            "请查看上方 observation",
            "请查看上方",
            "见上方",
            "如上",
            "see observation",
            "see above",
            "as above",
        ]
        if any(phrase.lower() in stripped.lower() for phrase in vague_phrases):
            issues.append("final_answer must answer directly instead of pointing to observations")

        evidence_items = evidence_memory.list()
        refs = extract_evidence_refs(stripped)
        if evidence_items and not refs:
            issues.append("final_answer is missing evidence references such as [ev_001]")

        task_provided_ids = set(extract_evidence_refs(task or ""))
        existing_ids = {item.evidence_id for item in evidence_items} | task_provided_ids
        missing_refs = [item for item in refs if item not in existing_ids]
        if missing_refs:
            issues.append(f"final_answer references missing evidence ids: {', '.join(missing_refs)}")

        missing_available_types = _missing_available_evidence_types(evidence_memory, refs)
        if missing_available_types:
            issues.append("final_answer missing available evidence type refs: " + ", ".join(missing_available_types))

        missing_required_types = _missing_required_evidence_types(evidence_memory, refs)
        if missing_required_types:
            issues.append("final_answer missing required P0 evidence type refs: " + ", ".join(missing_required_types))

        if task:
            task_issue = _check_task_coverage(stripped, task)
            if task_issue:
                issues.append(task_issue)

        unsupported_issue = _check_unsupported_claims(stripped, evidence_memory)
        if unsupported_issue:
            issues.append(unsupported_issue)

        speculation_issue = _check_speculation(stripped)
        if speculation_issue:
            issues.append(speculation_issue)

        semantic_issues, semantic_checks = _check_semantic_grounding(stripped, evidence_memory, refs)
        issues.extend(semantic_issues)

        suggestion = None
        suggested_next_action = None
        if issues:
            suggestion = "Rewrite the final answer using Evidence Memory and cite real evidence ids; remove or qualify unsupported claims."
            suggested_next_action = _build_suggested_next_action(issues, evidence_memory, task)

        result = VerificationResult(
            passed=not issues,
            issues=issues,
            suggestion=suggestion,
            suggested_next_action=suggested_next_action,
            semantic_checks=semantic_checks,
        )
        if suggested_next_action:
            print(f"[verifier] suggested_next_action={suggested_next_action}")
        print(f"[verifier] final_answer passed={result.passed}")
        return result

    def verify_tool_observation(
        self,
        tool_name: str,
        result: Any,
        observation: str,
        evidence_ids: list[str],
    ) -> VerificationResult:
        print(f"[verifier] check tool observation: {tool_name}")
        issues: list[str] = []

        if isinstance(result, dict) and result.get("success") is False:
            issues.append(str(result.get("error", "tool returned success=False")))

        if not observation.strip():
            issues.append("tool observation is empty")

        evidence_tools = {
            "search_docs",
            "search_tables",
            "search_figures",
            "search_code",
            "grep_code",
            "view_file",
            "generate_patch",
            "edit_file",
            "suggest_tests",
            "shell_readonly",
            "run_tests",
        }
        if tool_name in evidence_tools and _has_non_empty_result(result) and not evidence_ids:
            issues.append("tool returned data but no evidence_ids were extracted")

        suggestion = None
        suggested_next_action = None
        if issues:
            suggestion = "Check the tool result shape, EvidenceExtractor, or choose a corrective next action."
            suggested_next_action = {
                "tool": "final_answer",
                "args": {
                    "answer": "Tool observation verification failed. Review the tool result and evidence extraction before answering."
                },
                "reason": "tool observation failed verifier checks",
            }

        result = VerificationResult(
            passed=not issues,
            issues=issues,
            suggestion=suggestion,
            suggested_next_action=suggested_next_action,
        )
        if suggested_next_action:
            print(f"[verifier] suggested_next_action={suggested_next_action}")
        print(f"[verifier] tool observation passed={result.passed}")
        return result

    def check_has_evidence(self, evidence_memory: EvidenceMemory) -> dict[str, object]:
        evidence_count = len(evidence_memory.list())
        print(f"[verifier] evidence count: {evidence_count}")
        return {
            "passed": evidence_count > 0,
            "missing_evidence": [] if evidence_count > 0 else ["final answer has no evidence support"],
        }


def _has_non_empty_result(result: Any) -> bool:
    if isinstance(result, list):
        return len(result) > 0
    if isinstance(result, dict):
        if result.get("success") is False:
            return False
        return bool(result)
    return bool(result)


def _missing_required_evidence_types(evidence_memory: EvidenceMemory, refs: list[str]) -> list[str]:
    referenced = set(refs)
    missing: list[str] = []
    for source_type in ["patch", "test"]:
        candidates = [item for item in evidence_memory.list() if item.source_type == source_type]
        if candidates and not any(item.evidence_id in referenced for item in candidates):
            missing.append(source_type)
    return missing


def _missing_available_evidence_types(evidence_memory: EvidenceMemory, refs: list[str]) -> list[str]:
    referenced = set(refs)
    missing: list[str] = []
    for source_type in ["doc", "code", "file", "table", "figure", "edit", "edit_preview"]:
        candidates = [item for item in evidence_memory.list() if item.source_type == source_type]
        if candidates and not any(item.evidence_id in referenced for item in candidates):
            missing.append(source_type)
    return missing


def _check_task_coverage(answer: str, task: str) -> str | None:
    if not answer:
        return None
    content_words = _content_words(task)
    if not content_words:
        return None
    answer_lower = answer.lower()
    matched = [word for word in content_words if word in answer_lower]
    min_matches = 1 if len(content_words) <= 3 else 2
    if len(matched) < min_matches:
        return "final_answer may not directly address the user task keywords"
    return None


def _check_unsupported_claims(answer: str, evidence_memory: EvidenceMemory) -> str | None:
    lowered = answer.lower()
    execution_claims = ["已执行", "测试通过", "已运行测试", "已经执行", "test passed", "executed", "ran tests"]
    if any(claim in lowered for claim in execution_claims):
        has_test_or_shell = any(item.source_type in {"test", "shell", "test_run"} for item in evidence_memory.list())
        if not has_test_or_shell:
            return "final_answer claims test execution without test or shell evidence"

    modification_claims = ["已修改", "已经修改", "修改了文件", "file was modified", "modified the file"]
    if any(claim in lowered for claim in modification_claims):
        has_edit = any(
            item.source_type == "edit" and item.metadata.get("apply") is True
            for item in evidence_memory.list()
        )
        if not has_edit:
            return "final_answer claims files were modified without applied edit_file evidence"
    return None


def _check_speculation(answer: str) -> str | None:
    speculation_markers = ["可能", "大概", "应该", "推测", "maybe", "probably"]
    if any(marker in answer.lower() for marker in speculation_markers):
        return "final_answer contains speculation markers; cite evidence or explicitly label uncertainty"
    return None


def _check_semantic_grounding(
    answer: str,
    evidence_memory: EvidenceMemory,
    refs: list[str],
) -> tuple[list[str], list[dict[str, object]]]:
    if not answer or not refs:
        return [], []

    referenced_items = [item for item in (evidence_memory.get(ref) for ref in refs) if item is not None]
    if not referenced_items:
        return [], []

    evidence_text = "\n".join(_evidence_grounding_text(item) for item in referenced_items)
    evidence_terms = set(_semantic_terms(evidence_text))
    evidence_numbers = set(_numbers(evidence_text))
    issues: list[str] = []
    checks: list[dict[str, object]] = []

    for claim in _extract_fact_claims(answer):
        terms = _semantic_terms(claim)
        if len(terms) < 3:
            continue

        matched_terms = [term for term in terms if term in evidence_terms]
        identifier_terms = _identifier_terms(claim)
        missing_identifier_terms = [term for term in identifier_terms if term not in evidence_terms]
        claim_numbers = _numbers(claim)
        missing_numbers = [number for number in claim_numbers if number not in evidence_numbers]
        coverage = len(matched_terms) / len(terms) if terms else 1.0
        supported = (
            coverage >= _semantic_threshold(len(terms))
            and not missing_identifier_terms
            and not missing_numbers
        )

        checks.append(
            {
                "claim": claim,
                "term_count": len(terms),
                "matched_term_count": len(matched_terms),
                "coverage": round(coverage, 3),
                "matched_terms": matched_terms[:12],
                "missing_identifier_terms": missing_identifier_terms[:8],
                "missing_numbers": missing_numbers[:8],
                "supported": supported,
            }
        )
        if supported:
            continue

        reason_parts: list[str] = []
        if coverage < _semantic_threshold(len(terms)):
            reason_parts.append(f"semantic coverage {coverage:.2f}")
        if missing_identifier_terms:
            reason_parts.append("missing identifiers " + ", ".join(missing_identifier_terms[:4]))
        if missing_numbers:
            reason_parts.append("missing numbers " + ", ".join(missing_numbers[:4]))
        issues.append(
            "final_answer has unsupported semantic claim: "
            f"{_shorten_text(claim, 120)} ({'; '.join(reason_parts)})"
        )

    return issues, checks


def _extract_fact_claims(answer: str) -> list[str]:
    main_text = _answer_body_before_evidence_list(answer)
    cleaned = EVIDENCE_REF_PATTERN.sub("", main_text)
    cleaned = re.sub(r"```.*?```", " ", cleaned, flags=re.DOTALL)
    raw_parts = re.split(r"[\n。！？!?；;]+", cleaned)
    claims: list[str] = []
    for part in raw_parts:
        claim = part.strip(" -:\t\r")
        if not claim:
            continue
        lowered = claim.lower()
        if lowered in {"evidence", "sources", "证据", "引用"}:
            continue
        if len(_semantic_terms(claim)) < 3:
            continue
        claims.append(claim)
    return claims[:8]


def _answer_body_before_evidence_list(answer: str) -> str:
    markers = ["\n证据：", "\n证据:", "\nEvidence:", "\nEvidence：", "\nSources:", "\nReferences:"]
    positions = [answer.find(marker) for marker in markers if answer.find(marker) >= 0]
    if not positions:
        return answer
    return answer[: min(positions)]


def _evidence_grounding_text(item: Any) -> str:
    metadata = item.metadata if isinstance(item.metadata, dict) else {}
    metadata_values = " ".join(str(value) for value in metadata.values() if isinstance(value, (str, int, float)))
    return "\n".join(
        [
            item.source_type,
            item.source,
            item.line_range or "",
            item.reason,
            item.content,
            metadata_values,
        ]
    )


def _semantic_terms(text: str) -> list[str]:
    normalized = text.lower()
    latin_terms = re.findall(r"[a-z0-9_./\\-]+", normalized)
    cjk_terms: list[str] = []
    if not latin_terms:
        cjk_chars = re.findall(r"[\u4e00-\u9fff]", normalized)
        cjk_terms = ["".join(cjk_chars[index : index + 2]) for index in range(0, max(len(cjk_chars) - 1, 0))]
    raw_terms = latin_terms + cjk_terms
    terms: list[str] = []
    for term in raw_terms:
        for piece in re.split(r"[./\\\-]+", term):
            if not piece or piece in _SEMANTIC_STOP_WORDS:
                continue
            if piece.startswith("ev_"):
                continue
            if len(piece) < 2 and not piece.isdigit():
                continue
            if piece not in terms:
                terms.append(piece)
    return terms


def _identifier_terms(text: str) -> list[str]:
    identifiers: list[str] = []
    for item in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text):
        lowered = item.lower()
        if "_" not in lowered:
            continue
        if lowered not in identifiers:
            identifiers.append(lowered)
    return identifiers


def _numbers(text: str) -> list[str]:
    return re.findall(r"\b\d+(?:\.\d+)?\b", text)


def _semantic_threshold(term_count: int) -> float:
    if term_count <= 4:
        return 0.5
    if term_count <= 8:
        return 0.4
    return 0.32


def _shorten_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def _build_suggested_next_action(
    issues: list[str],
    evidence_memory: EvidenceMemory,
    task: str | None,
) -> dict[str, object]:
    issue_text = " ".join(issues).lower()

    if "unsupported semantic claim" in issue_text:
        return {
            "tool": "final_answer",
            "args": {"answer": "Rewrite unsupported claims so each factual claim is grounded in cited evidence ids."},
            "reason": "semantic fact checking found an unsupported claim",
        }

    if "patch" in issue_text:
        return {
            "tool": "generate_patch",
            "args": {
                "file_path": _first_file_source(evidence_memory),
                "instruction": task or "Generate a patch suggestion based on the collected evidence.",
                "evidence_ids": _all_evidence_ids(evidence_memory),
            },
            "reason": "patch evidence is required or must be cited for this answer",
        }

    if "test" in issue_text:
        return {
            "tool": "suggest_tests",
            "args": {"context": task or "Validate the current answer.", "evidence_ids": _all_evidence_ids(evidence_memory)},
            "reason": "test evidence is required or must be cited for this answer",
        }

    if "modified without applied edit_file evidence" in issue_text:
        return {
            "tool": "edit_file",
            "args": {
                "path": _first_file_source(evidence_memory),
                "operation": "replace",
                "old_text": "",
                "new_text": "",
                "apply": False,
                "evidence_ids": _all_evidence_ids(evidence_memory),
            },
            "reason": "a modification claim requires applied edit_file evidence",
        }

    if "missing available evidence type refs" in issue_text or "missing evidence references" in issue_text:
        return {
            "tool": "final_answer",
            "args": {"answer": "Rewrite the answer using all relevant existing Evidence Memory ids."},
            "reason": "evidence exists but the answer did not cite enough relevant evidence",
        }

    if (
        "references missing evidence ids" in issue_text
        or "not directly address" in issue_text
        or "speculation" in issue_text
    ):
        return {
            "tool": "final_answer",
            "args": {"answer": "Rewrite the answer to directly address the user task and cite only real evidence ids."},
            "reason": "the answer needs correction based on verifier feedback",
        }

    if evidence_memory.list():
        return {
            "tool": "view_file",
            "args": {"path": _first_file_source(evidence_memory), "start": 1, "end": 120},
            "reason": "collect a more precise file segment before answering",
        }

    return {
        "tool": "search_docs",
        "args": {"query": task or "software engineering", "source": "hybrid", "top_k": 3},
        "reason": "no usable evidence is available yet",
    }


def _first_file_source(evidence_memory: EvidenceMemory) -> str:
    for item in evidence_memory.list():
        if item.source_type in {"file", "code", "patch", "edit", "edit_preview"}:
            return item.source
    return "agent/verifier.py"


def _all_evidence_ids(evidence_memory: EvidenceMemory) -> list[str]:
    return [item.evidence_id for item in evidence_memory.list()]


def _content_words(text: str) -> list[str]:
    words = [word.lower() for word in re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]+", text)]
    stop_words = {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "请",
        "给出",
        "说明",
        "一个",
        "如何",
        "什么",
        "哪里",
    }
    stop_words.update({"请", "给出", "说明", "一个", "如何", "什么", "哪里"})
    return [word for word in words if len(word) >= 3 and word not in stop_words][:8]
