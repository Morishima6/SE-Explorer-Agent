from tools.shell_readonly import shell_readonly


def run_tests(command: str, timeout: int = 60, test_type: str | None = None) -> dict[str, object]:
    print(f"[run_tests] command={command}, timeout={timeout}, test_type={test_type}")
    result = shell_readonly(command=command, timeout=timeout)
    blocked = result.get("returncode") is None
    if blocked:
        return {
            "success": False,
            "passed": False,
            "command": command,
            "test_type": test_type or "blocked",
            "command_type": result.get("command_type", "blocked"),
            "returncode": None,
            "elapsed_ms": result.get("elapsed_ms", 0),
            "stdout": "",
            "stderr": result.get("stderr", result.get("error", "")),
            "stdout_tail": "",
            "stderr_tail": result.get("stderr_tail", result.get("error", "")),
            "summary": str(result.get("error") or result.get("stderr") or "command blocked"),
            "error": result.get("error", "command blocked"),
        }

    inferred_type = test_type or _infer_test_type(str(result.get("command_type", "")))
    passed = result.get("returncode") == 0
    summary = f"{inferred_type} {'passed' if passed else 'failed'} with returncode={result.get('returncode')}"
    return {
        "success": True,
        "passed": passed,
        "command": command,
        "test_type": inferred_type,
        "command_type": result.get("command_type"),
        "returncode": result.get("returncode"),
        "elapsed_ms": result.get("elapsed_ms"),
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "stdout_tail": result.get("stdout_tail", ""),
        "stderr_tail": result.get("stderr_tail", ""),
        "summary": summary,
    }


def _infer_test_type(command_type: str) -> str:
    if command_type == "python -m compileall":
        return "compileall"
    if command_type in {"python -m pytest", "pytest"}:
        return "pytest"
    return "custom_allowlisted"
