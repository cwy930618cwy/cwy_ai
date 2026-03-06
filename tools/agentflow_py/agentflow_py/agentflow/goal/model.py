from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


class GoalStatus:
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class Goal:
    id: str = ""
    title: str = ""
    description: str = ""
    status: str = GoalStatus.PENDING
    priority: int = 5
    parent_goal_id: str = ""
    phases: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    progress: float = 0.0
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "priority": self.priority,
            "parent_goal_id": self.parent_goal_id,
            "phases": self.phases,
            "tags": self.tags,
            "progress": self.progress,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
