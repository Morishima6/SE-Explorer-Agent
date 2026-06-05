import sys
from types import SimpleNamespace
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.llm_client import LLMClient, _is_transient_llm_error


class FakeConnectionError(Exception):
    pass


class FakeCompletions:
    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.calls = 0

    def create(self, **_: object) -> object:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise FakeConnectionError("Connection error.")
        message = SimpleNamespace(content='{"tool": "final_answer", "args": {"answer": "ok"}}')
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])


class FakeClient:
    def __init__(self, fail_times: int) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions(fail_times))


def main() -> int:
    checks = [
        _check_connection_error_is_transient(),
        _check_request_timeout_config(),
        _check_retry_success(),
        _check_retry_exhausted(),
    ]
    passed = all(item[1] for item in checks)
    for name, ok, detail in checks:
        status = "passed" if ok else "failed"
        print(f"[LLM retry] {name}: {status}")
        if detail:
            print(f"      {detail}")
    print(f"[LLM retry] overall: {'passed' if passed else 'failed'}")
    return 0 if passed else 1


def _check_connection_error_is_transient() -> tuple[str, bool, str]:
    ok = _is_transient_llm_error(FakeConnectionError("Connection error."))
    return "connection error classified transient", ok, ""


def _check_request_timeout_config() -> tuple[str, bool, str]:
    client = LLMClient(
        model="fake-model",
        api_key="fake-key",
        max_retries=0,
        retry_base_seconds=0,
        request_timeout=180,
    )
    ok = client.request_timeout == 180
    return "request timeout is configurable", ok, f"timeout={client.request_timeout}"


def _check_retry_success() -> tuple[str, bool, str]:
    client = LLMClient(
        model="fake-model",
        api_key="fake-key",
        max_retries=3,
        retry_base_seconds=0,
    )
    fake_client = FakeClient(fail_times=2)
    response = client._complete_with_retry(fake_client, [{"role": "user", "content": "hi"}])
    calls = fake_client.chat.completions.calls
    ok = calls == 3 and response.choices[0].message.content
    return "retry succeeds after transient failures", ok, "" if ok else f"calls={calls}"


def _check_retry_exhausted() -> tuple[str, bool, str]:
    client = LLMClient(
        model="fake-model",
        api_key="fake-key",
        max_retries=2,
        retry_base_seconds=0,
    )
    fake_client = FakeClient(fail_times=3)
    try:
        client._complete_with_retry(fake_client, [{"role": "user", "content": "hi"}])
    except FakeConnectionError:
        return "retry exhaustion raises final error", fake_client.chat.completions.calls == 3, ""
    return "retry exhaustion raises final error", False, "expected FakeConnectionError"


if __name__ == "__main__":
    raise SystemExit(main())
