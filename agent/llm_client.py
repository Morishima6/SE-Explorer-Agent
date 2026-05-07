import json
import os
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
    ) -> None:
        self.model = model or os.environ.get("OPENAI_MODEL")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.base_url = base_url or os.environ.get("OPENAI_BASE_URL")

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

        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        response = client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0,
        )
        return response.choices[0].message.content or ""


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
        return self._complete_docs(messages)

    def _complete_docs(self, messages: list[dict[str, str]]) -> str:
        if self._step == 1:
            print("[mock_llm_client] scenario=docs choose search_docs")
            return _json_action(
                "search_docs",
                {"query": _extract_user_task(messages) or "software architecture", "source": "rag_anything", "top_k": 3},
            )

        print("[mock_llm_client] scenario=docs choose final_answer")
        answer = (
            "根据已解析文档，当前检索结果显示主题与 Graduate Software Engineering / "
            "Software Engineering 课程指南相关。[ev_001]\n\n"
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
            "search_docs 工具在 demo/app.py 的 build_registry 中注册，并通过 ask 流程交给 "
            "ToolRegistry 执行。[ev_001][ev_002]\n\n"
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
            "轻量修复建议是强化 agent/verifier.py 中 final_answer 的证据引用校验，并用 mock "
            "Agent 链路验证 evidence 与 trajectory 是否仍然正常。[ev_001][ev_002][ev_003][ev_004]\n\n"
            "证据：\n"
            "- [ev_001] 定位到 evidence 引用匹配逻辑。\n"
            "- [ev_002] 展示了 verify_final_answer 的实现片段。\n"
            "- [ev_003] 给出了不改文件的 patch suggestion。\n"
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
                {"query": "Graduate Software Engineering", "source": "rag_anything", "top_k": 1},
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
