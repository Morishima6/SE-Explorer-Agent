import time
from dataclasses import dataclass, field
from typing import Any

from agent.action_parser import ActionParseError, AgentAction, parse_action
from agent.context_manager import compress_history
from agent.evidence_extractor import extract_evidence_from_tool_result
from agent.evidence_memory import EvidenceMemory
from agent.llm_client import LLMClientProtocol
from agent.observation import format_observation
from agent.prompts import build_agent_messages
from agent.tool_registry import ToolRegistry
from agent.trajectory import TrajectoryLogger, TrajectoryStep
from agent.verifier import VerificationResult, Verifier, extract_evidence_refs


@dataclass
class AgentRunResult:
    answer: str
    history: list[dict[str, str]] = field(default_factory=list)
    final_action: AgentAction | None = None
    evidence: list[dict[str, object]] = field(default_factory=list)
    verification: dict[str, object] | None = None


class AgentLoop:
    def __init__(
        self,
        registry: ToolRegistry,
        llm_client: LLMClientProtocol,
        max_steps: int = 6,
        trajectory_logger: TrajectoryLogger | None = None,
        evidence_memory: EvidenceMemory | None = None,
        verifier: Verifier | None = None,
        task_id: str = "demo_task",
        context_max_recent_steps: int = 4,
        context_max_observation_chars: int = 700,
    ) -> None:
        self.registry = registry
        self.llm_client = llm_client
        self.max_steps = max_steps
        self.trajectory_logger = trajectory_logger
        self.evidence_memory = evidence_memory or EvidenceMemory()
        self.verifier = verifier or Verifier()
        self.task_id = task_id
        self.context_max_recent_steps = context_max_recent_steps
        self.context_max_observation_chars = context_max_observation_chars

    def run_once(self, tool_name: str, **kwargs: object) -> object:
        print(f"[agent_loop] run once with tool={tool_name}")
        return self.registry.run(tool_name, **kwargs)

    def run(self, task: str) -> AgentRunResult:
        print(f"[agent_loop] start task_id={self.task_id}, max_steps={self.max_steps}")
        if self.trajectory_logger is not None:
            self.trajectory_logger.reset_task(self.task_id)
        self.evidence_memory.reset_jsonl(self.task_id)
        history: list[dict[str, str]] = []

        for step in range(1, self.max_steps + 1):
            started_at = time.perf_counter()
            compressed_context = compress_history(
                history,
                max_recent_steps=self.context_max_recent_steps,
                max_observation_chars=self.context_max_observation_chars,
            )
            messages = build_agent_messages(
                task=task,
                registry=self.registry,
                history=history,
                evidence_memory=self.evidence_memory,
                compressed_context=compressed_context,
            )
            raw_action = self.llm_client.complete(messages)

            try:
                action = parse_action(raw_action)
            except ActionParseError as exc:
                observation = f"Action parse failed: {exc}. Please output valid JSON action."
                history.append(
                    {
                        "step": str(step),
                        "action": "parse_error",
                        "observation": observation,
                    }
                )
                self._save_step(
                    step=step,
                    question=task,
                    action="parse_error",
                    args={"raw": raw_action},
                    observation=observation,
                    success=False,
                    started_at=started_at,
                    raw_action=raw_action,
                    phase="parse_error",
                    error=str(exc),
                )
                continue

            print(f"[agent_loop] step={step}, tool={action.tool}, args={action.args}")

            if action.tool == "final_answer":
                result = self._handle_final_answer(
                    step=step,
                    task=task,
                    action=action,
                    raw_action=raw_action,
                    history=history,
                    started_at=started_at,
                )
                if result is not None:
                    return result
                continue

            if not self.registry.has_tool(action.tool):
                observation = f"Unknown tool: {action.tool}"
                history.append(
                    {
                        "step": str(step),
                        "action": action.tool,
                        "observation": observation,
                    }
                )
                self._save_step(
                    step=step,
                    question=task,
                    action=action.tool,
                    args=action.args,
                    observation=observation,
                    success=False,
                    started_at=started_at,
                    raw_action=raw_action,
                    phase="tool_call",
                    error=observation,
                )
                continue

            result = self.registry.run(action.tool, **action.args)
            success = not (isinstance(result, dict) and result.get("success") is False)
            evidence_ids = extract_evidence_from_tool_result(
                tool_name=action.tool,
                args=action.args,
                result=result,
                evidence_memory=self.evidence_memory,
            )
            observation = format_observation(result)
            if evidence_ids:
                observation = observation + "\nEvidence: " + ", ".join(f"[{item}]" for item in evidence_ids)

            verification = self.verifier.verify_tool_observation(
                tool_name=action.tool,
                result=result,
                observation=observation,
                evidence_ids=evidence_ids,
            )
            history.append(
                {
                    "step": str(step),
                    "action": f"{action.tool}({action.args})",
                    "observation": observation,
                }
            )
            self.evidence_memory.save_jsonl(self.task_id)
            self._save_step(
                step=step,
                question=task,
                action=action.tool,
                args=action.args,
                observation=observation,
                success=success and verification.passed,
                started_at=started_at,
                evidence_ids=evidence_ids,
                raw_action=raw_action,
                phase="tool_call",
                verifier_result=verification,
                error=None if verification.passed else "; ".join(verification.issues),
            )

        verification = VerificationResult(
            passed=False,
            issues=["达到 max_steps，尚未生成通过 verifier 的 final_answer"],
            suggestion="请增加 max_steps 或检查工具调用与证据引用。",
        )
        return AgentRunResult(
            answer=f"达到 max_steps={self.max_steps}，尚未生成通过 verifier 的 final_answer。",
            history=history,
            evidence=self.evidence_memory.to_dicts(),
            verification=verification.to_dict(),
        )

    def _handle_final_answer(
        self,
        step: int,
        task: str,
        action: AgentAction,
        raw_action: str,
        history: list[dict[str, str]],
        started_at: float,
    ) -> AgentRunResult | None:
        answer = str(action.args.get("answer", ""))
        observation = answer or "final_answer called without answer"
        verification = self.verifier.verify_final_answer(answer, self.evidence_memory, task=task)
        used_ids = self._find_evidence_ids(answer)

        if verification.passed:
            self.evidence_memory.mark_used(used_ids)
            self.evidence_memory.save_jsonl(self.task_id)
            self._save_step(
                step=step,
                question=task,
                action=action.tool,
                args=action.args,
                observation=observation,
                success=bool(answer),
                started_at=started_at,
                evidence_ids=used_ids,
                raw_action=raw_action,
                phase="final_answer",
                verifier_result=verification,
            )
            return AgentRunResult(
                answer=observation,
                history=history,
                final_action=action,
                evidence=self.evidence_memory.to_dicts(),
                verification=verification.to_dict(),
            )

        feedback = self._format_verifier_feedback(verification)
        history.append(
            {
                "step": str(step),
                "action": "final_answer",
                "observation": feedback,
            }
        )
        self.evidence_memory.save_jsonl(self.task_id)
        self._save_step(
            step=step,
            question=task,
            action=action.tool,
            args=action.args,
            observation=feedback,
            success=False,
            started_at=started_at,
            evidence_ids=used_ids,
            raw_action=raw_action,
            phase="final_answer",
            verifier_result=verification,
            error="final_answer verification failed",
        )

        if step == self.max_steps:
            return AgentRunResult(
                answer=feedback,
                history=history,
                final_action=action,
                evidence=self.evidence_memory.to_dicts(),
                verification=verification.to_dict(),
            )
        return None

    def _save_step(
        self,
        step: int,
        question: str,
        action: str,
        args: dict[str, Any],
        observation: str,
        success: bool,
        started_at: float,
        evidence_ids: list[str] | None = None,
        raw_action: str = "",
        phase: str = "tool_call",
        verifier_result: VerificationResult | None = None,
        error: str | None = None,
    ) -> None:
        if self.trajectory_logger is None:
            return

        latency_ms = int((time.perf_counter() - started_at) * 1000)
        self.trajectory_logger.save_step(
            TrajectoryStep(
                task_id=self.task_id,
                step=step,
                question=question,
                phase=phase,
                llm_output=self._shorten(raw_action, 2000),
                action=action,
                args=args,
                observation_summary=self._shorten(observation, 2000),
                evidence_ids=evidence_ids or [],
                verifier=verifier_result.to_dict() if verifier_result else {},
                success=success,
                error=error,
                latency_ms=latency_ms,
            )
        )

    def _find_evidence_ids(self, text: str) -> list[str]:
        refs = extract_evidence_refs(text)
        existing_ids = {item.evidence_id for item in self.evidence_memory.list()}
        return [item for item in refs if item in existing_ids]

    def _format_verifier_feedback(self, verification: VerificationResult) -> str:
        rows = ["Verifier feedback: final_answer 未通过检查。"]
        for issue in verification.issues:
            rows.append(f"- {issue}")
        if verification.suggestion:
            rows.append(f"Suggestion: {verification.suggestion}")
        if verification.suggested_next_action:
            rows.append(f"Suggested next action: {verification.suggested_next_action}")
        return "\n".join(rows)

    def _shorten(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "..."
