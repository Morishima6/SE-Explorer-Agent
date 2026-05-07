import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class TrajectoryStep:
    task_id: str
    step: int
    action: str
    args: dict[str, Any]
    observation_summary: str
    question: str = ""
    phase: str = "tool_call"
    llm_output: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    verifier: dict[str, object] = field(default_factory=dict)
    success: bool = True
    error: str | None = None
    latency_ms: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


class TrajectoryLogger:
    def __init__(self, output_dir: str = "outputs/trajectories") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def reset_task(self, task_id: str) -> Path:
        output_path = self.output_dir / f"{task_id}.jsonl"
        if output_path.exists():
            print(f"[trajectory] reset task log: {output_path}")
            output_path.unlink()
        return output_path

    def save_step(self, step: TrajectoryStep) -> Path:
        output_path = self.output_dir / f"{step.task_id}.jsonl"
        print(f"[trajectory] save step {step.step} to {output_path}")
        with output_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(asdict(step), ensure_ascii=False) + "\n")
        return output_path
