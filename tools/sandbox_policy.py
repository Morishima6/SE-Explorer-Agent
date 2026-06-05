from dataclasses import asdict, dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALLOWED_ROOTS = ["outputs/edit_file_sandbox"]
DEFAULT_TEXT_EXTENSIONS = {
    ".py",
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".html",
    ".css",
    ".js",
    ".ts",
}
DEFAULT_MAX_BYTES = 200_000


@dataclass(frozen=True)
class SandboxDecision:
    allowed: bool
    path: str
    relative_path: str
    reason: str
    allowed_roots: list[str]
    max_bytes: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def check_edit_path(
    path: str,
    allowed_roots: list[str] | None = None,
    text_extensions: set[str] | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> SandboxDecision:
    roots = allowed_roots or DEFAULT_ALLOWED_ROOTS
    extensions = text_extensions or DEFAULT_TEXT_EXTENSIONS
    target = _resolve_project_path(path)
    relative_path = _relative_to_project(target)

    if target.suffix.lower() not in extensions:
        return _decision(False, target, relative_path, f"extension not allowed: {target.suffix}", roots, max_bytes)

    if target.exists() and not target.is_file():
        return _decision(False, target, relative_path, "target is not a file", roots, max_bytes)

    if target.exists() and target.stat().st_size > max_bytes:
        return _decision(False, target, relative_path, "file exceeds sandbox max_bytes", roots, max_bytes)

    for root in roots:
        allowed_root = _resolve_project_path(root)
        if _is_within(target, allowed_root):
            return _decision(True, target, relative_path, "path is inside allowed edit sandbox", roots, max_bytes)

    return _decision(False, target, relative_path, "path is outside allowed edit sandbox", roots, max_bytes)


def _resolve_project_path(path: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate.resolve()


def _relative_to_project(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _decision(
    allowed: bool,
    path: Path,
    relative_path: str,
    reason: str,
    allowed_roots: list[str],
    max_bytes: int,
) -> SandboxDecision:
    return SandboxDecision(
        allowed=allowed,
        path=str(path),
        relative_path=relative_path,
        reason=reason,
        allowed_roots=allowed_roots,
        max_bytes=max_bytes,
    )
