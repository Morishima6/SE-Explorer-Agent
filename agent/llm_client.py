import json
import os
import time
from typing import Protocol


class LLMClientProtocol(Protocol):
    def complete(self, messages: list[dict[str, str]]) -> str:
        ...


class LLMClient:
    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        max_retries: int | None = None,
        retry_base_seconds: float | None = None,
        request_timeout: float | None = None,
    ) -> None:
        self.model = model or os.environ.get("OPENAI_MODEL")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.base_url = base_url or os.environ.get("OPENAI_BASE_URL")
        self.max_retries = max_retries if max_retries is not None else int(os.environ.get("LLM_MAX_RETRIES", "3"))
        self.retry_base_seconds = (
            retry_base_seconds
            if retry_base_seconds is not None
            else float(os.environ.get("LLM_RETRY_BASE_SECONDS", "2"))
        )
        self.request_timeout = (
            request_timeout
            if request_timeout is not None
            else float(os.environ.get("LLM_REQUEST_TIMEOUT", "120"))
        )

        if not self.model:
            raise ValueError("OPENAI_MODEL is required for real Agent Loop mode")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required for real Agent Loop mode")

    def complete(self, messages: list[dict[str, str]]) -> str:
        print(f"[llm_client] call model={self.model}")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Package 'openai' is required. Run: pip install openai") from exc

        client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.request_timeout)
        response = self._complete_with_retry(client, messages)
        return response.choices[0].message.content or ""

    def _complete_with_retry(self, client: object, messages: list[dict[str, str]]) -> object:
        total_attempts = max(1, self.max_retries + 1)
        last_error: Exception | None = None
        for attempt in range(1, total_attempts + 1):
            try:
                response = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0,
                )
                if attempt > 1:
                    print(f"[llm_client] retry success attempt={attempt}/{total_attempts}")
                return response
            except Exception as exc:
                last_error = exc
                if attempt >= total_attempts or not _is_transient_llm_error(exc):
                    print(f"[llm_client] request failed attempt={attempt}/{total_attempts}, error={exc}")
                    raise
                wait_seconds = _retry_wait_seconds(attempt, self.retry_base_seconds)
                print(
                    "[llm_client] transient error "
                    f"attempt={attempt}/{total_attempts}, wait={wait_seconds:g}s, error={exc}"
                )
                time.sleep(wait_seconds)
                print("[llm_client] retry after transient error")
        raise RuntimeError(f"LLM request failed after retry: {last_error}")


def _retry_wait_seconds(attempt: int, base_seconds: float) -> float:
    waits = [base_seconds, base_seconds * 2.5, base_seconds * 5]
    index = min(max(attempt - 1, 0), len(waits) - 1)
    return max(0, waits[index])


def _is_transient_llm_error(error: Exception) -> bool:
    name = error.__class__.__name__.lower()
    text = str(error).lower()
    transient_names = [
        "apiconnectionerror",
        "apitimeouterror",
        "ratelimiterror",
        "timeout",
        "connection",
    ]
    if any(item in name for item in transient_names):
        return True
    if "connection error" in text or "timeout" in text or "rate limit" in text:
        return True
    status_code = getattr(error, "status_code", None)
    return isinstance(status_code, int) and status_code >= 500


class MockLLMClient:
    def __init__(self, scenario: str = "docs") -> None:
        self.scenario = scenario
        self._step = 0

    def complete(self, messages: list[dict[str, str]]) -> str:
        self._step += 1
        if self.scenario == "code":
            return self._complete_code()
        if self.scenario == "fix":
            return self._complete_fix()
        if self.scenario == "test":
            return self._complete_test()
        if self.scenario == "multimodal":
            return self._complete_multimodal()
        if self.scenario == "edit":
            return self._complete_edit()
        return self._complete_docs(messages)

    def _complete_docs(self, messages: list[dict[str, str]]) -> str:
        if self._step == 1:
            print("[mock_llm_client] scenario=docs choose search_docs")
            return _json_action(
                "search_docs",
                {"query": _extract_user_task(messages) or "software architecture", "source": "hybrid", "top_k": 3},
            )

        print("[mock_llm_client] scenario=docs choose final_answer")
        answer = (
            "search_docs 命中的文档证据显示，结果包含 Graduate Software Engineering 和 "
            "Curriculum Guidelines for Graduate Degree Programs in Software Engineering。 [ev_001]\n\n"
            "证据：\n"
            "- [ev_001] 来自 search_docs 命中的解析文档片段。"
        )
        return _json_action("final_answer", {"answer": answer})

    def _complete_code(self) -> str:
        if self._step == 1:
            print("[mock_llm_client] scenario=code choose search_code")
            return _json_action("search_code", {"query": "search_docs", "path": "demo", "top_k": 1})
        if self._step == 2:
            print("[mock_llm_client] scenario=code choose view_file")
            return _json_action("view_file", {"path": "demo/app.py", "start": 55, "end": 80})

        print("[mock_llm_client] scenario=code choose final_answer")
        answer = (
            "search_docs 在 demo/app.py 中被导入，并在 build_registry() -> ToolRegistry 中通过 "
            "registry.register(\"search_docs\", ...) 注册。 [ev_001][ev_002]\n\n"
            "证据：\n"
            "- [ev_001] 来自 search_code 对 search_docs 的命中。\n"
            "- [ev_002] 来自 view_file 读取的 demo/app.py 注册片段。"
        )
        return _json_action("final_answer", {"answer": answer})

    def _complete_fix(self) -> str:
        if self._step == 1:
            print("[mock_llm_client] scenario=fix choose search_code")
            query = "EVIDENCE_" + "REF_PATTERN"
            return _json_action("search_code", {"query": query, "path": "agent", "top_k": 1})
        if self._step == 2:
            print("[mock_llm_client] scenario=fix choose view_file")
            return _json_action("view_file", {"path": "agent/verifier.py", "start": 20, "end": 70})
        if self._step == 3:
            print("[mock_llm_client] scenario=fix choose generate_patch")
            return _json_action(
                "generate_patch",
                {
                    "file_path": "agent/verifier.py",
                    "instruction": "Strengthen final_answer evidence-reference validation and keep the error message clear.",
                    "evidence_ids": ["ev_001", "ev_002"],
                },
            )
        if self._step == 4:
            print("[mock_llm_client] scenario=fix choose suggest_tests")
            return _json_action(
                "suggest_tests",
                {
                    "context": "Validate verifier evidence-reference behavior after the patch suggestion.",
                    "evidence_ids": ["ev_001", "ev_002", "ev_003"],
                },
            )

        print("[mock_llm_client] scenario=fix choose final_answer")
        answer = (
            "agent/verifier.py 包含 EVIDENCE_REF_PATTERN 和 verify_final_answer；generate_patch "
            "已生成 agent/verifier.py 的 patch suggestion，suggest_tests 已给出验证命令建议。 "
            "[ev_001][ev_002][ev_003][ev_004]\n\n"
            "证据：\n"
            "- [ev_001] 定位到 EVIDENCE_REF_PATTERN。\n"
            "- [ev_002] 展示了 verify_final_answer 的实现片段。\n"
            "- [ev_003] 给出了 agent/verifier.py 的 patch suggestion。\n"
            "- [ev_004] 给出了测试命令建议。"
        )
        return _json_action("final_answer", {"answer": answer})

    def _complete_test(self) -> str:
        if self._step == 1:
            print("[mock_llm_client] scenario=test choose search_code")
            return _json_action("search_code", {"query": "verify_final_answer", "path": "agent", "top_k": 1})
        if self._step == 2:
            print("[mock_llm_client] scenario=test choose suggest_tests")
            return _json_action(
                "suggest_tests",
                {
                    "context": "Validate compileall and verifier-related code after shell_readonly evidence support.",
                    "evidence_ids": ["ev_001"],
                },
            )
        if self._step == 3:
            print("[mock_llm_client] scenario=test choose run_tests")
            return _json_action(
                "run_tests",
                {
                    "command": "python -m compileall agent tools rag demo scripts eval",
                    "timeout": 60,
                    "test_type": "compileall",
                },
            )

        print("[mock_llm_client] scenario=test choose final_answer")
        answer = (
            "run_tests 已执行 allowlisted compileall validation，返回码为 0，说明当前 Python 模块语法检查通过。"
            "[ev_001][ev_002][ev_003]\n\n"
            "证据：\n"
            "- [ev_001] 来自 search_code 对 verifier 实现的定位。\n"
            "- [ev_002] 来自 suggest_tests 给出的验证命令建议。\n"
            "- [ev_003] 来自 run_tests 的实际测试执行结果。"
        )
        return _json_action("final_answer", {"answer": answer})

    def _complete_multimodal(self) -> str:
        if self._step == 1:
            print("[mock_llm_client] scenario=multimodal choose search_docs")
            return _json_action(
                "search_docs",
                {"query": "Graduate Software Engineering", "source": "hybrid", "top_k": 1},
            )
        if self._step == 2:
            print("[mock_llm_client] scenario=multimodal choose search_figures")
            return _json_action("search_figures", {"query": "image", "top_k": 1})

        print("[mock_llm_client] scenario=multimodal choose final_answer")
        answer = (
            "RAG-Anything 解析产物中可以同时收集正文文档证据和图示证据：正文 evidence 定位到 "
            "Graduate Software Engineering 相关内容，figure evidence 定位到解析出的 image block。"
            "[ev_001][ev_002]\n\n"
            "证据：\n"
            "- [ev_001] 来自 search_docs 命中的文档正文或结构化 block。\n"
            "- [ev_002] 来自 search_figures 命中的图片或图示 block。"
        )
        return _json_action("final_answer", {"answer": answer})

    def _complete_edit(self) -> str:
        if self._step == 1:
            print("[mock_llm_client] scenario=edit choose view_file")
            return _json_action(
                "view_file",
                {"path": "outputs/edit_file_sandbox/mock_edit_fixture.py", "start": 1, "end": 40},
            )
        if self._step == 2:
            print("[mock_llm_client] scenario=edit choose edit_file")
            return _json_action(
                "edit_file",
                {
                    "path": "outputs/edit_file_sandbox/mock_edit_fixture.py",
                    "operation": "replace",
                    "old_text": 'VALUE = "before"\n',
                    "new_text": 'VALUE = "after"\n',
                    "apply": True,
                    "evidence_ids": ["ev_001"],
                },
            )
        if self._step == 3:
            print("[mock_llm_client] scenario=edit choose run_tests")
            return _json_action(
                "run_tests",
                {
                    "command": "python -m compileall outputs/edit_file_sandbox",
                    "timeout": 60,
                    "test_type": "compileall",
                },
            )

        print("[mock_llm_client] scenario=edit choose final_answer")
        answer = (
            "edit_file 已修改 sandbox 文件 outputs/edit_file_sandbox/mock_edit_fixture.py，"
            "并已执行 allowlisted compileall 验证，返回码为 0。[ev_001][ev_002][ev_003]\n\n"
            "证据：\n"
            "- [ev_001] 来自 view_file 的修改前文件片段。\n"
            "- [ev_002] 来自 edit_file 的 sandbox diff、hash 和 backup metadata。\n"
            "- [ev_003] 来自 run_tests 的 compileall 执行结果。"
        )
        return _json_action("final_answer", {"answer": answer})


def _json_action(tool: str, args: dict[str, object]) -> str:
    return json.dumps({"tool": tool, "args": args}, ensure_ascii=False)


def _extract_user_task(messages: list[dict[str, str]]) -> str:
    for message in messages:
        if message.get("role") != "user":
            continue
        content = message.get("content", "")
        if "User Task:" in content and "Available Tools:" in content:
            return content.split("User Task:", 1)[1].split("Available Tools:", 1)[0].strip()
        return content.strip()
    return ""
