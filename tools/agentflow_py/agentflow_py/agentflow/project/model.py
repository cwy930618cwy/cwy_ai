"""项目数据模型 - 移植自 Go 的 internal/project/model.go"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any


# ==== 状态枚举 ====

class ProjectStatus:
    """项目状态"""
    DRAFT = "draft"
    IDEA_REVIEW = "idea_review"
    MACRO_SUPPLEMENT = "macro_supplement"
    RESEARCH = "research"
    MVP = "mvp"
    P1 = "p1"
    P2 = "p2"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class PhaseGateStatus:
    """阶段门控状态"""
    PENDING = "pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISION_REQUESTED = "revision_requested"


class PhaseGoalLinkStatus:
    """Phase-Goal 关联状态"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class LinkType:
    """关联类型"""
    AUTO_GENERATED = "auto_generated"
    MANUAL_LINKED = "manual_linked"
    CONDITION_BOUND = "condition_bound"


class PhaseStatus:
    """阶段状态"""
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    SKIPPED = "skipped"


# ==== 数据模型 ====

@dataclass
class EntryCondition:
    """准入条件"""
    description: str = ""
    is_met: bool = False

    def to_dict(self) -> Dict:
        return {"description": self.description, "is_met": self.is_met}


@dataclass
class ExitCondition:
    """准出条件（扩展版，支持绑定 Goal/Task）"""
    description: str = ""
    is_met: bool = False
    bound_goal_id: str = ""
    bound_task_id: str = ""
    auto_check: bool = False

    def to_dict(self) -> Dict:
        d = {"description": self.description, "is_met": self.is_met, "auto_check": self.auto_check}
        if self.bound_goal_id:
            d["bound_goal_id"] = self.bound_goal_id
        if self.bound_task_id:
            d["bound_task_id"] = self.bound_task_id
        return d


@dataclass
class Deliverable:
    """产出物"""
    name: str = ""
    description: str = ""
    content: str = ""
    is_completed: bool = False

    def to_dict(self) -> Dict:
        d = {"name": self.name, "is_completed": self.is_completed}
        if self.description:
            d["description"] = self.description
        if self.content:
            d["content"] = self.content
        return d


@dataclass
class HumanFeedback:
    """人类反馈（结构化存储）"""
    comment: str = ""
    revision_items: List[str] = field(default_factory=list)
    metadata: Dict[str, str] = field(default_factory=dict)
    submitted_at: str = ""

    def to_dict(self) -> Dict:
        d = {"comment": self.comment, "submitted_at": self.submitted_at}
        if self.revision_items:
            d["revision_items"] = self.revision_items
        if self.metadata:
            d["metadata"] = self.metadata
        return d


@dataclass
class PhaseDefinition:
    """阶段定义（模板）"""
    name: str = ""
    description: str = ""
    order: int = 0
    default_entry_conditions: List[EntryCondition] = field(default_factory=list)
    default_exit_conditions: List[ExitCondition] = field(default_factory=list)
    required_deliverables: List[str] = field(default_factory=list)
    auto_generate_goals: bool = False

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "description": self.description,
            "order": self.order,
            "default_entry_conditions": [c.to_dict() for c in self.default_entry_conditions],
            "default_exit_conditions": [c.to_dict() for c in self.default_exit_conditions],
            "required_deliverables": self.required_deliverables,
            "auto_generate_goals": self.auto_generate_goals,
        }


@dataclass
class PhaseInfo:
    """阶段信息（Project 中存储的阶段状态）"""
    name: str = ""
    description: str = ""
    order: int = 0
    status: str = PhaseStatus.PENDING
    parent_phase: str = ""
    children: List["PhaseInfo"] = field(default_factory=list)

    def to_dict(self) -> Dict:
        d = {
            "name": self.name,
            "order": self.order,
            "status": self.status,
        }
        if self.description:
            d["description"] = self.description
        if self.parent_phase:
            d["parent_phase"] = self.parent_phase
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        return d


@dataclass
class Project:
    """项目（高于 Goal 的抽象层）"""
    id: str = ""
    title: str = ""
    description: str = ""
    vision: str = ""
    status: str = ProjectStatus.DRAFT
    current_phase: str = ""
    phases: List[PhaseInfo] = field(default_factory=list)
    owner_agent_id: str = ""
    tags: List[str] = field(default_factory=list)
    priority: int = 5
    risk_list: List[str] = field(default_factory=list)
    tech_stack: List[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "vision": self.vision,
            "status": self.status,
            "current_phase": self.current_phase,
            "phases": [p.to_dict() for p in self.phases],
            "owner_agent_id": self.owner_agent_id,
            "tags": self.tags,
            "priority": self.priority,
            "risk_list": self.risk_list,
            "tech_stack": self.tech_stack,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class PhaseGate:
    """阶段门控"""
    id: str = ""
    project_id: str = ""
    phase_name: str = ""
    status: str = PhaseGateStatus.PENDING
    entry_conditions: List[EntryCondition] = field(default_factory=list)
    exit_conditions: List[ExitCondition] = field(default_factory=list)
    deliverables: List[Deliverable] = field(default_factory=list)
    reviewer_comment: str = ""
    human_feedback: Optional[HumanFeedback] = None
    linked_goal_ids: List[str] = field(default_factory=list)
    linked_task_ids: List[str] = field(default_factory=list)
    approved_by: str = ""
    approved_at: str = ""
    created_at: str = ""

    def to_dict(self) -> Dict:
        d = {
            "id": self.id,
            "project_id": self.project_id,
            "phase_name": self.phase_name,
            "status": self.status,
            "created_at": self.created_at,
        }
        if self.entry_conditions:
            d["entry_conditions"] = [c.to_dict() for c in self.entry_conditions]
        if self.exit_conditions:
            d["exit_conditions"] = [c.to_dict() for c in self.exit_conditions]
        if self.deliverables:
            d["deliverables"] = [deliv.to_dict() for deliv in self.deliverables]
        if self.reviewer_comment:
            d["reviewer_comment"] = self.reviewer_comment
        if self.human_feedback:
            d["human_feedback"] = self.human_feedback.to_dict()
        if self.linked_goal_ids:
            d["linked_goal_ids"] = self.linked_goal_ids
        if self.linked_task_ids:
            d["linked_task_ids"] = self.linked_task_ids
        if self.approved_by:
            d["approved_by"] = self.approved_by
        if self.approved_at:
            d["approved_at"] = self.approved_at
        return d


@dataclass
class PhaseGoalLink:
    """Phase 与 Goal/Task 的关联关系"""
    project_id: str = ""
    phase_name: str = ""
    goal_id: str = ""
    task_ids: List[str] = field(default_factory=list)
    link_type: str = LinkType.AUTO_GENERATED
    linked_condition_index: int = -1
    linked_deliverable_index: int = -1
    status: str = PhaseGoalLinkStatus.PENDING
    linked_at: str = ""

    def to_dict(self) -> Dict:
        d = {
            "project_id": self.project_id,
            "phase_name": self.phase_name,
            "goal_id": self.goal_id,
            "link_type": self.link_type,
            "status": self.status,
            "linked_at": self.linked_at,
        }
        if self.task_ids:
            d["task_ids"] = self.task_ids
        if self.linked_condition_index >= 0:
            d["linked_condition_index"] = self.linked_condition_index
        if self.linked_deliverable_index >= 0:
            d["linked_deliverable_index"] = self.linked_deliverable_index
        return d


@dataclass
class PhaseHistory:
    """阶段历史记录"""
    id: str = ""
    project_id: str = ""
    phase_name: str = ""
    action: str = ""  # approved/rejected/revision_requested/submitted
    actor: str = ""
    comment: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> Dict:
        d = {
            "id": self.id,
            "project_id": self.project_id,
            "phase_name": self.phase_name,
            "action": self.action,
            "actor": self.actor,
            "created_at": self.created_at,
        }
        if self.comment:
            d["comment"] = self.comment
        if self.details:
            d["details"] = self.details
        return d


@dataclass
class PhaseProgress:
    """Phase 完成进度统计"""
    project_id: str = ""
    phase_name: str = ""
    total_goals: int = 0
    completed_goals: int = 0
    total_tasks: int = 0
    completed_tasks: int = 0
    percentage: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "project_id": self.project_id,
            "phase_name": self.phase_name,
            "total_goals": self.total_goals,
            "completed_goals": self.completed_goals,
            "total_tasks": self.total_tasks,
            "completed_tasks": self.completed_tasks,
            "percentage": self.percentage,
        }


@dataclass
class TaskWithStatus:
    """Task 及其状态信息（用于 Phase 概览）"""
    task_id: str = ""
    title: str = ""
    status: str = ""
    progress: float = 0.0
    claimed_by: str = ""

    def to_dict(self) -> Dict:
        d = {"task_id": self.task_id, "status": self.status, "progress": self.progress}
        if self.title:
            d["title"] = self.title
        if self.claimed_by:
            d["claimed_by"] = self.claimed_by
        return d


@dataclass
class GoalWithTasks:
    """Goal 及其 Task 列表（用于 Phase 概览）"""
    goal_id: str = ""
    title: str = ""
    status: str = ""
    progress: float = 0.0
    tasks: List[TaskWithStatus] = field(default_factory=list)
    total_tasks: int = 0
    completed_tasks: int = 0

    def to_dict(self) -> Dict:
        return {
            "goal_id": self.goal_id,
            "title": self.title,
            "status": self.status,
            "progress": self.progress,
            "tasks": [t.to_dict() for t in self.tasks],
            "total_tasks": self.total_tasks,
            "completed_tasks": self.completed_tasks,
        }


@dataclass
class PhaseOverview:
    """Phase 概览（包含关联的 Goal/Task 完整信息）"""
    project_id: str = ""
    phase_name: str = ""
    goals: List[GoalWithTasks] = field(default_factory=list)
    progress: PhaseProgress = field(default_factory=PhaseProgress)

    def to_dict(self) -> Dict:
        return {
            "project_id": self.project_id,
            "phase_name": self.phase_name,
            "goals": [g.to_dict() for g in self.goals],
            "progress": self.progress.to_dict() if self.progress else {},
        }


# ==== 参数类型 ====

@dataclass
class CreateProjectParams:
    """创建项目参数"""
    title: str = ""
    description: str = ""
    vision: str = ""
    priority: int = 5
    tags: List[str] = field(default_factory=list)
    template: str = "standard"


@dataclass
class UpdateProjectParams:
    """更新项目参数"""
    project_id: str = ""
    fields: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DeleteProjectParams:
    """删除项目参数"""
    project_id: str = ""
    cascade: bool = False
    confirm: str = ""


@dataclass
class ListProjectsParams:
    """项目列表参数"""
    status: str = ""
    tags: List[str] = field(default_factory=list)
    page: int = 1
    page_size: int = 20


@dataclass
class ApprovePhaseParams:
    """审批通过参数"""
    project_id: str = ""
    phase_name: str = ""
    comment: str = ""
    approved_by: str = ""


@dataclass
class RejectPhaseParams:
    """审批驳回参数"""
    project_id: str = ""
    phase_name: str = ""
    comment: str = ""
    feedback: Optional[HumanFeedback] = None


@dataclass
class RequestRevisionParams:
    """请求修订参数"""
    project_id: str = ""
    phase_name: str = ""
    comment: str = ""
    revision_items: List[str] = field(default_factory=list)


@dataclass
class SubmitPhaseReviewParams:
    """提交阶段审阅参数"""
    project_id: str = ""
    phase_name: str = ""
    deliverables: List[Deliverable] = field(default_factory=list)
    summary: str = ""


@dataclass
class LinkGoalToPhaseParams:
    """关联 Goal 到 Phase 参数"""
    project_id: str = ""
    phase_name: str = ""
    goal_id: str = ""
    link_type: str = LinkType.MANUAL_LINKED


@dataclass
class BindConditionToTaskParams:
    """绑定准出条件到 Task 参数"""
    project_id: str = ""
    phase_name: str = ""
    condition_index: int = 0
    task_id: str = ""
    goal_id: str = ""
    auto_check: bool = True


@dataclass
class LinkTaskToPhaseParams:
    """关联 Task 到 Phase 参数"""
    project_id: str = ""
    phase_name: str = ""
    goal_id: str = ""
    task_id: str = ""


# ==== 状态转换 ====

VALID_PROJECT_STATUS_TRANSITIONS: Dict[str, List[str]] = {
    ProjectStatus.DRAFT: [ProjectStatus.IDEA_REVIEW, ProjectStatus.CANCELLED],
    ProjectStatus.IDEA_REVIEW: [ProjectStatus.MACRO_SUPPLEMENT, ProjectStatus.DRAFT, ProjectStatus.CANCELLED],
    ProjectStatus.MACRO_SUPPLEMENT: [ProjectStatus.RESEARCH, ProjectStatus.IDEA_REVIEW, ProjectStatus.CANCELLED],
    ProjectStatus.RESEARCH: [ProjectStatus.MVP, ProjectStatus.MACRO_SUPPLEMENT, ProjectStatus.CANCELLED],
    ProjectStatus.MVP: [ProjectStatus.P1, ProjectStatus.RESEARCH, ProjectStatus.CANCELLED],
    ProjectStatus.P1: [ProjectStatus.P2, ProjectStatus.MVP, ProjectStatus.CANCELLED],
    ProjectStatus.P2: [ProjectStatus.COMPLETED, ProjectStatus.P1, ProjectStatus.CANCELLED],
    ProjectStatus.COMPLETED: [],
    ProjectStatus.CANCELLED: [],
}

VALID_PHASE_GATE_STATUS_TRANSITIONS: Dict[str, List[str]] = {
    PhaseGateStatus.PENDING: [PhaseGateStatus.APPROVED, PhaseGateStatus.REJECTED, PhaseGateStatus.REVISION_REQUESTED],
    PhaseGateStatus.APPROVED: [],
    PhaseGateStatus.REJECTED: [PhaseGateStatus.PENDING],
    PhaseGateStatus.REVISION_REQUESTED: [PhaseGateStatus.PENDING],
}


def is_valid_project_status_transition(from_status: str, to_status: str) -> bool:
    """检查项目状态转换是否合法"""
    valid_targets = VALID_PROJECT_STATUS_TRANSITIONS.get(from_status, [])
    return to_status in valid_targets


def is_valid_phase_gate_status_transition(from_status: str, to_status: str) -> bool:
    """检查 PhaseGate 状态转换是否合法"""
    valid_targets = VALID_PHASE_GATE_STATUS_TRANSITIONS.get(from_status, [])
    return to_status in valid_targets
