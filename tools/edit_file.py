import difflib
import hashlib
from datetime import datetime
from pathlib import Path

from tools.sandbox_policy import PROJECT_ROOT, check_edit_path


def edit_file(
    path: str,
    operation: str,
    old_text: str = "",
    new_text: str = "",
    append_text: str = "",
    apply: bool = False,
    evidence_ids: list[str] | None = None,
) -> dict[str, object]:
    print(f"[edit_file] path={path}, operation={operation}, apply={apply}")
    evidence_ids = evidence_ids or []
    decision = check_edit_path(path)
    if not decision.allowed:
        return {
            "success": False,
            "path": path,
            "operation": operation,
            "apply": apply,
            "evidence_ids": evidence_ids,
            "error": decision.reason,
            "policy": decision.to_dict(),
        }

    target = Path(decision.path)
    if not target.exists():
        return {
            "success": False,
            "path": decision.relative_path,
            "operation": operation,
            "apply": apply,
            "evidence_ids": evidence_ids,
            "error": f"file not found: {decision.relative_path}",
            "policy": decision.to_dict(),
        }

    before = target.read_text(encoding="utf-8", errors="replace")
    try:
        after = _apply_operation(before, operation, old_text, new_text, append_text)
    except ValueError as exc:
        return {
            "success": False,
            "path": decision.relative_path,
            "operation": operation,
            "apply": apply,
            "evidence_ids": evidence_ids,
            "error": str(exc),
            "policy": decision.to_dict(),
        }
    changed = before != after
    diff = _build_diff(decision.relative_path, before, after)
    before_hash = _sha256(before)
    after_hash = _sha256(after)
    backup_path = ""

    if apply and changed:
        backup_path = _write_backup(target, before)
        _atomic_write(target, after)

    return {
        "success": True,
        "path": decision.relative_path,
        "operation": operation,
        "apply": apply,
        "changed": changed,
        "evidence_ids": evidence_ids,
        "before_hash": before_hash,
        "after_hash": after_hash,
        "backup_path": backup_path,
        "diff": diff,
        "policy": decision.to_dict(),
        "note": "edit_file applied changes inside the sandbox." if apply else "dry-run only; no file was modified.",
    }


def _apply_operation(before: str, operation: str, old_text: str, new_text: str, append_text: str) -> str:
    if operation == "replace":
        if not old_text:
            raise ValueError("old_text is required for replace")
        count = before.count(old_text)
        if count != 1:
            raise ValueError(f"replace requires exactly one match, found {count}")
        return before.replace(old_text, new_text, 1)

    if operation == "append":
        text = append_text or new_text
        if not text:
            raise ValueError("append_text or new_text is required for append")
        separator = "" if before.endswith("\n") else "\n"
        return before + separator + text

    raise ValueError(f"unsupported edit operation: {operation}")


def _build_diff(path: str, before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_backup(target: Path, content: str) -> str:
    relative = target.relative_to(PROJECT_ROOT)
    backup_dir = PROJECT_ROOT / "outputs" / "edit_file_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "__".join(relative.parts)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = backup_dir / f"{timestamp}__{safe_name}.bak"
    backup_path.write_text(content, encoding="utf-8")
    return str(backup_path.relative_to(PROJECT_ROOT))


def _atomic_write(target: Path, content: str) -> None:
    temp_path = target.with_name(f"{target.name}.tmp")
    temp_path.write_text(content, encoding="utf-8")
    temp_path.replace(target)
