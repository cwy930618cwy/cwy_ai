from dataclasses import dataclass, field
from typing import List, Optional


class FixStatus:
    ACTIVE = "active"
    RESOLVED = "resolved"
    ABANDONED = "abandoned"


class AttemptResult:
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    BLOCKED = "blocked"


@dataclass
class FixAttempt:
    id: str = ""
    session_id: str = ""
    approach: str = ""
    reasoning: str = ""
    result: str = ""
    result_detail: str = ""
    label: str = ""  # good/bad/misleading
    modified_files: List[str] = field(default_factory=list)
    code_changes: str = ""
    confidence: float = 0.5
    created_at: str = ""

    def to_dict(self):
        return {
            "id": self.id,
            "session_id": self.session_id,
            "approach": self.approach,
            "reasoning": self.reasoning,
            "result": self.result,
            "result_detail": self.result_detail,
            "label": self.label,
            "modified_files": self.modified_files,
            "code_changes": self.code_changes,
            "confidence": self.confidence,
            "created_at": self.created_at,
        }


@dataclass
class FixSession:
    id: str = ""
    task_id: str = ""
    agent_id: str = ""
    problem: str = ""
    error_msg: str = ""
    error_type: str = ""
    status: str = FixStatus.ACTIVE
    resolution: str = ""
    attempt_count: int = 0
    final_experience: str = ""
    tags: List[str] = field(default_factory=list)
    created_at: str = ""
    resolved_at: str = ""

    def to_dict(self):
        return {
            "id": self.id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "problem": self.problem,
            "error_msg": self.error_msg,
            "error_type": self.error_type,
            "status": self.status,
            "resolution": self.resolution,
            "attempt_count": self.attempt_count,
            "final_experience": self.final_experience,
            "tags": self.tags,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
        }
