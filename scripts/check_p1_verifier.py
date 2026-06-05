import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from agent.evidence_memory import EvidenceMemory
from agent.verifier import Verifier


def main() -> int:
    checks = [
        _check_missing_ref(),
        _check_unknown_ref(),
        _check_vague_answer(),
        _check_patch_test_not_cited(),
        _check_task_coverage(),
        _check_semantic_fact_mismatch(),
        _check_semantic_fact_supported(),
        _check_valid_answer(),
    ]
    passed = all(item[1] for item in checks)
    for name, ok, detail in checks:
        status = "passed" if ok else "failed"
        print(f"[P1 verifier] {name}: {status}")
        if detail:
            print(f"      {detail}")
    print(f"[P1 verifier] overall: {'passed' if passed else 'failed'}")
    return 0 if passed else 1


def _check_missing_ref() -> tuple[str, bool, str]:
    memory = EvidenceMemory()
    memory.add("doc", "docs/demo.md", "software architecture guidance", "test evidence")
    result = Verifier().verify_final_answer(
        "Software architecture guidance is available.",
        memory,
        task="software architecture",
    )
    return _expect_fail("missing evidence ref", result, "missing evidence references")


def _check_unknown_ref() -> tuple[str, bool, str]:
    memory = EvidenceMemory()
    memory.add("doc", "docs/demo.md", "software architecture guidance", "test evidence")
    result = Verifier().verify_final_answer(
        "Software architecture guidance is available. [ev_999]",
        memory,
        task="software architecture",
    )
    return _expect_fail("unknown evidence ref", result, "references missing evidence ids")


def _check_vague_answer() -> tuple[str, bool, str]:
    memory = EvidenceMemory()
    memory.add("doc", "docs/demo.md", "software architecture guidance", "test evidence")
    result = Verifier().verify_final_answer(
        "Please see above. [ev_001]",
        memory,
        task="software architecture",
    )
    return _expect_fail("vague answer", result, "must answer directly")


def _check_patch_test_not_cited() -> tuple[str, bool, str]:
    memory = EvidenceMemory()
    memory.add("code", "agent/verifier.py", "Verifier checks final answers.", "code evidence")
    memory.add("patch", "agent/verifier.py", "--- a/agent/verifier.py", "patch evidence")
    memory.add("test", "suggest_tests", "python scripts/check_p1_verifier.py", "test evidence")
    result = Verifier().verify_final_answer(
        "Verifier should cite code evidence only. [ev_001]",
        memory,
        task="verifier fix suggestion",
    )
    return _expect_fail("patch/test citation", result, "patch")


def _check_task_coverage() -> tuple[str, bool, str]:
    memory = EvidenceMemory()
    memory.add("doc", "docs/demo.md", "software architecture guidance", "test evidence")
    result = Verifier().verify_final_answer(
        "Evidence is available. [ev_001]",
        memory,
        task="explain verifier evidence validation",
    )
    return _expect_fail("task coverage", result, "not directly address")


def _check_semantic_fact_mismatch() -> tuple[str, bool, str]:
    memory = EvidenceMemory()
    memory.add(
        "code",
        "demo/app.py",
        'registry.register("search_docs", "Search parsed docs", search_docs)',
        "tool registry evidence",
    )
    result = Verifier().verify_final_answer(
        "run_tests is registered in demo/app.py. [ev_001]",
        memory,
        task="explain run_tests registration",
    )
    return _expect_fail("semantic fact mismatch", result, "unsupported semantic claim")


def _check_semantic_fact_supported() -> tuple[str, bool, str]:
    memory = EvidenceMemory()
    memory.add(
        "code",
        "demo/app.py",
        'registry.register("search_docs", "Search parsed docs", search_docs)',
        "tool registry evidence",
    )
    result = Verifier().verify_final_answer(
        "search_docs is registered in demo/app.py. [ev_001]",
        memory,
        task="explain search_docs registration",
    )
    ok = result.passed and result.semantic_checks and result.semantic_checks[0]["supported"] is True
    return "semantic fact supported", ok, "" if ok else str(result.to_dict())


def _check_valid_answer() -> tuple[str, bool, str]:
    memory = EvidenceMemory()
    memory.add("code", "agent/verifier.py", "Verifier checks final_answer evidence refs.", "code evidence")
    memory.add("file", "agent/verifier.py", "verify_final_answer implementation", "file evidence")
    memory.add("patch", "agent/verifier.py", "--- a/agent/verifier.py", "patch evidence")
    memory.add("test", "suggest_tests", "python scripts/check_p1_verifier.py", "test evidence")
    result = Verifier().verify_final_answer(
        "Verifier evidence validation is implemented in agent/verifier.py and the fix path includes patch and test evidence. [ev_001][ev_002][ev_003][ev_004]",
        memory,
        task="explain verifier evidence validation fix",
    )
    ok = result.passed and result.suggested_next_action is None
    return "valid answer", ok, "" if ok else str(result.to_dict())


def _expect_fail(name: str, result, expected_issue_fragment: str) -> tuple[str, bool, str]:
    issue_text = " | ".join(result.issues).lower()
    ok = (
        not result.passed
        and expected_issue_fragment.lower() in issue_text
        and result.suggested_next_action is not None
    )
    return name, ok, "" if ok else str(result.to_dict())


if __name__ == "__main__":
    raise SystemExit(main())
