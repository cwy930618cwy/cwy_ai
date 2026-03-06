from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class TaskStatus:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    INTERRUPTED = "interrupted"
    REVIEW = "review"

    ALL = [PENDING, RUNNING, COMPLETED, FAILED, BLOCKED, INTERRUPTED, REVIEW]


@dataclass
class TestDesign:
    unit_tests: List[str] = field(default_factory=list)
    integration_tests: List[str] = field(default_factory=list)
    acceptance_criteria: List[str] = field(default_factory=list)

    def to_dict(self):
        return {
            "unit_tests": self.unit_tests,
            "integration_tests": self.integration_tests,
            "acceptance_criteria": self.acceptance_criteria,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TestDesign":
        return cls(
            unit_tests=d.get("unit_tests", []),
            integration_tests=d.get("integration_tests", []),
            acceptance_criteria=d.get("acceptance_criteria", []),
        )


@dataclass
class Task:
    id: str = ""
    goal_id: str = ""
    parent_task_id: str = ""
    title: str = ""
    description: str = ""
    status: str = TaskStatus.PENDING
    progress: float = 0.0
    skill_type: str = ""
    phase: str = ""
    dependencies: List[str] = field(default_factory=list)
    prerequisites: List[str] = field(default_factory=list)
    estimated_tokens: int = 0
    difficulty: int = 5
    priority: int = 5
    claimed_by: str = ""
    test_design: Optional[TestDesign] = None
    artifacts: List[str] = field(default_factory=list)
    summary: str = ""
    tokens_used: int = 0
    retry_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    completed_at: str = ""
    interrupted_at: str = ""
    last_heartbeat: str = ""
    # 调度增强字段
    deadline: str = ""
    # Review 相关字段
    review_result: str = ""
    reviewed_by: str = ""
    review_comment: str = ""
    reviewed_at: str = ""

    def to_dict(self) -> Dict:
        d = {
            "id": self.id,
            "goal_id": self.goal_id,
            "parent_task_id": self.parent_task_id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "progress": self.progress,
            "skill_type": self.skill_type,
            "phase": self.phase,
            "dependencies": self.dependencies,
            "prerequisites": self.prerequisites,
            "estimated_tokens": self.estimated_tokens,
            "difficulty": self.difficulty,
            "priority": self.priority,
            "claimed_by": self.claimed_by,
            "artifacts": self.artifacts,
            "summary": self.summary,
            "tokens_used": self.tokens_used,
            "retry_count": self.retry_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.test_design:
            d["test_design"] = self.test_design.to_dict()
        if self.completed_at:
            d["completed_at"] = self.completed_at
        if self.interrupted_at:
            d["interrupted_at"] = self.interrupted_at
        if self.last_heartbeat:
            d["last_heartbeat"] = self.last_heartbeat
        if self.deadline:
            d["deadline"] = self.deadline
        if self.review_result:
            d["review_result"] = self.review_result
        if self.reviewed_by:
            d["reviewed_by"] = self.reviewed_by
        if self.review_comment:
            d["review_comment"] = self.review_comment
        if self.reviewed_at:
            d["reviewed_at"] = self.reviewed_at
        return d


@dataclass
class Checkpoint:
    task_id: str = ""
    agent_id: str = ""
    progress: float = 0.0
    completed_items: List[str] = field(default_factory=list)
    pending_items: List[str] = field(default_factory=list)
    modified_files: List[str] = field(default_factory=list)
    notes: str = ""
    saved_at: str = ""

    def to_dict(self) -> Dict:
        return {
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "progress": self.progress,
            "completed_items": self.completed_items,
            "pending_items": self.pending_items,
            "modified_files": self.modified_files,
            "notes": self.notes,
            "saved_at": self.saved_at,
        }


@dataclass
class AutoCheckpoint:
    task_id: str = ""
    agent_id: str = ""
    modified_files: List[str] = field(default_factory=list)
    read_files: List[str] = field(default_factory=list)
    tool_call_count: int = 0
    last_tool_call: str = ""
    generated_at: str = ""

    def to_dict(self) -> Dict:
        return {
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "modified_files": self.modified_files,
            "read_files": self.read_files,
            "tool_call_count": self.tool_call_count,
            "last_tool_call": self.last_tool_call,
            "generated_at": self.generated_at,
        }
