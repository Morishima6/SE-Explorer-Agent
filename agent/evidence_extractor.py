from typing import Any

from agent.evidence_memory import EvidenceMemory


def extract_evidence_from_tool_result(
    tool_name: str,
    args: dict[str, Any],
    result: Any,
    evidence_memory: EvidenceMemory,
    max_items: int = 3,
) -> list[str]:
    print(f"[evidence_extractor] extract from tool={tool_name}")

    if isinstance(result, dict) and result.get("success") is False:
        return []

    if tool_name == "search_docs" and isinstance(result, list):
        return _extract_search_docs(args, result, evidence_memory, max_items)

    if tool_name == "search_tables" and isinstance(result, list):
        return _extract_structured_doc_search("table", args, result, evidence_memory, max_items)

    if tool_name == "search_figures" and isinstance(result, list):
        return _extract_structured_doc_search("figure", args, result, evidence_memory, max_items)

    if tool_name in {"grep_code", "search_code"} and isinstance(result, list):
        return _extract_code_search(tool_name, args, result, evidence_memory, max_items)

    if tool_name == "view_file":
        return _extract_view_file(args, result, evidence_memory)

    if tool_name == "generate_patch":
        return _extract_generate_patch(args, result, evidence_memory)

    if tool_name == "suggest_tests":
        return _extract_suggest_tests(args, result, evidence_memory)

    if tool_name in {"shell_readonly", "run_tests"}:
        return _extract_test_run(tool_name, args, result, evidence_memory)

    return []


def _extract_search_docs(
    args: dict[str, Any],
    result: list[Any],
    evidence_memory: EvidenceMemory,
    max_items: int,
) -> list[str]:
    evidence_ids: list[str] = []
    query = str(args.get("query", ""))
    for item in result[:max_items]:
        if not isinstance(item, dict):
            continue
        evidence = evidence_memory.add(
            source_type="doc",
            source=str(item.get("source", "unknown")),
            content=str(item.get("snippet", "")),
            reason=f"search_docs matched query: {query}",
            score=item.get("score"),
            metadata=dict(item.get("metadata", {})) if isinstance(item.get("metadata"), dict) else {},
        )
        evidence_ids.append(evidence.evidence_id)
    return evidence_ids


def _extract_structured_doc_search(
    source_type: str,
    args: dict[str, Any],
    result: list[Any],
    evidence_memory: EvidenceMemory,
    max_items: int,
) -> list[str]:
    evidence_ids: list[str] = []
    query = str(args.get("query", ""))
    for item in result[:max_items]:
        if not isinstance(item, dict):
            continue
        evidence = evidence_memory.add(
            source_type=source_type,
            source=str(item.get("source", "unknown")),
            content=str(item.get("snippet", "")),
            reason=f"search_{source_type}s matched query: {query}",
            score=item.get("score"),
            metadata=dict(item.get("metadata", {})) if isinstance(item.get("metadata"), dict) else {},
        )
        evidence_ids.append(evidence.evidence_id)
    return evidence_ids


def _extract_code_search(
    tool_name: str,
    args: dict[str, Any],
    result: list[Any],
    evidence_memory: EvidenceMemory,
    max_items: int,
) -> list[str]:
    evidence_ids: list[str] = []
    query = str(args.get("query") or args.get("pattern") or "")
    for item in result[:max_items]:
        if not isinstance(item, dict):
            continue
        line = item.get("line")
        line_range = f"{line}-{line}" if line is not None else None
        evidence = evidence_memory.add(
            source_type="code",
            source=str(item.get("path", "unknown")),
            line_range=line_range,
            content=str(item.get("text", "")),
            reason=f"{tool_name} matched query: {query}",
        )
        evidence_ids.append(evidence.evidence_id)
    return evidence_ids


def _extract_view_file(
    args: dict[str, Any],
    result: Any,
    evidence_memory: EvidenceMemory,
) -> list[str]:
    if isinstance(result, dict):
        evidence = evidence_memory.add(
            source_type="file",
            source=str(result.get("path", args.get("path", "unknown"))),
            line_range=str(result.get("line_range", "")) or None,
            content=str(result.get("content", "")),
            reason="view_file returned requested file segment",
        )
        return [evidence.evidence_id]

    if isinstance(result, str):
        evidence = evidence_memory.add(
            source_type="file",
            source=str(args.get("path", "unknown")),
            line_range=f"{args.get('start', 1)}-{args.get('end', 120)}",
            content=result,
            reason="view_file returned requested file segment",
        )
        return [evidence.evidence_id]

    return []


def _extract_generate_patch(
    args: dict[str, Any],
    result: Any,
    evidence_memory: EvidenceMemory,
) -> list[str]:
    if not isinstance(result, dict):
        return []

    content = str(result.get("patch_suggestion", ""))
    if not content:
        return []

    evidence = evidence_memory.add(
        source_type="patch",
        source=str(result.get("file_path", args.get("file_path", "unknown"))),
        content=content,
        reason="generate_patch created a patch suggestion",
        metadata={
            "instruction": str(result.get("instruction", args.get("instruction", ""))),
            "input_evidence_ids": result.get("evidence_ids", []),
        },
    )
    return [evidence.evidence_id]


def _extract_suggest_tests(
    args: dict[str, Any],
    result: Any,
    evidence_memory: EvidenceMemory,
) -> list[str]:
    if not isinstance(result, dict):
        return []

    commands = result.get("commands", [])
    notes = result.get("notes", [])
    expected_checks = result.get("expected_checks", [])
    content = "\n".join(
        [
            *(str(item) for item in commands),
            *(str(item) for item in notes),
            *(f"expected: {item}" for item in expected_checks),
        ]
    )
    if not content:
        return []

    evidence = evidence_memory.add(
        source_type="test",
        source="suggest_tests",
        content=content,
        reason="suggest_tests created validation commands",
        metadata={
            "context": str(result.get("context", args.get("context", ""))),
            "input_evidence_ids": result.get("evidence_ids", []),
        },
    )
    return [evidence.evidence_id]


def _extract_test_run(
    tool_name: str,
    args: dict[str, Any],
    result: Any,
    evidence_memory: EvidenceMemory,
) -> list[str]:
    if not isinstance(result, dict) or result.get("success") is not True:
        return []

    command = str(result.get("command", args.get("command", "")))
    stdout_tail = str(result.get("stdout_tail", result.get("stdout", "")))
    stderr_tail = str(result.get("stderr_tail", result.get("stderr", "")))
    content = "\n".join(
        item
        for item in [
            f"command: {command}",
            f"tool: {tool_name}",
            f"test_type: {result.get('test_type', result.get('command_type', ''))}",
            f"passed: {result.get('passed', result.get('success'))}",
            f"returncode: {result.get('returncode')}",
            f"elapsed_ms: {result.get('elapsed_ms')}",
            f"summary: {result.get('summary')}" if result.get("summary") else "",
            f"stdout_tail:\n{stdout_tail}" if stdout_tail else "",
            f"stderr_tail:\n{stderr_tail}" if stderr_tail else "",
        ]
        if item
    )

    evidence = evidence_memory.add(
        source_type="test_run",
        source=tool_name,
        content=content,
        reason=f"{tool_name} executed an allowlisted validation command",
        metadata={
            "command": command,
            "command_type": str(result.get("command_type", "")),
            "test_type": str(result.get("test_type", "")),
            "passed": result.get("passed", result.get("success")),
            "returncode": result.get("returncode"),
            "elapsed_ms": result.get("elapsed_ms"),
        },
    )
    return [evidence.evidence_id]
