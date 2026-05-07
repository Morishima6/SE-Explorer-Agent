import shlex
import subprocess
import time


ALLOWED_COMMANDS = {"pytest", "rg"}
ALLOWED_PYTHON_MODULES = {"compileall", "pytest"}
BLOCKED_TOKENS = {"rm", "del", "erase", "move", "mv", "copy", "cp", "curl", "wget", "pip", "conda", "sudo"}
OUTPUT_TAIL_CHARS = 4000


def shell_readonly(command: str, timeout: int = 20) -> dict[str, object]:
    print(f"[shell_readonly] command={command}, timeout={timeout}")
    parts = shlex.split(command, posix=False)
    if not parts:
        return _blocked_result(command, "empty command")

    blocked = _find_blocked_token(parts)
    if blocked:
        return _blocked_result(command, f"blocked token in read-only command: {blocked}")

    if parts[0] == "python":
        allowed = len(parts) >= 3 and parts[1] == "-m" and parts[2] in ALLOWED_PYTHON_MODULES
        command_type = f"python -m {parts[2]}" if allowed else "python"
    else:
        allowed = parts[0] in ALLOWED_COMMANDS
        command_type = parts[0]

    if not allowed:
        return _blocked_result(command, f"command not allowed: {parts[0]}")

    started_at = time.perf_counter()
    completed = subprocess.run(parts, capture_output=True, text=True, timeout=timeout)
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    print(
        "[shell_readonly] completed "
        f"type={command_type}, returncode={completed.returncode}, elapsed_ms={elapsed_ms}"
    )
    return {
        "success": completed.returncode == 0,
        "command": command,
        "command_type": command_type,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_tail": stdout[-OUTPUT_TAIL_CHARS:],
        "stderr_tail": stderr[-OUTPUT_TAIL_CHARS:],
        "returncode": completed.returncode,
        "elapsed_ms": elapsed_ms,
    }


def _blocked_result(command: str, error: str) -> dict[str, object]:
    print(f"[shell_readonly] blocked: {error}")
    return {
        "success": False,
        "command": command,
        "command_type": "blocked",
        "stdout": "",
        "stderr": error,
        "stdout_tail": "",
        "stderr_tail": error,
        "returncode": None,
        "elapsed_ms": 0,
        "error": error,
    }


def _find_blocked_token(parts: list[str]) -> str | None:
    normalized = {part.lower().strip("\"'") for part in parts}
    for token in BLOCKED_TOKENS:
        if token in normalized:
            return token
    return None
