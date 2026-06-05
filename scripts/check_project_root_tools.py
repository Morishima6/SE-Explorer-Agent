import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.grep_code import grep_code
from tools.list_repo_tree import list_repo_tree
from tools.search_code import search_code
from tools.view_file import view_file


FIXTURE_ROOT = PROJECT_ROOT / "outputs" / "project_root_fixture"


def main() -> int:
    _write_fixture()
    checks = [
        _check_view_file_project_root(),
        _check_search_code_project_root(),
        _check_grep_code_project_root(),
        _check_list_repo_tree_project_root(),
        _check_project_root_slash_path(),
        _check_project_root_backslash_path(),
        _check_view_file_rejects_line_range(),
        _check_list_repo_tree_rejects_recursive(),
    ]
    passed = all(item[1] for item in checks)
    for name, ok, detail in checks:
        status = "passed" if ok else "failed"
        print(f"[project root tools] {name}: {status}")
        if detail:
            print(f"      {detail}")
    print(f"[project root tools] overall: {'passed' if passed else 'failed'}")
    return 0 if passed else 1


def _write_fixture() -> None:
    src_dir = FIXTURE_ROOT / "src" / "pages"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "Planner.jsx").write_text(
        "\n".join(
            [
                "export default function Planner() {",
                "  const result = generatePlan(form);",
                "  return result;",
                "}",
            ]
        ),
        encoding="utf-8",
    )


def _check_view_file_project_root() -> tuple[str, bool, str]:
    result = view_file("src/pages/Planner.jsx", project_root=str(FIXTURE_ROOT))
    ok = result.get("success") is not False and "generatePlan" in str(result.get("content", ""))
    return "view_file resolves relative path under project_root", ok, str(result)[:500]


def _check_search_code_project_root() -> tuple[str, bool, str]:
    result = search_code("generatePlan", path=".", project_root=str(FIXTURE_ROOT), top_k=5)
    ok = isinstance(result, list) and any("Planner.jsx" in str(item.get("path", "")) for item in result)
    return "search_code searches project_root instead of cwd", ok, str(result)[:500]


def _check_grep_code_project_root() -> tuple[str, bool, str]:
    result = grep_code("generatePlan", path="src", project_root=str(FIXTURE_ROOT), max_results=5)
    ok = isinstance(result, list) and any("Planner.jsx" in str(item.get("path", "")) for item in result)
    return "grep_code searches relative path under project_root", ok, str(result)[:500]


def _check_list_repo_tree_project_root() -> tuple[str, bool, str]:
    result = list_repo_tree(path=".", project_root=str(FIXTURE_ROOT), max_depth=3)
    ok = isinstance(result, list) and any("src" in item for item in result)
    return "list_repo_tree lists project_root", ok, str(result)[:500]


def _check_project_root_slash_path() -> tuple[str, bool, str]:
    result = list_repo_tree(path="/", project_root=str(FIXTURE_ROOT), max_depth=3)
    ok = isinstance(result, list) and any("Planner.jsx" in item for item in result)
    return "path slash resolves to project_root", ok, str(result)[:500]


def _check_project_root_backslash_path() -> tuple[str, bool, str]:
    result = list_repo_tree(path="\\", project_root=str(FIXTURE_ROOT), max_depth=3)
    ok = isinstance(result, list) and any("Planner.jsx" in item for item in result)
    return "path backslash resolves to project_root", ok, str(result)[:500]


def _check_view_file_rejects_line_range() -> tuple[str, bool, str]:
    result = view_file("src/pages/Planner.jsx", project_root=str(FIXTURE_ROOT), line_range="1-2")
    ok = isinstance(result, dict) and result.get("success") is False and "line_range" in str(result.get("error", ""))
    return "view_file rejects unsupported line_range", ok, str(result)


def _check_list_repo_tree_rejects_recursive() -> tuple[str, bool, str]:
    result = list_repo_tree(path=".", project_root=str(FIXTURE_ROOT), recursive=True)
    ok = isinstance(result, dict) and result.get("success") is False and "recursive" in str(result.get("error", ""))
    return "list_repo_tree rejects unsupported recursive", ok, str(result)


if __name__ == "__main__":
    raise SystemExit(main())
