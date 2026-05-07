from agent.evidence_memory import EvidenceMemory


def final_answer(answer: str, evidence_memory: EvidenceMemory) -> dict[str, object]:
    print("[final_answer] build final answer with evidence")
    return {
        "answer": answer,
        "evidence": evidence_memory.to_dicts(),
    }

