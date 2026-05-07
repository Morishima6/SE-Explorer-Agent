import re
from dataclasses import asdict, dataclass, field
from typing import Any

from agent.evidence_memory import EvidenceMemory


EVIDENCE_REF_PATTERN = re.compile(r"\[(ev_\d{3,})\]")


@dataclass
class VerificationResult:
    passed: bool
    issues: list[str] = field(default_factory=list)
    suggestion: str | None = None
    suggested_next_action: dict[str, object] | None = None

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

        existing_ids = {item.evidence_id for item in evidence_items}
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

        suggestion = None
        suggested_next_action = None
        if issues:
            suggestion = "Rewrite the final answer using Evidence Memory and cite real evidence ids."
            suggested_next_action = _build_suggested_next_action(issues, evidence_memory, task)

        result = VerificationResult(
            passed=not issues,
            issues=issues,
            suggestion=suggestion,
            suggested_next_action=suggested_next_action,
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
    for source_type in ["doc", "code", "file", "table", "figure"]:
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
        return "final_answer claims files were modified, but current patch flow only provides suggestions"
    return None


def _check_speculation(answer: str) -> str | None:
    speculation_markers = ["可能", "大概", "应该", "推测", "maybe", "probably"]
    if any(marker in answer.lower() for marker in speculation_markers):
        return "final_answer contains speculation markers; cite evidence or explicitly label uncertainty"
    return None


def _build_suggested_next_action(
    issues: list[str],
    evidence_memory: EvidenceMemory,
    task: str | None,
) -> dict[str, object]:
    issue_text = " ".join(issues).lower()

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

    if "missing available evidence type refs" in issue_text or "missing evidence references" in issue_text:
        return {
            "tool": "final_answer",
            "args": {"answer": "Rewrite the answer using all relevant existing Evidence Memory ids."},
            "reason": "evidence exists but the answer did not cite enough relevant evidence",
        }

    if "references missing evidence ids" in issue_text or "not directly address" in issue_text or "speculation" in issue_text:
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
        "args": {"query": task or "software engineering", "source": "rag_anything", "top_k": 3},
        "reason": "no usable evidence is available yet",
    }


def _first_file_source(evidence_memory: EvidenceMemory) -> str:
    for item in evidence_memory.list():
        if item.source_type in {"file", "code", "patch"}:
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
