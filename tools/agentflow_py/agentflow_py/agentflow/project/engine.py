"""项目生命周期引擎 - 移植自 Go 的 internal/project/engine.go"""
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple, TYPE_CHECKING

from agentflow.common.errors import NotFoundError, InvalidParamError
from agentflow.project.model import (
    Project,
    PhaseGate,
    PhaseGoalLink,
    PhaseHistory,
    PhaseProgress,
    PhaseOverview,
    GoalWithTasks,
    TaskWithStatus,
    PhaseInfo,
    EntryCondition,
    ExitCondition,
    Deliverable,
    HumanFeedback,
    ProjectStatus,
    PhaseGateStatus,
    PhaseGoalLinkStatus,
    PhaseStatus,
    LinkType,
)
from agentflow.project.store import ProjectStore
from agentflow.project.generator import Generator
from agentflow.common.id_gen import (
    generate_phase_history_id,
)

if TYPE_CHECKING:
    from agentflow.goal import GoalStore


# ---- 阶段模板定义 ----

@dataclass
class PhaseDefinition:
    """阶段定义模板"""
    name: str
    description: str
    order: int
    default_entry_conditions: List[EntryCondition] = field(default_factory=list)
    default_exit_conditions: List[ExitCondition] = field(default_factory=list)
    required_deliverables: List[str] = field(default_factory=list)
    auto_generate_goals: bool = False


# 标准阶段模板（Idea → 宏观补充 → 调研 → MVP → P1 → P2）
DEFAULT_PHASE_TEMPLATE: List[PhaseDefinition] = [
    PhaseDefinition(
        name="idea",
        description="Idea 阶段：将模糊想法结构化，明确核心目标和范围",
        order=1,
        default_entry_conditions=[
            EntryCondition(description="项目已创建", is_met=True),
        ],
        default_exit_conditions=[
            ExitCondition(description="项目蓝图已生成（愿景、核心功能、目标用户）"),
            ExitCondition(description="初步技术约束已明确"),
            ExitCondition(description="风险清单已整理"),
        ],
        required_deliverables=["项目蓝图文档"],
        auto_generate_goals=False,
    ),
    PhaseDefinition(
        name="macro_supplement",
        description="宏观补充阶段：细化项目规划，拆解子目标，评估资源",
        order=2,
        default_entry_conditions=[
            EntryCondition(description="Idea 阶段已审批通过"),
        ],
        default_exit_conditions=[
            ExitCondition(description="子目标树已拆解"),
            ExitCondition(description="技术栈已确定"),
            ExitCondition(description="依赖分析已完成"),
            ExitCondition(description="里程碑规划已制定"),
        ],
        required_deliverables=["宏观规划文档", "子目标树"],
        auto_generate_goals=True,
    ),
    PhaseDefinition(
        name="research",
        description="调研阶段：技术方案对比、可行性分析、原型验证",
        order=3,
        default_entry_conditions=[
            EntryCondition(description="宏观补充阶段已审批通过"),
        ],
        default_exit_conditions=[
            ExitCondition(description="技术方案对比报告已完成（至少3种方案）"),
            ExitCondition(description="可行性分析已完成"),
            ExitCondition(description="依赖库/框架评估已完成"),
            ExitCondition(description="原型验证计划已制定"),
        ],
        required_deliverables=["调研报告", "技术选型决策"],
        auto_generate_goals=True,
    ),
    PhaseDefinition(
        name="mvp",
        description="MVP 阶段：实现最小可行产品，验证核心功能路径",
        order=4,
        default_entry_conditions=[
            EntryCondition(description="调研阶段已审批通过"),
            EntryCondition(description="技术选型已确定"),
        ],
        default_exit_conditions=[
            ExitCondition(description="核心功能已实现并可运行"),
            ExitCondition(description="基础测试已通过"),
            ExitCondition(description="MVP 演示文档已准备"),
        ],
        required_deliverables=["MVP 可运行版本", "核心功能演示"],
        auto_generate_goals=True,
    ),
    PhaseDefinition(
        name="p1",
        description="P1 稳定化阶段：完善功能、修复问题、提升稳定性",
        order=5,
        default_entry_conditions=[
            EntryCondition(description="MVP 阶段已审批通过"),
        ],
        default_exit_conditions=[
            ExitCondition(description="P1 功能列表已全部实现"),
            ExitCondition(description="测试覆盖率达标"),
            ExitCondition(description="已知 Bug 已修复"),
        ],
        required_deliverables=["P1 版本", "测试报告"],
        auto_generate_goals=True,
    ),
    PhaseDefinition(
        name="p2",
        description="P2 完善阶段：性能优化、文档完善、生产就绪",
        order=6,
        default_entry_conditions=[
            EntryCondition(description="P1 阶段已审批通过"),
        ],
        default_exit_conditions=[
            ExitCondition(description="性能指标达标"),
            ExitCondition(description="文档已完善"),
            ExitCondition(description="生产环境部署就绪"),
        ],
        required_deliverables=["P2 版本", "完整文档", "部署指南"],
        auto_generate_goals=True,
    ),
]

# 阶段名到项目状态的映射
PHASE_TO_PROJECT_STATUS: Dict[str, str] = {
    "idea": ProjectStatus.IDEA_REVIEW,
    "macro_supplement": ProjectStatus.MACRO_SUPPLEMENT,
    "research": ProjectStatus.RESEARCH,
    "mvp": ProjectStatus.MVP,
    "p1": ProjectStatus.P1,
    "p2": ProjectStatus.P2,
}


# ---- 参数类型定义 ----

@dataclass
class CreateProjectParams:
    """创建项目参数"""
    title: str
    description: str = ""
    vision: str = ""
    template: str = "standard"
    priority: int = 5
    tags: Optional[List[str]] = None


@dataclass
class SubmitPhaseReviewParams:
    """提交阶段审阅参数"""
    project_id: str
    phase_name: str
    summary: str = ""
    deliverables: Optional[List[Deliverable]] = None


@dataclass
class ApprovePhaseParams:
    """审批通过阶段参数"""
    project_id: str
    phase_name: str
    approved_by: str = ""
    comment: str = ""


@dataclass
class RejectPhaseParams:
    """审批驳回阶段参数"""
    project_id: str
    phase_name: str
    comment: str
    feedback: Optional[HumanFeedback] = None


@dataclass
class RequestRevisionParams:
    """请求修订参数"""
    project_id: str
    phase_name: str
    comment: str
    revision_items: Optional[List[str]] = None


@dataclass
class BindConditionToTaskParams:
    """绑定准出条件到任务参数"""
    project_id: str
    phase_name: str
    condition_index: int
    task_id: str = ""
    goal_id: str = ""
    auto_check: bool = True


class Engine:
    """项目生命周期引擎
    
    负责管理项目的完整生命周期，包括：
    - 项目创建与初始化
    - 阶段推进逻辑
    - PhaseGate 审批流程
    - Goal 自动生成与 Phase 关联
    - 状态同步
    - 动态阶段管理
    """

    def __init__(
        self,
        store: ProjectStore,
        goal_store: "GoalStore",
        logger: logging.Logger,
        task_store: Optional[Any] = None,
    ):
        self._store = store
        self._goal_store = goal_store
        self._logger = logger
        self._generator = Generator()
        self._task_store = task_store
        # 将 task_store 注入 project_store
        if task_store is not None and self._store._task_store is None:
            self._store._task_store = task_store

    # ---- 项目创建与初始化 ----

    async def create_project(self, params: CreateProjectParams) -> Project:
        """创建项目并初始化
        
        注意：新建流程时不预置任何阶段，由用户手动添加
        """
        if not params.title:
            raise InvalidParamError("title 不能为空")

        project = await self._store.create_project(
            title=params.title,
            description=params.description,
            vision=params.vision,
            template=params.template,
            priority=params.priority,
            tags=params.tags,
        )

        # 更新为空阶段列表，设置初始状态
        project = await self._store.update_project(project.id, {
            "phases": [],
            "current_phase": "",
            "status": ProjectStatus.IDEA_REVIEW,
        })

        self._logger.info(f"项目已初始化 id={project.id} phases={len(project.phases)}")
        return project

    # ---- 阶段推进逻辑 ----

    async def advance_phase(self, project_id: str) -> Project:
        """推进到下一阶段（审批通过后调用）"""
        project = await self._store.get_project(project_id)

        # 找到当前阶段索引
        current_idx = -1
        for i, phase in enumerate(project.phases):
            if phase.name == project.current_phase:
                current_idx = i
                break

        if current_idx == -1:
            raise InvalidParamError(f"当前阶段 {project.current_phase} 不存在")

        # 检查当前阶段的 PhaseGate 是否已审批通过
        gate = await self._store.get_phase_gate(project_id, project.current_phase)
        if gate.status != PhaseGateStatus.APPROVED:
            raise InvalidParamError(
                f"当前阶段 {project.current_phase} 的 PhaseGate 尚未审批通过"
                f"（当前状态: {gate.status}）"
            )

        # 检查准出条件是否全部满足
        for i, cond in enumerate(gate.exit_conditions):
            if not cond.is_met:
                raise InvalidParamError(
                    f"准出条件 [{i}] '{cond.description}' 尚未满足"
                )

        # 更新当前阶段状态为 completed
        phases = list(project.phases)
        phases[current_idx].status = PhaseStatus.COMPLETED

        # 找下一阶段
        next_idx = current_idx + 1
        if next_idx >= len(phases):
            # 所有阶段完成，项目完成
            project = await self._store.update_project(project_id, {
                "phases": phases,
                "status": ProjectStatus.COMPLETED,
            })
            self._logger.info(f"项目所有阶段已完成 project_id={project_id}")
            return project

        # 激活下一阶段
        phases[next_idx].status = PhaseStatus.ACTIVE
        next_phase_name = phases[next_idx].name

        # 确定下一阶段对应的项目状态
        next_status = PHASE_TO_PROJECT_STATUS.get(next_phase_name, project.status)

        project = await self._store.update_project(project_id, {
            "phases": phases,
            "current_phase": next_phase_name,
            "status": next_status,
        })

        self._logger.info(
            f"阶段已推进 project_id={project_id} "
            f"from={project.phases[current_idx].name} to={next_phase_name}"
        )
        return project

    # ---- PhaseGate 审批流程 ----

    async def submit_for_review(self, params: SubmitPhaseReviewParams) -> PhaseGate:
        """提交阶段审阅"""
        if not params.project_id or not params.phase_name:
            raise InvalidParamError("project_id 和 phase_name 不能为空")

        gate = await self._store.get_phase_gate(params.project_id, params.phase_name)

        # 只有 pending、revision_requested 或 rejected 状态才能提交审阅
        valid_statuses = [
            PhaseGateStatus.PENDING,
            PhaseGateStatus.REVISION_REQUESTED,
            PhaseGateStatus.REJECTED,
        ]
        if gate.status not in valid_statuses:
            raise InvalidParamError(
                f"PhaseGate 当前状态 {gate.status} 不允许提交审阅"
            )

        updates: Dict[str, Any] = {}

        # 更新产出物
        if params.deliverables:
            gate.deliverables = params.deliverables
            updates["deliverables"] = params.deliverables

        # rejected 或 revision_requested 状态重新提交时，重置为 pending
        if gate.status in (PhaseGateStatus.REJECTED, PhaseGateStatus.REVISION_REQUESTED):
            updates["status"] = PhaseGateStatus.PENDING

        # 添加提交历史
        history = PhaseHistory(
            id=generate_phase_history_id(),
            project_id=params.project_id,
            phase_name=params.phase_name,
            action="submitted",
            actor="agent",
            comment=params.summary,
            created_at=datetime.now().isoformat(),
        )
        await self._store.add_phase_history(history)

        if updates:
            for k, v in updates.items():
                setattr(gate, k, v)
            gate = await self._store.save_phase_gate(gate)

        return gate

    async def approve_phase(self, params: ApprovePhaseParams) -> Project:
        """审批通过阶段"""
        if not params.project_id or not params.phase_name:
            raise InvalidParamError("project_id 和 phase_name 不能为空")

        gate = await self._store.get_phase_gate(params.project_id, params.phase_name)

        # 校验状态转换合法性
        if not self._is_valid_status_transition(gate.status, PhaseGateStatus.APPROVED):
            raise InvalidParamError(
                f"PhaseGate 状态 {gate.status} 不能转换为 approved"
            )

        # 自动将所有准出条件标记为满足
        for cond in gate.exit_conditions:
            cond.is_met = True

        now = datetime.now().isoformat()
        approved_by = params.approved_by or "human"

        # 更新 PhaseGate
        gate.status = PhaseGateStatus.APPROVED
        gate.reviewer_comment = params.comment
        gate.approved_by = approved_by
        gate.approved_at = now
        gate = await self._store.save_phase_gate(gate)

        # 添加审批历史
        history = PhaseHistory(
            id=generate_phase_history_id(),
            project_id=params.project_id,
            phase_name=params.phase_name,
            action="approved",
            actor=approved_by,
            comment=params.comment,
            created_at=now,
        )
        await self._store.add_phase_history(history)

        # 自动生成下一阶段的 Goal（如果阶段模板配置了 AutoGenerateGoals）
        await self._auto_generate_goal_for_phase(
            params.project_id, params.phase_name, params.comment
        )

        # 推进到下一阶段
        try:
            project = await self.advance_phase(params.project_id)
        except Exception as e:
            self._logger.warning(
                f"自动推进阶段失败 project_id={params.project_id} error={e}"
            )
            project = await self._store.get_project(params.project_id)

        self._logger.info(
            f"阶段已审批通过 project_id={params.project_id} "
            f"phase={params.phase_name} by={approved_by}"
        )
        return project

    async def reject_phase(self, params: RejectPhaseParams) -> PhaseGate:
        """审批驳回阶段"""
        if not params.project_id or not params.phase_name:
            raise InvalidParamError("project_id 和 phase_name 不能为空")
        if not params.comment:
            raise InvalidParamError("驳回必须提供意见")

        gate = await self._store.get_phase_gate(params.project_id, params.phase_name)

        if not self._is_valid_status_transition(gate.status, PhaseGateStatus.REJECTED):
            raise InvalidParamError(
                f"PhaseGate 状态 {gate.status} 不能转换为 rejected"
            )

        gate.status = PhaseGateStatus.REJECTED
        gate.reviewer_comment = params.comment
        if params.feedback:
            gate.human_feedback = params.feedback
        gate = await self._store.save_phase_gate(gate)

        # 添加驳回历史
        history = PhaseHistory(
            id=generate_phase_history_id(),
            project_id=params.project_id,
            phase_name=params.phase_name,
            action="rejected",
            actor="human",
            comment=params.comment,
            created_at=datetime.now().isoformat(),
        )
        await self._store.add_phase_history(history)

        self._logger.info(
            f"阶段已被驳回 project_id={params.project_id} phase={params.phase_name}"
        )
        return gate

    async def request_revision(self, params: RequestRevisionParams) -> PhaseGate:
        """请求修订"""
        if not params.project_id or not params.phase_name:
            raise InvalidParamError("project_id 和 phase_name 不能为空")
        if not params.comment:
            raise InvalidParamError("请求修订必须提供意见")

        gate = await self._store.get_phase_gate(params.project_id, params.phase_name)

        if not self._is_valid_status_transition(gate.status, PhaseGateStatus.REVISION_REQUESTED):
            raise InvalidParamError(
                f"PhaseGate 状态 {gate.status} 不能转换为 revision_requested"
            )

        feedback = HumanFeedback(
            comment=params.comment,
            revision_items=params.revision_items or [],
            submitted_at=datetime.now().isoformat(),
        )

        gate.status = PhaseGateStatus.REVISION_REQUESTED
        gate.reviewer_comment = params.comment
        gate.human_feedback = feedback
        gate = await self._store.save_phase_gate(gate)

        # 添加修订历史
        history = PhaseHistory(
            id=generate_phase_history_id(),
            project_id=params.project_id,
            phase_name=params.phase_name,
            action="revision_requested",
            actor="human",
            comment=params.comment,
            details={"revision_items": params.revision_items or []},
            created_at=datetime.now().isoformat(),
        )
        await self._store.add_phase_history(history)

        self._logger.info(
            f"阶段已请求修订 project_id={params.project_id} phase={params.phase_name}"
        )
        return gate

    # ---- Goal 自动生成与 Phase 关联 ----

    async def _auto_generate_goal_for_phase(
        self,
        project_id: str,
        phase_name: str,
        approval_comment: str = "",
    ) -> None:
        """审批通过后自动生成下一阶段的 Goal"""
        project = await self._store.get_project(project_id)

        # 找到当前阶段的下一阶段
        current_idx = -1
        for i, phase in enumerate(project.phases):
            if phase.name == phase_name:
                current_idx = i
                break

        if current_idx == -1 or current_idx + 1 >= len(project.phases):
            return  # 没有下一阶段，不生成

        next_phase = project.phases[current_idx + 1]

        # 查找阶段模板，检查是否需要自动生成 Goal
        phase_def = None
        for pd in DEFAULT_PHASE_TEMPLATE:
            if pd.name == next_phase.name:
                phase_def = pd
                break

        if phase_def is None or not phase_def.auto_generate_goals:
            return

        # 构建 Goal 描述，注入人类审批反馈
        description = f"【{next_phase.name} 阶段目标】\n\n项目：{project.title}\n\n{next_phase.description}"
        if approval_comment:
            description += f"\n\n【上一阶段审批意见】\n{approval_comment}"

        # 获取上一阶段的人类反馈
        try:
            gate = await self._store.get_phase_gate(project_id, phase_name)
            if gate.human_feedback:
                description += f"\n\n【人类反馈】\n{gate.human_feedback.comment}"
                if gate.human_feedback.revision_items:
                    description += "\n修订要点：\n- " + "\n- ".join(gate.human_feedback.revision_items)
        except NotFoundError:
            pass

        # 创建 Goal
        tags = list(project.tags) + [next_phase.name, "auto_generated"]

        try:
            from agentflow.goal import CreateGoalParams
            goal_params = CreateGoalParams(
                title=f"[{next_phase.name}] {project.title}",
                description=description,
                priority=project.priority,
                tags=tags,
            )
            new_goal = await self._goal_store.create(goal_params)

            # 关联 Goal 到项目
            await self._store.link_goal_to_phase(
                project_id, next_phase.name, new_goal.id, LinkType.AUTO_GENERATED
            )

            self._logger.info(
                f"已自动生成Goal project_id={project_id} "
                f"phase={next_phase.name} goal_id={new_goal.id}"
            )
        except Exception as e:
            self._logger.warning(f"创建Goal失败: {e}")

    # ---- Phase↔Goal/Task 关联管理 ----

    async def manual_link_goal_to_phase(
        self,
        project_id: str,
        phase_name: str,
        goal_id: str,
    ) -> PhaseGoalLink:
        """手动将已有 Goal 关联到 Phase"""
        if not project_id or not phase_name or not goal_id:
            raise InvalidParamError("project_id、phase_name、goal_id 不能为空")

        # 验证项目存在
        await self._store.get_project(project_id)

        # 验证 Goal 存在
        await self._goal_store.get(goal_id)

        # 检查是否已关联，避免重复（与 Go 实现保持一致）
        existing_links = await self._store._get_phase_goal_links(project_id, phase_name)
        for existing_link in existing_links:
            if existing_link.goal_id == goal_id:
                return existing_link  # 已关联，直接返回

        # 关联 Goal 到 Phase
        link = await self._store.link_goal_to_phase(
            project_id, phase_name, goal_id, LinkType.MANUAL_LINKED
        )

        self._logger.info(
            f"Goal已关联到Phase project_id={project_id} "
            f"phase={phase_name} goal_id={goal_id}"
        )
        return link

    async def manual_link_task_to_phase(
        self,
        project_id: str,
        phase_name: str,
        goal_id: str,
        task_id: str,
    ) -> None:
        """手动将已有 Task 关联到 Phase"""
        if not project_id or not phase_name or not task_id:
            raise InvalidParamError("project_id、phase_name、task_id 不能为空")

        # 验证项目存在
        await self._store.get_project(project_id)

        await self._store.link_task_to_phase(project_id, phase_name, goal_id, task_id)

    async def bind_condition_to_task(self, params: BindConditionToTaskParams) -> None:
        """将准出条件绑定到 Task，Task 完成时自动标记条件满足"""
        if not params.project_id or not params.phase_name:
            raise InvalidParamError("project_id 和 phase_name 不能为空")

        await self._store.bind_condition_to_task(
            params.project_id,
            params.phase_name,
            params.condition_index,
            task_id=params.task_id,
            goal_id=params.goal_id,
            auto_check=params.auto_check,
        )

    # ---- 阶段概览和进度 ----

    async def get_phase_overview(
        self,
        project_id: str,
        phase_name: str,
    ) -> PhaseOverview:
        """获取 Phase 概览（包含关联的 Goal/Task 完整信息）"""
        # 获取 Goal/Task 状态需要外部 provider
        overview = await self._store.get_phase_overview(
            project_id, phase_name,
            goal_provider=self._goal_store,
        )

        # 填充 Goal 详情
        links = await self._store._get_phase_goal_links(project_id, phase_name)
        for i, link in enumerate(links):
            try:
                goal = await self._goal_store.get(link.goal_id)
                overview.goals[i].title = goal.title
                overview.goals[i].status = goal.status
                overview.goals[i].progress = goal.progress
            except NotFoundError:
                pass

        return overview

    async def get_phase_progress(
        self,
        project_id: str,
        phase_name: str,
    ) -> PhaseProgress:
        """获取 Phase 完成进度"""
        links = await self._store._get_phase_goal_links(project_id, phase_name)

        # 收集 Goal 状态
        goal_statuses: Dict[str, str] = {}
        for link in links:
            try:
                goal = await self._goal_store.get(link.goal_id)
                goal_statuses[link.goal_id] = goal.status
            except NotFoundError:
                pass

        # 收集 Task 状态（通过阶段关联的 task_ids）
        task_statuses: Dict[str, str] = {}
        try:
            task_ids = await self._store._get_phase_task_ids(project_id, phase_name)
            for task_id in task_ids:
                if self._task_store is not None:
                    try:
                        task = await self._task_store.get(task_id)
                        task_statuses[task_id] = task.status if task else "unknown"
                    except Exception:
                        task_statuses[task_id] = "unknown"
                else:
                    task_statuses[task_id] = "unknown"
        except Exception:
            pass

        # 委托给 store 计算进度（与 Go 实现保持一致）
        progress = await self._store.get_phase_progress_with_statuses(
            project_id, phase_name, goal_statuses, task_statuses
        )
        return progress

    # ---- 状态同步 ----

    async def on_goal_completed(self, goal_id: str) -> None:
        """当 Goal 完成时调用，自动更新 PhaseGate 的准出条件"""
        self._logger.info(f"Goal已完成，触发状态同步 goal_id={goal_id}")
        # 查找该 Goal 关联的所有 Phase
        phase_links = await self._store.get_goal_phase_links(goal_id)
        for link_info in phase_links:
            project_id = link_info["project_id"]
            phase_name = link_info["phase_name"]
            gate = link_info.get("gate")
            if gate is None:
                try:
                    gate = await self._store.get_phase_gate(project_id, phase_name)
                except Exception:
                    continue
            # 检查准出条件中是否有绑定该 Goal 的条件
            updated = False
            for i, cond in enumerate(gate.exit_conditions):
                if cond.auto_check and cond.bound_goal_id == goal_id and not cond.is_met:
                    gate.exit_conditions[i].is_met = True
                    updated = True
                    self._logger.info(
                        f"准出条件已自动满足 project_id={project_id} "
                        f"phase={phase_name} condition={cond.description} goal_id={goal_id}"
                    )
            if updated:
                await self._store.save_phase_gate(gate)
            # 更新 PhaseGoalLink 状态为 completed
            try:
                await self._store.update_goal_link_status(
                    project_id, phase_name, goal_id, PhaseGoalLinkStatus.COMPLETED
                )
            except Exception:
                pass

    async def on_task_completed(
        self,
        project_id: str,
        phase_name: str,
        task_id: str,
    ) -> None:
        """当 Task 完成时调用，自动检查绑定的准出条件"""
        try:
            gate = await self._store.get_phase_gate(project_id, phase_name)
        except NotFoundError:
            return  # 没有对应的 PhaseGate，忽略

        updated = False
        for i, cond in enumerate(gate.exit_conditions):
            if cond.auto_check and cond.bound_task_id == task_id and not cond.is_met:
                gate.exit_conditions[i].is_met = True
                updated = True
                self._logger.info(
                    f"准出条件已自动满足 project_id={project_id} "
                    f"phase={phase_name} condition={cond.description} task_id={task_id}"
                )

        if updated:
            await self._store.save_phase_gate(gate)

    async def check_all_exit_conditions_met(
        self,
        project_id: str,
        phase_name: str,
    ) -> Tuple[bool, List[str]]:
        """检查所有准出条件是否满足"""
        gate = await self._store.get_phase_gate(project_id, phase_name)

        unmet = []
        for cond in gate.exit_conditions:
            if not cond.is_met:
                unmet.append(cond.description)

        return len(unmet) == 0, unmet

    async def get_phase_feedback(
        self,
        project_id: str,
        phase_name: str,
    ) -> Optional[HumanFeedback]:
        """获取阶段的人类反馈"""
        gate = await self._store.get_phase_gate(project_id, phase_name)
        return gate.human_feedback

    async def get_project_overview(self, project_id: str) -> Dict[str, Any]:
        """获取项目完整概览（含所有阶段状态）"""
        project = await self._store.get_project(project_id)
        gates = await self._store.list_phase_gates(project_id)
        history = await self._store.get_phase_history(project_id)

        gate_map = {gate.phase_name: gate for gate in gates}

        # 构建阶段概览（支持子阶段）
        def build_phase_overviews(phases: List[PhaseInfo]) -> List[Dict[str, Any]]:
            result = []
            for phase in phases:
                phase_info: Dict[str, Any] = {
                    "name": phase.name,
                    "description": phase.description,
                    "order": phase.order,
                    "status": phase.status,
                }
                if phase.name in gate_map:
                    gate = gate_map[phase.name]
                    phase_info["gate_status"] = gate.status
                    phase_info["linked_goals"] = len(gate.linked_goal_ids)
                    phase_info["linked_tasks"] = len(gate.linked_task_ids)
                if phase.children:
                    phase_info["children"] = build_phase_overviews(phase.children)
                result.append(phase_info)
            return result

        phase_overviews = build_phase_overviews(project.phases)

        return {
            "project": project.to_dict(),
            "phases": phase_overviews,
            "history": [h.to_dict() for h in history],
            "gates": [g.to_dict() for g in gates],
        }

    # ---- 动态阶段管理 ----

    async def add_phase(
        self,
        project_id: str,
        phase_name: str,
        description: str = "",
        order: int = 0,
        parent_phase: str = "",
    ) -> Project:
        """动态添加新阶段到项目（支持子阶段）"""
        if not project_id or not phase_name:
            raise InvalidParamError("project_id 和 phase_name 不能为空")

        project = await self._store.get_project(project_id)

        # 检查阶段名称是否重复（递归检查所有层级）
        if self._find_phase_by_name(project.phases, phase_name):
            raise InvalidParamError(f"阶段 '{phase_name}' 已存在")

        new_phase = PhaseInfo(
            name=phase_name,
            description=description,
            order=order,
            status=PhaseStatus.PENDING,
            parent_phase=parent_phase,
        )

        phases = list(project.phases)

        if parent_phase:
            # 添加为子阶段
            parent = self._find_phase_by_name(phases, parent_phase)
            if not parent:
                raise NotFoundError(f"父阶段 '{parent_phase}' 不存在")
            if order <= 0:
                order = len(parent.children) + 1
                new_phase.order = order
            parent.children = self._insert_phase_by_order(parent.children, new_phase)
        else:
            # 添加为顶层阶段
            if order <= 0:
                order = len(phases) + 1
                new_phase.order = order
            phases = self._insert_phase_by_order(phases, new_phase)

        # 创建对应的 PhaseGate
        await self._store._create_phase_gate_internal(project_id, phase_name)

        # 更新项目阶段列表
        project = await self._store.update_project(project_id, {"phases": phases})

        self._logger.info(
            f"阶段已添加 project_id={project_id} phase={phase_name} "
            f"parent={parent_phase} order={order}"
        )
        return project

    async def remove_phase(self, project_id: str, phase_name: str) -> Project:
        """从项目中移除阶段"""
        if not project_id or not phase_name:
            raise InvalidParamError("project_id 和 phase_name 不能为空")

        project = await self._store.get_project(project_id)

        # 检查阶段是否存在
        phase = self._find_phase_by_name(project.phases, phase_name)
        if not phase:
            raise NotFoundError(f"阶段 '{phase_name}' 不存在")

        if phase.status == PhaseStatus.ACTIVE:
            raise InvalidParamError(f"不能删除当前活跃阶段 '{phase_name}'")

        # 递归删除子阶段的 PhaseGate
        async def delete_child_gates(children: List[PhaseInfo]) -> None:
            for child in children:
                try:
                    await self._store.remove_phase(project_id, child.name)
                except Exception as e:
                    self._logger.warning(
                        f"删除子阶段PhaseGate失败 phase={child.name} error={e}"
                    )
                await delete_child_gates(child.children)

        await delete_child_gates(phase.children)

        # 从树中移除阶段（递归）
        phases = self._remove_phase_from_tree(project.phases, phase_name)

        # 删除 PhaseGate 及相关数据
        await self._store.remove_phase(project_id, phase_name)

        # 更新项目
        project = await self._store.update_project(project_id, {"phases": phases})

        self._logger.info(
            f"阶段已移除 project_id={project_id} phase={phase_name}"
        )
        return project

    async def update_phase_info(
        self,
        project_id: str,
        phase_name: str,
        new_name: str = "",
        new_description: str = "",
    ) -> Project:
        """更新阶段信息（名称、描述）"""
        if not project_id or not phase_name:
            raise InvalidParamError("project_id 和 phase_name 不能为空")

        project = await self._store.get_project(project_id)

        # 检查新名称是否与其他阶段冲突
        if new_name and new_name != phase_name:
            if self._find_phase_by_name(project.phases, new_name):
                raise InvalidParamError(f"阶段名称 '{new_name}' 已被占用")

        # 更新阶段信息
        updates: Dict[str, Any] = {}
        phase = self._find_phase_by_name(project.phases, phase_name)
        if not phase:
            raise NotFoundError(f"阶段 '{phase_name}' 不存在")

        if new_name:
            phase.name = new_name
        if new_description:
            phase.description = new_description

        updates["phases"] = project.phases

        # 如果修改了当前阶段的名称，同步更新 current_phase
        if new_name and new_name != phase_name and project.current_phase == phase_name:
            updates["current_phase"] = new_name

        # 如果改名，需要迁移 PhaseGate 数据（调用 store 的 rename_phase_gate 方法）
        if new_name and new_name != phase_name:
            try:
                await self._store.rename_phase_gate(project_id, phase_name, new_name)
            except Exception as e:
                self._logger.warning(f"迁移PhaseGate失败 error={e}")

        project = await self._store.update_project(project_id, updates)

        self._logger.info(
            f"阶段信息已更新 project_id={project_id} "
            f"phase={phase_name} new_name={new_name}"
        )
        return project

    # ---- 内容生成 ----

    def get_generator(self) -> Generator:
        """获取内容生成器"""
        return self._generator

    # ---- 内部辅助方法 ----

    def _is_valid_status_transition(self, from_status: str, to_status: str) -> bool:
        """检查 PhaseGate 状态转换是否合法"""
        # 允许的状态转换规则
        valid_transitions = {
            PhaseGateStatus.PENDING: [
                PhaseGateStatus.APPROVED,
                PhaseGateStatus.REJECTED,
                PhaseGateStatus.REVISION_REQUESTED,
            ],
            PhaseGateStatus.REVISION_REQUESTED: [
                PhaseGateStatus.PENDING,
                PhaseGateStatus.APPROVED,
                PhaseGateStatus.REJECTED,
            ],
            PhaseGateStatus.REJECTED: [
                PhaseGateStatus.PENDING,
                PhaseGateStatus.REVISION_REQUESTED,
            ],
        }

        if from_status == to_status:
            return True

        allowed = valid_transitions.get(from_status, [])
        return to_status in allowed

    def _find_phase_by_name(
        self,
        phases: List[PhaseInfo],
        name: str,
    ) -> Optional[PhaseInfo]:
        """递归查找阶段"""
        for phase in phases:
            if phase.name == name:
                return phase
            if phase.children:
                found = self._find_phase_by_name(phase.children, name)
                if found:
                    return found
        return None

    def _insert_phase_by_order(
        self,
        phases: List[PhaseInfo],
        new_phase: PhaseInfo,
    ) -> List[PhaseInfo]:
        """将新阶段按 order 插入到列表中"""
        result = []
        inserted = False

        for p in phases:
            if not inserted and p.order >= new_phase.order:
                result.append(new_phase)
                inserted = True
            if p.order >= new_phase.order:
                p.order += 1
            result.append(p)

        if not inserted:
            result.append(new_phase)

        return result

    def _remove_phase_from_tree(
        self,
        phases: List[PhaseInfo],
        name: str,
    ) -> List[PhaseInfo]:
        """从阶段树中递归移除指定阶段"""
        result = []
        for p in phases:
            if p.name == name:
                continue  # 跳过要删除的
            # 递归检查子阶段
            p.children = self._remove_phase_from_tree(p.children, name)
            result.append(p)
        # 重新排序
        for i, p in enumerate(result):
            p.order = i + 1
        return result
