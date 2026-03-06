from dataclasses import dataclass, field
from typing import Dict, List, Optional

AgentRole = str

ROLE_EXECUTOR = "executor"
ROLE_AUDITOR = "auditor"
ROLE_OPERATOR = "operator"

ALL_ROLES = [ROLE_EXECUTOR, ROLE_AUDITOR, ROLE_OPERATOR]


@dataclass
class RoleInfo:
    role: AgentRole
    name: str
    description: str
    core_tools: List[str]
    extra_tools: List[str]
    workflow: str


_ROLE_DEFINITIONS: Dict[str, RoleInfo] = {
    ROLE_EXECUTOR: RoleInfo(
        role=ROLE_EXECUTOR,
        name="执行者 (Executor)",
        description="负责领取并执行开发任务的Agent。核心职责：理解需求、编写代码、运行测试、汇报结果。",
        core_tools=[
            "claim_task", "report_task_result", "update_task_progress",
            "save_checkpoint", "split_task",
            "get_task_context", "get_global_rules", "get_artifact", "search_context",
            "list_tasks", "get_task_detail",
            "report_experience", "query_fix_experience", "report_fix_attempt", "close_fix_session",
        ],
        extra_tools=[
            "get_dashboard", "get_skill", "release_task",
            "update_fix_attempt_label", "feedback_experience",
        ],
        workflow="claim_task → [get_task_context] → 编码执行 → update_task_progress → save_checkpoint → report_task_result → [report_experience]",
    ),
    ROLE_AUDITOR: RoleInfo(
        role=ROLE_AUDITOR,
        name="审计者 (Auditor)",
        description="负责代码评审、技能质量审计和进化管理的Agent。核心职责：Review产出物、审核Skill DNA、管理进化提案。",
        core_tools=[
            "audit_skill_quality", "distill_and_evolve",
            "get_skill", "list_skills", "get_artifact",
            "claim_task", "report_task_result", "list_tasks", "get_task_detail", "create_tasks",
            "report_experience", "feedback_experience", "get_evolution_status",
        ],
        extra_tools=[
            "approve_evolution", "trigger_evolution", "snapshot_agent",
            "get_experiences", "create_skill", "update_skill",
            "get_dashboard", "search_context", "get_global_rules",
        ],
        workflow="list_tasks(review) → claim_task → get_artifact → 审查代码 → report_task_result → audit_skill_quality → distill_and_evolve",
    ),
    ROLE_OPERATOR: RoleInfo(
        role=ROLE_OPERATOR,
        name="运维者 (Operator)",
        description="负责系统监控、健康检查、故障恢复和目标管理的Agent。",
        core_tools=[
            "get_dashboard", "get_health_check", "get_evolution_status",
            "create_goal", "update_goal", "delete_goal", "get_goal", "list_goals",
            "create_tasks", "list_tasks", "update_task", "release_task",
        ],
        extra_tools=[
            "get_safety_report", "rollback_to_archive", "snapshot_agent", "get_extended_tools",
            "get_skill", "list_skills", "get_task_detail",
        ],
        workflow="get_dashboard → get_health_check → [create_goal → create_tasks] → 管理任务生命周期 → [get_safety_report → rollback_to_archive]",
    ),
}


def get_role_info(role: str) -> Optional[RoleInfo]:
    return _ROLE_DEFINITIONS.get(role)


def get_all_role_infos() -> List[RoleInfo]:
    return [_ROLE_DEFINITIONS[r] for r in ALL_ROLES if r in _ROLE_DEFINITIONS]
