def suggest_tests(
    context: str,
    evidence_ids: list[str] | None = None,
) -> dict[str, object]:
    print("[suggest_tests] build test suggestions")
    evidence_ids = evidence_ids or []
    return {
        "success": True,
        "context": context,
        "evidence_ids": evidence_ids,
        "commands": _build_commands(context),
        "notes": _build_notes(context),
        "expected_checks": _build_expected_checks(context),
    }


def _build_commands(context: str) -> list[str]:
    lowered = context.lower()
    commands = ["python -m compileall agent tools rag demo scripts"]

    if any(term in lowered for term in ["registry", "tool", "search_code", "view_file"]):
        commands.append("python demo/app.py list")
        commands.append(
            'python demo/app.py ask "search_docs 工具在哪里注册和调用？" --mock --mock-scenario code --max-steps 4 --task-id p0_demo_code_check'
        )

    if any(term in lowered for term in ["doc", "docs", "search_docs", "rag"]):
        commands.append(
            'python demo/app.py ask "software architecture" --mock --mock-scenario docs --max-steps 3 --task-id p0_demo_docs_check'
        )

    if any(term in lowered for term in ["verifier", "evidence", "patch", "fix", "test"]):
        commands.append(
            'python demo/app.py ask "请给出 verifier 缺少证据引用时的轻量修复建议和测试建议" --mock --mock-scenario fix --max-steps 6 --task-id p0_demo_fix_check'
        )

    if len(commands) == 1:
        commands.extend(["python scripts/check_demo_ready.py", "python scripts/check_p0_chain.py"])

    return _dedupe(commands)


def _build_notes(context: str) -> list[str]:
    lowered = context.lower()
    notes = [
        "确认 compileall 无 SyntaxError。",
        "确认 final answer 引用真实 evidence id。",
        "确认 outputs/evidence 与 outputs/trajectories 中有对应记录。",
    ]
    if any(term in lowered for term in ["patch", "fix"]):
        notes.append("确认 patch suggestion 只写入 evidence，不直接修改源文件。")
    if "test" in lowered:
        notes.append("确认 test suggestion 只生成命令建议，除非显式调用 shell_readonly，否则不执行测试。")
    return notes


def _build_expected_checks(context: str) -> list[str]:
    lowered = context.lower()
    checks = ["verification.passed == true", "evidence.used_in_final contains true"]
    if any(term in lowered for term in ["patch", "fix", "verifier", "evidence"]):
        checks.extend(['source_type == "patch"', 'source_type == "test"'])
    if any(term in lowered for term in ["registry", "tool"]):
        checks.append("trajectory contains search_code and view_file")
    if any(term in lowered for term in ["doc", "docs", "rag"]):
        checks.append("trajectory contains search_docs")
    return checks


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped
