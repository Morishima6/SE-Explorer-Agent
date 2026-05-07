import re
from pathlib import Path


def generate_patch(
    file_path: str,
    instruction: str,
    evidence_ids: list[str] | None = None,
) -> dict[str, object]:
    print(f"[generate_patch] file_path={file_path}")
    path = Path(file_path)
    evidence_ids = evidence_ids or []

    if not path.exists():
        return {
            "success": False,
            "file_path": file_path,
            "instruction": instruction,
            "evidence_ids": evidence_ids,
            "error": f"file not found: {file_path}",
        }

    patch_suggestion = _build_patch_suggestion(file_path=file_path, instruction=instruction)
    return {
        "success": True,
        "file_path": file_path,
        "instruction": instruction,
        "evidence_ids": evidence_ids,
        "patch_suggestion": patch_suggestion,
        "note": "This is a patch suggestion only. No file was modified.",
    }


def _build_patch_suggestion(file_path: str, instruction: str) -> str:
    lines = Path(file_path).read_text(encoding="utf-8", errors="replace").splitlines()
    anchor = _find_anchor_line(lines, instruction)
    start = max(1, anchor - 2)
    end = min(len(lines), anchor + 2)
    old_count = max(1, end - start + 1)
    context = lines[start - 1 : end]

    patch_lines = [
        f"--- a/{file_path}",
        f"+++ b/{file_path}",
        f"@@ -{start},{old_count} +{start},{old_count + 3} @@",
    ]
    patch_lines.extend(f" {line}" for line in context)
    patch_lines.extend(
        [
            f"+# P0 patch suggestion: {instruction}",
            "+# TODO: replace this suggestion with the exact code change after review.",
            "+# No source file was modified by generate_patch.",
        ]
    )
    return "\n".join(patch_lines)


def _find_anchor_line(lines: list[str], instruction: str) -> int:
    terms = [term.lower() for term in re.split(r"\W+", instruction) if len(term) >= 4]
    best_line = 1
    best_score = -1
    for index, line in enumerate(lines, start=1):
        lowered = line.lower()
        score = sum(1 for term in terms if term in lowered)
        if score > best_score:
            best_line = index
            best_score = score
    return best_line
