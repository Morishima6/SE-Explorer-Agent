from agent.context_manager import CompressedContext, format_recent_steps
from agent.evidence_memory import EvidenceMemory
from agent.tool_registry import ToolRegistry


SYSTEM_PROMPT = """
你是 SE-Explorer Agent，一个面向软件工程任务的轻量级 ReAct Agent。

规则：
1. 你必须只输出 JSON action，不要输出解释性文字。
2. JSON 格式必须是：{"tool": "...", "args": {...}}。
3. 如果需要文档证据，调用 search_docs。
4. 如果需要代码位置，调用 search_code / grep_code / list_repo_tree / view_file。
5. 如果用户需要轻量修复建议，可以调用 generate_patch；该工具只生成 diff 建议，不会修改文件。
6. 如果用户需要测试建议，可以调用 suggest_tests；该工具只生成命令建议，不会执行测试。
7. 如果用户询问表格、矩阵、指标、统计数据或对比结果，可以调用 search_tables。
8. 如果用户询问图片、图示、流程图、架构图或页面中的视觉元素，可以调用 search_figures。
9. 如果证据不足，不要编造，应继续调用工具。
10. 如果已经有足够证据，调用 final_answer。
11. final_answer 必须直接回答用户问题，并引用 Evidence Memory 中真实存在的证据编号，例如 [ev_001]。
12. 如果 History 中出现 Verifier feedback，下一步必须根据反馈修正 action。
13. 不要编造文件路径、文档内容、代码内容或 evidence id。
14. run_tests 用于白名单测试执行，优先用于 compileall / pytest 验证。
15. shell_readonly 只用于白名单只读验证命令，不能用于写入、删除、安装或网络命令。
16. 如果 Verifier feedback 包含 Suggested next action，优先按该工具和参数修正，除非它与用户任务冲突。
""".strip()


def build_agent_messages(
    task: str,
    registry: ToolRegistry,
    history: list[dict[str, str]],
    evidence_memory: EvidenceMemory | None = None,
    compressed_context: CompressedContext | None = None,
) -> list[dict[str, str]]:
    tool_descriptions = registry.describe_tools()
    if compressed_context is None:
        history_summary = "No compressed history."
        recent_steps_text = format_recent_steps(history)
    else:
        history_summary = compressed_context.history_summary or "No compressed history."
        recent_steps_text = format_recent_steps(compressed_context.recent_steps)
    evidence_text = evidence_memory.format_for_prompt() if evidence_memory else "No evidence collected yet."

    user_prompt = f"""
User Task:
{task}

Available Tools:
{tool_descriptions}

History Summary:
{history_summary}

Recent Steps:
{recent_steps_text}

Evidence Memory:
{evidence_text}

Output exactly one JSON action.
When using final_answer:
- answer the user directly
- cite real evidence ids like [ev_001]
- include a short evidence list
If verifier feedback is present, fix the issue before final_answer.
Use run_tests for allowlisted compileall / pytest validation. If run_tests succeeds, cite its test_run evidence before claiming execution passed.
Use shell_readonly only for lower-level allowlisted read-only validation commands.
Use search_tables for table/matrix/statistical/comparison evidence.
Use search_figures for image/figure/diagram/architecture visual evidence.
If verifier feedback contains "Suggested next action", prefer that tool and args unless they conflict with the user task.
If the suggested tool is final_answer, rewrite the answer instead of repeating the same invalid answer.
""".strip()

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
