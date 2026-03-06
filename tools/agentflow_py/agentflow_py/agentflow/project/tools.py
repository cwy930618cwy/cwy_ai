"""Project 模块 MCP 工具注册 - 移植自 Go 的 internal/project/tools*.go"""
import json
import logging
from typing import Dict, Any, Optional, List

from agentflow.mcp_server.types import ToolDef, ToolResult, ToolLayer
from agentflow.mcp_server.registry import Registry
from agentflow.project.engine import Engine
from agentflow.project.store import ProjectStore
from agentflow.project.generator import Generator
from agentflow.project.model import (
    Deliverable,
    HumanFeedback,
    ListProjectsParams,
    UpdateProjectParams,
    DeleteProjectParams,
    CreateProjectParams,
    SubmitPhaseReviewParams,
    ApprovePhaseParams,
    RejectPhaseParams,
    RequestRevisionParams,
    LinkGoalToPhaseParams,
    LinkTaskToPhaseParams,
    BindConditionToTaskParams,
)


def register_tools(
    registry: Registry,
    engine: Engine,
    store: ProjectStore,
    generator: Generator,
    logger: logging.Logger,
) -> None:
    """注册 Project 模块的所有 MCP 工具"""
    _register_project_manage_tools(registry, engine, store, logger)
    _register_phase_gate_tools(registry, engine, store, logger)
    _register_phase_manage_tools(registry, engine, store, logger)
    _register_link_tools(registry, engine, store, logger)
    _register_generate_tools(registry, engine, store, generator, logger)
    logger.debug("Project 模块工具注册完成")


# ---- 项目管理类工具 ----

def _register_project_manage_tools(
    registry: Registry,
    engine: Engine,
    store: ProjectStore,
    logger: logging.Logger,
) -> None:
    """注册项目管理类工具"""

    @registry.register(ToolDef(
        name="create_project",
        description="创建项目并初始化所有阶段门控（PhaseGate）。Agent 接收用户的模糊想法后调用此工具。\n"
        "项目创建后自动进入 idea_review 状态，并初始化 Idea→宏观补充→调研→MVP→P1→P2 六个阶段。\n"
        "template 参数指定阶段模板，默认 'standard'（标准六阶段流程）。",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "项目标题"},
                "description": {"type": "string", "description": "项目描述（初始想法）"},
                "vision": {"type": "string", "description": "项目愿景（可选）"},
                "priority": {"type": "integer", "description": "优先级1-10，默认5", "minimum": 1, "maximum": 10},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "标签"},
                "template": {"type": "string", "description": "阶段模板名称，默认 'standard'"},
            },
            "required": ["title", "description"],
        },
        layer=ToolLayer.LAYER1,
    ))
    async def create_project(params: Dict[str, Any]) -> ToolResult:
        p = CreateProjectParams(
            title=params.get("title", ""),
            description=params.get("description", ""),
            vision=params.get("vision", ""),
            template=params.get("template", "standard"),
            priority=params.get("priority", 5),
            tags=params.get("tags"),
        )
        try:
            project = await engine.create_project(p)
            return ToolResult.success(data={
                "project": project.to_dict(),
                "message": "项目已创建，已初始化6个阶段门控。当前阶段：idea，请调用 generate_project_blueprint 生成项目蓝图，然后调用 submit_phase_review 提交审阅。",
            })
        except Exception as e:
            return ToolResult.error(str(e))

    @registry.register(ToolDef(
        name="get_project",
        description="获取项目完整详情，包含所有阶段状态、关联 Goal 数量、审批历史和进度。",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "项目ID"},
            },
            "required": ["project_id"],
        },
        layer=ToolLayer.LAYER1,
    ))
    async def get_project(params: Dict[str, Any]) -> ToolResult:
        project_id = params.get("project_id")
        if not project_id:
            return ToolResult.error("project_id 不能为空")
        try:
            overview = await engine.get_project_overview(project_id)
            return ToolResult.success(data=overview)
        except Exception as e:
            return ToolResult.error(str(e))

    @registry.register(ToolDef(
        name="list_projects",
        description="获取项目列表，支持按状态/标签过滤和分页。返回每个项目的进度概览。",
        input_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "按状态过滤（draft/idea_review/macro_supplement/research/mvp/p1/p2/completed/cancelled）"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "按标签过滤"},
                "page": {"type": "integer", "description": "页码，默认1"},
                "page_size": {"type": "integer", "description": "每页数量，默认20"},
            },
        },
        layer=ToolLayer.LAYER1,
    ))
    async def list_projects(params: Dict[str, Any]) -> ToolResult:
        p = ListProjectsParams(
            status=params.get("status"),
            tags=params.get("tags"),
            page=params.get("page", 1),
            page_size=params.get("page_size", 20),
        )
        try:
            projects, total = await store.list_projects(p)
            return ToolResult.success(data={
                "projects": [proj.to_dict() for proj in projects],
                "total": total,
                "page": p.page,
            })
        except Exception as e:
            return ToolResult.error(str(e))

    @registry.register(ToolDef(
        name="update_project",
        description="更新项目信息。支持更新：title/description/vision/risk_list/tech_stack/tags/priority。",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "项目ID"},
                "fields": {"type": "object", "description": "要更新的字段键值对"},
            },
            "required": ["project_id", "fields"],
        },
        layer=ToolLayer.LAYER2,
    ))
    async def update_project(params: Dict[str, Any]) -> ToolResult:
        p = UpdateProjectParams(
            project_id=params.get("project_id", ""),
            fields=params.get("fields", {}),
        )
        if not p.project_id:
            return ToolResult.error("project_id 不能为空")
        try:
            project = await store.update_project(p.project_id, p.fields)
            return ToolResult.success(data=project.to_dict())
        except Exception as e:
            return ToolResult.error(str(e))

    @registry.register(ToolDef(
        name="delete_project",
        description="删除项目。cascade=true 时级联删除关联 Goal 和 Task。confirm 必须为 'CONFIRM_DELETE'。",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "项目ID"},
                "cascade": {"type": "boolean", "description": "是否级联删除关联 Goal 和 Task"},
                "confirm": {"type": "string", "description": "确认标记，必须为 'CONFIRM_DELETE'"},
            },
            "required": ["project_id", "confirm"],
        },
        layer=ToolLayer.LAYER2,
    ))
    async def delete_project(params: Dict[str, Any]) -> ToolResult:
        p = DeleteProjectParams(
            project_id=params.get("project_id", ""),
            cascade=params.get("cascade", False),
            confirm=params.get("confirm", ""),
        )
        if p.confirm != "CONFIRM_DELETE":
            return ToolResult.error("删除确认失败: confirm 必须为 'CONFIRM_DELETE'")
        try:
            await store.delete_project(p.project_id, p.cascade)
            return ToolResult.success(data={
                "status": "deleted",
                "project_id": p.project_id,
            })
        except Exception as e:
            return ToolResult.error(str(e))


# ---- 阶段审批类工具 ----

def _register_phase_gate_tools(
    registry: Registry,
    engine: Engine,
    store: ProjectStore,
    logger: logging.Logger,
) -> None:
    """注册阶段审批类工具"""

    @registry.register(ToolDef(
        name="submit_phase_review",
        description="Agent 完成阶段工作后提交审阅。提交后 PhaseGate 进入等待人类审批状态。\n"
        "⚠️ 提交前请确保：\n"
        "1. 已调用 generate_phase_summary 生成阶段总结\n"
        "2. 所有关键产出物已完成\n"
        "3. 准出条件已尽量满足",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "项目ID"},
                "phase_name": {"type": "string", "description": "阶段名称（idea/macro_supplement/research/mvp/p1/p2）"},
                "summary": {"type": "string", "description": "阶段工作总结"},
                "deliverables": {
                    "type": "array",
                    "description": "阶段产出物列表",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                            "content": {"type": "string"},
                            "is_completed": {"type": "boolean"},
                        },
                    },
                },
            },
            "required": ["project_id", "phase_name"],
        },
        layer=ToolLayer.LAYER1,
    ))
    async def submit_phase_review(params: Dict[str, Any]) -> ToolResult:
        deliverables_data = params.get("deliverables", [])
        deliverables = [Deliverable(**d) for d in deliverables_data] if deliverables_data else None

        p = SubmitPhaseReviewParams(
            project_id=params.get("project_id", ""),
            phase_name=params.get("phase_name", ""),
            summary=params.get("summary", ""),
            deliverables=deliverables,
        )
        try:
            gate = await engine.submit_for_review(p)
            return ToolResult.success(data={
                "gate": gate.to_dict(),
                "message": "阶段已提交审阅，等待人类审批。请在 Dashboard 中查看审批状态。",
            })
        except Exception as e:
            return ToolResult.error(str(e))

    @registry.register(ToolDef(
        name="approve_phase",
        description="人类审批通过阶段，自动推进到下一阶段并生成下一阶段的 Goal。\n"
        "审批通过后：\n"
        "1. 当前阶段 PhaseGate 状态变为 approved\n"
        "2. 自动生成下一阶段的 Goal（包含审批意见作为上下文）\n"
        "3. 项目推进到下一阶段",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "项目ID"},
                "phase_name": {"type": "string", "description": "阶段名称"},
                "comment": {"type": "string", "description": "审批意见（会注入到下一阶段 Goal 的上下文中）"},
                "approved_by": {"type": "string", "description": "审批人标识，默认 'human'"},
            },
            "required": ["project_id", "phase_name"],
        },
        layer=ToolLayer.LAYER1,
    ))
    async def approve_phase(params: Dict[str, Any]) -> ToolResult:
        p = ApprovePhaseParams(
            project_id=params.get("project_id", ""),
            phase_name=params.get("phase_name", ""),
            comment=params.get("comment", ""),
            approved_by=params.get("approved_by", "human"),
        )
        try:
            project = await engine.approve_phase(p)
            return ToolResult.success(data={
                "project": project.to_dict(),
                "message": "阶段已审批通过，项目已推进到下一阶段。已自动生成下一阶段的 Goal。",
            })
        except Exception as e:
            return ToolResult.error(str(e))

    @registry.register(ToolDef(
        name="reject_phase",
        description="人类驳回阶段，记录驳回原因和反馈。Agent 需要根据反馈修改后重新提交。\n"
        "驳回后 Agent 应：\n"
        "1. 调用 get_phase_feedback 获取详细反馈\n"
        "2. 根据反馈修改工作内容\n"
        "3. 重新调用 submit_phase_review 提交",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "项目ID"},
                "phase_name": {"type": "string", "description": "阶段名称"},
                "comment": {"type": "string", "description": "驳回原因（必填）"},
                "feedback": {
                    "type": "object",
                    "description": "结构化反馈",
                    "properties": {
                        "comment": {"type": "string"},
                        "revision_items": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "required": ["project_id", "phase_name", "comment"],
        },
        layer=ToolLayer.LAYER1,
    ))
    async def reject_phase(params: Dict[str, Any]) -> ToolResult:
        feedback_data = params.get("feedback")
        feedback = None
        if feedback_data:
            feedback = HumanFeedback(
                comment=feedback_data.get("comment", ""),
                revision_items=feedback_data.get("revision_items", []),
            )

        p = RejectPhaseParams(
            project_id=params.get("project_id", ""),
            phase_name=params.get("phase_name", ""),
            comment=params.get("comment", ""),
            feedback=feedback,
        )
        try:
            gate = await engine.reject_phase(p)
            return ToolResult.success(data={
                "gate": gate.to_dict(),
                "message": "阶段已被驳回。Agent 请调用 get_phase_feedback 获取详细反馈，修改后重新提交。",
            })
        except Exception as e:
            return ToolResult.error(str(e))

    @registry.register(ToolDef(
        name="request_phase_revision",
        description="人类请求修订（介于通过和驳回之间）。Agent 需要按修订要点修改后重新提交。",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "项目ID"},
                "phase_name": {"type": "string", "description": "阶段名称"},
                "comment": {"type": "string", "description": "修订意见（必填）"},
                "revision_items": {"type": "array", "items": {"type": "string"}, "description": "修订要点列表"},
            },
            "required": ["project_id", "phase_name", "comment"],
        },
        layer=ToolLayer.LAYER2,
    ))
    async def request_phase_revision(params: Dict[str, Any]) -> ToolResult:
        p = RequestRevisionParams(
            project_id=params.get("project_id", ""),
            phase_name=params.get("phase_name", ""),
            comment=params.get("comment", ""),
            revision_items=params.get("revision_items"),
        )
        try:
            gate = await engine.request_revision(p)
            return ToolResult.success(data={
                "gate": gate.to_dict(),
                "message": "已请求修订。Agent 请根据修订要点修改后重新提交。",
            })
        except Exception as e:
            return ToolResult.error(str(e))

    @registry.register(ToolDef(
        name="get_phase_gate",
        description="获取阶段门控详情，包含准入/准出条件、产出物、审批状态和人类反馈。",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "项目ID"},
                "phase_name": {"type": "string", "description": "阶段名称"},
            },
            "required": ["project_id", "phase_name"],
        },
        layer=ToolLayer.LAYER1,
    ))
    async def get_phase_gate(params: Dict[str, Any]) -> ToolResult:
        project_id = params.get("project_id")
        phase_name = params.get("phase_name")
        if not project_id or not phase_name:
            return ToolResult.error("project_id 和 phase_name 不能为空")
        try:
            gate = await store.get_phase_gate(project_id, phase_name)
            return ToolResult.success(data=gate.to_dict())
        except Exception as e:
            return ToolResult.error(str(e))

    @registry.register(ToolDef(
        name="list_phase_gates",
        description="获取项目所有阶段门控的状态概览。",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "项目ID"},
            },
            "required": ["project_id"],
        },
        layer=ToolLayer.LAYER2,
    ))
    async def list_phase_gates(params: Dict[str, Any]) -> ToolResult:
        project_id = params.get("project_id")
        if not project_id:
            return ToolResult.error("project_id 不能为空")
        try:
            gates = await store.list_phase_gates(project_id)
            return ToolResult.success(data={
                "gates": [g.to_dict() for g in gates],
                "total": len(gates),
            })
        except Exception as e:
            return ToolResult.error(str(e))

    @registry.register(ToolDef(
        name="get_phase_feedback",
        description="获取阶段的人类审阅反馈。Agent 在审批被驳回或请求修订后应调用此工具获取详细反馈。\n"
        "反馈内容包含：审阅意见、修订要点列表，Agent 应将这些内容作为下一步工作的指导。",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "项目ID"},
                "phase_name": {"type": "string", "description": "阶段名称"},
            },
            "required": ["project_id", "phase_name"],
        },
        layer=ToolLayer.LAYER2,
    ))
    async def get_phase_feedback(params: Dict[str, Any]) -> ToolResult:
        project_id = params.get("project_id")
        phase_name = params.get("phase_name")
        if not project_id or not phase_name:
            return ToolResult.error("project_id 和 phase_name 不能为空")
        try:
            feedback = await engine.get_phase_feedback(project_id, phase_name)
            if feedback is None:
                return ToolResult.success(data={"message": "该阶段暂无人类反馈"})
            return ToolResult.success(data=feedback.to_dict())
        except Exception as e:
            return ToolResult.error(str(e))

    @registry.register(ToolDef(
        name="get_phase_overview",
        description="获取阶段概览：返回该 Phase 关联的所有 Goal 列表（含 title/status/progress），\n"
        "每个 Goal 下的 Task 列表（含 title/status/progress/claimed_by），以及 Phase 级别的完成进度统计。\n"
        "这是 Dashboard 前端点击 Phase 节点时加载的核心数据。",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "项目ID"},
                "phase_name": {"type": "string", "description": "阶段名称"},
            },
            "required": ["project_id", "phase_name"],
        },
        layer=ToolLayer.LAYER1,
    ))
    async def get_phase_overview(params: Dict[str, Any]) -> ToolResult:
        project_id = params.get("project_id")
        phase_name = params.get("phase_name")
        if not project_id or not phase_name:
            return ToolResult.error("project_id 和 phase_name 不能为空")
        try:
            overview = await engine.get_phase_overview(project_id, phase_name)
            return ToolResult.success(data=overview.to_dict())
        except Exception as e:
            return ToolResult.error(str(e))


# ---- 阶段管理类工具 ----

def _register_phase_manage_tools(
    registry: Registry,
    engine: Engine,
    store: ProjectStore,
    logger: logging.Logger,
) -> None:
    """注册阶段管理类工具"""

    @registry.register(ToolDef(
        name="add_phase",
        description="动态添加阶段或子阶段。支持在项目顶层添加新阶段，或在已有阶段下添加子阶段。\n"
        "parent_phase 为空时添加顶层阶段，非空时添加为指定阶段的子阶段。",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "项目ID"},
                "name": {"type": "string", "description": "阶段名称"},
                "description": {"type": "string", "description": "阶段描述（可选）"},
                "order": {"type": "integer", "description": "排序序号（可选，默认追加到末尾）"},
                "parent_phase": {"type": "string", "description": "父阶段名称（可选，为空则添加顶层阶段）"},
            },
            "required": ["project_id", "name"],
        },
        layer=ToolLayer.LAYER1,
    ))
    async def add_phase(params: Dict[str, Any]) -> ToolResult:
        project_id = params.get("project_id")
        name = params.get("name")
        if not project_id or not name:
            return ToolResult.error("project_id 和 name 不能为空")
        try:
            project = await engine.add_phase(
                project_id=project_id,
                phase_name=name,
                description=params.get("description", ""),
                order=params.get("order", 0),
                parent_phase=params.get("parent_phase", ""),
            )
            return ToolResult.success(data=project.to_dict())
        except Exception as e:
            return ToolResult.error(str(e))

    @registry.register(ToolDef(
        name="remove_phase",
        description="删除阶段（包括其所有子阶段和关联的 PhaseGate）。⚠️ 此操作不可逆。",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "项目ID"},
                "phase_name": {"type": "string", "description": "要删除的阶段名称"},
            },
            "required": ["project_id", "phase_name"],
        },
        layer=ToolLayer.LAYER2,
    ))
    async def remove_phase(params: Dict[str, Any]) -> ToolResult:
        project_id = params.get("project_id")
        phase_name = params.get("phase_name")
        if not project_id or not phase_name:
            return ToolResult.error("project_id 和 phase_name 不能为空")
        try:
            project = await engine.remove_phase(project_id, phase_name)
            return ToolResult.success(data=project.to_dict())
        except Exception as e:
            return ToolResult.error(str(e))

    @registry.register(ToolDef(
        name="update_phase",
        description="更新阶段信息（名称和描述）。支持重命名阶段（会同步更新 PhaseGate 的键名）。",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "项目ID"},
                "phase_name": {"type": "string", "description": "当前阶段名称"},
                "new_name": {"type": "string", "description": "新名称（可选，不填则不改名）"},
                "new_description": {"type": "string", "description": "新描述（可选，不填则不修改）"},
            },
            "required": ["project_id", "phase_name"],
        },
        layer=ToolLayer.LAYER2,
    ))
    async def update_phase(params: Dict[str, Any]) -> ToolResult:
        project_id = params.get("project_id")
        phase_name = params.get("phase_name")
        if not project_id or not phase_name:
            return ToolResult.error("project_id 和 phase_name 不能为空")
        try:
            project = await engine.update_phase_info(
                project_id=project_id,
                phase_name=phase_name,
                new_name=params.get("new_name", ""),
                new_description=params.get("new_description", ""),
            )
            return ToolResult.success(data=project.to_dict())
        except Exception as e:
            return ToolResult.error(str(e))


# ---- Goal/Task 关联类工具 ----

def _register_link_tools(
    registry: Registry,
    engine: Engine,
    store: ProjectStore,
    logger: logging.Logger,
) -> None:
    """注册 Goal/Task 关联类工具"""

    @registry.register(ToolDef(
        name="link_goal_to_phase",
        description="手动将已有 Goal 关联到指定 Phase。关联后 Goal 会出现在 Phase 的概览中。",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "项目ID"},
                "phase_name": {"type": "string", "description": "阶段名称"},
                "goal_id": {"type": "string", "description": "Goal ID"},
            },
            "required": ["project_id", "phase_name", "goal_id"],
        },
        layer=ToolLayer.LAYER1,
    ))
    async def link_goal_to_phase(params: Dict[str, Any]) -> ToolResult:
        p = LinkGoalToPhaseParams(
            project_id=params.get("project_id", ""),
            phase_name=params.get("phase_name", ""),
            goal_id=params.get("goal_id", ""),
        )
        try:
            link = await engine.manual_link_goal_to_phase(
                p.project_id, p.phase_name, p.goal_id
            )
            return ToolResult.success(data=link.to_dict())
        except Exception as e:
            return ToolResult.error(str(e))

    @registry.register(ToolDef(
        name="unlink_goal_from_phase",
        description="取消 Goal 与 Phase 的关联。取消后 Goal 不再出现在该 Phase 的概览中。",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "项目ID"},
                "phase_name": {"type": "string", "description": "阶段名称"},
                "goal_id": {"type": "string", "description": "要取消关联的 Goal ID"},
            },
            "required": ["project_id", "phase_name", "goal_id"],
        },
        layer=ToolLayer.LAYER2,
    ))
    async def unlink_goal_from_phase(params: Dict[str, Any]) -> ToolResult:
        project_id = params.get("project_id")
        phase_name = params.get("phase_name")
        goal_id = params.get("goal_id")
        if not project_id or not phase_name or not goal_id:
            return ToolResult.error("project_id、phase_name、goal_id 不能为空")
        try:
            await store.unlink_goal_from_phase(project_id, phase_name, goal_id)
            return ToolResult.success(data={
                "status": "unlinked",
                "project_id": project_id,
                "phase_name": phase_name,
                "goal_id": goal_id,
            })
        except Exception as e:
            return ToolResult.error(str(e))

    @registry.register(ToolDef(
        name="link_task_to_phase",
        description="手动将已有 Task 关联到指定 Phase。需要指定 Task 所属的 Goal ID。",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "项目ID"},
                "phase_name": {"type": "string", "description": "阶段名称"},
                "goal_id": {"type": "string", "description": "Task 所属的 Goal ID"},
                "task_id": {"type": "string", "description": "Task ID"},
            },
            "required": ["project_id", "phase_name", "goal_id", "task_id"],
        },
        layer=ToolLayer.LAYER1,
    ))
    async def link_task_to_phase(params: Dict[str, Any]) -> ToolResult:
        p = LinkTaskToPhaseParams(
            project_id=params.get("project_id", ""),
            phase_name=params.get("phase_name", ""),
            goal_id=params.get("goal_id", ""),
            task_id=params.get("task_id", ""),
        )
        try:
            await engine.manual_link_task_to_phase(
                p.project_id, p.phase_name, p.goal_id, p.task_id
            )
            return ToolResult.success(data={
                "status": "linked",
                "project_id": p.project_id,
                "phase_name": p.phase_name,
                "task_id": p.task_id,
            })
        except Exception as e:
            return ToolResult.error(str(e))

    @registry.register(ToolDef(
        name="unlink_task_from_phase",
        description="取消 Task 与 Phase 的关联。同时从 Phase 的任务列表和 Goal 的 TaskIDs 中移除。",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "项目ID"},
                "phase_name": {"type": "string", "description": "阶段名称"},
                "task_id": {"type": "string", "description": "要取消关联的 Task ID"},
            },
            "required": ["project_id", "phase_name", "task_id"],
        },
        layer=ToolLayer.LAYER2,
    ))
    async def unlink_task_from_phase(params: Dict[str, Any]) -> ToolResult:
        project_id = params.get("project_id")
        phase_name = params.get("phase_name")
        task_id = params.get("task_id")
        if not project_id or not phase_name or not task_id:
            return ToolResult.error("project_id、phase_name、task_id 不能为空")
        try:
            await store.unlink_task_from_phase(project_id, phase_name, task_id)
            return ToolResult.success(data={
                "status": "unlinked",
                "project_id": project_id,
                "phase_name": phase_name,
                "task_id": task_id,
            })
        except Exception as e:
            return ToolResult.error(str(e))

    @registry.register(ToolDef(
        name="bind_condition_to_task",
        description="将准出条件绑定到 Task 或 Goal。绑定后当 Task/Goal 完成时，准出条件自动标记为满足（AutoCheck）。\n"
        "condition_index 为准出条件在列表中的索引（从0开始）。",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "项目ID"},
                "phase_name": {"type": "string", "description": "阶段名称"},
                "condition_index": {"type": "integer", "description": "准出条件索引（从0开始）"},
                "task_id": {"type": "string", "description": "绑定的 Task ID（与 goal_id 二选一）"},
                "goal_id": {"type": "string", "description": "绑定的 Goal ID（与 task_id 二选一）"},
                "auto_check": {"type": "boolean", "description": "是否自动检查，默认 true"},
            },
            "required": ["project_id", "phase_name", "condition_index"],
        },
        layer=ToolLayer.LAYER1,
    ))
    async def bind_condition_to_task(params: Dict[str, Any]) -> ToolResult:
        p = BindConditionToTaskParams(
            project_id=params.get("project_id", ""),
            phase_name=params.get("phase_name", ""),
            condition_index=params.get("condition_index", 0),
            task_id=params.get("task_id", ""),
            goal_id=params.get("goal_id", ""),
            auto_check=params.get("auto_check", True),
        )
        try:
            await engine.bind_condition_to_task(p)
            return ToolResult.success(data={
                "status": "bound",
                "project_id": p.project_id,
                "phase_name": p.phase_name,
                "condition_index": p.condition_index,
            })
        except Exception as e:
            return ToolResult.error(str(e))


# ---- 内容生成类工具 ----

def _register_generate_tools(
    registry: Registry,
    engine: Engine,
    store: ProjectStore,
    generator: Generator,
    logger: logging.Logger,
) -> None:
    """注册内容生成类工具"""

    @registry.register(ToolDef(
        name="generate_project_blueprint",
        description="基于项目描述生成项目蓝图（结构化的项目计划）。\n"
        "返回：蓝图内容（愿景、核心功能、技术约束、风险、里程碑）和给 AI 填充的提示词。\n"
        "Agent 应在 Idea 阶段审批前调用此工具，将提示词发送给 LLM 生成完整蓝图。",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "项目ID"},
            },
            "required": ["project_id"],
        },
        layer=ToolLayer.LAYER2,
    ))
    async def generate_project_blueprint(params: Dict[str, Any]) -> ToolResult:
        project_id = params.get("project_id")
        if not project_id:
            return ToolResult.error("project_id 不能为空")
        try:
            project = await store.get_project(project_id)
            blueprint = generator.generate_project_blueprint(project)
            return ToolResult.success(data={
                "blueprint": blueprint.to_dict(),
                "hint": "请将 blueprint.prompt 发送给 LLM，将生成的内容填充到蓝图中，然后调用 update_project 更新项目信息，最后调用 submit_phase_review 提交审阅。",
            })
        except Exception as e:
            return ToolResult.error(str(e))

    @registry.register(ToolDef(
        name="generate_macro_supplement",
        description="生成宏观补充内容（子目标树、技术栈建议、依赖分析、资源预估）。\n"
        "返回结构化的宏观补充模板和提示词，Agent 应将提示词发送给 LLM 填充详细内容。",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "项目ID"},
            },
            "required": ["project_id"],
        },
        layer=ToolLayer.LAYER2,
    ))
    async def generate_macro_supplement(params: Dict[str, Any]) -> ToolResult:
        project_id = params.get("project_id")
        if not project_id:
            return ToolResult.error("project_id 不能为空")
        try:
            project = await store.get_project(project_id)
            supplement, prompt = generator.generate_macro_supplement(project)
            return ToolResult.success(data={
                "supplement": supplement.to_dict(),
                "prompt": prompt,
                "hint": "请将 prompt 发送给 LLM，将生成的内容填充到 supplement 中，然后调用 update_project 更新技术栈和风险清单。",
            })
        except Exception as e:
            return ToolResult.error(str(e))

    @registry.register(ToolDef(
        name="generate_research_plan",
        description="基于宏观补充，生成调研计划和调研任务列表。\n"
        "返回的任务模板列表可直接用于 create_tasks 创建调研任务。",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "项目ID"},
            },
            "required": ["project_id"],
        },
        layer=ToolLayer.LAYER2,
    ))
    async def generate_research_plan(params: Dict[str, Any]) -> ToolResult:
        project_id = params.get("project_id")
        if not project_id:
            return ToolResult.error("project_id 不能为空")
        try:
            project = await store.get_project(project_id)
            tasks, prompt = generator.generate_research_tasks(project)
            return ToolResult.success(data={
                "task_templates": [t.to_dict() for t in tasks],
                "prompt": prompt,
                "hint": "可将 task_templates 直接传入 create_tasks 创建调研任务，或将 prompt 发送给 LLM 生成更详细的任务列表。",
            })
        except Exception as e:
            return ToolResult.error(str(e))

    @registry.register(ToolDef(
        name="generate_phase_tasks",
        description="为指定阶段生成任务列表。返回任务模板列表（含依赖关系和难度评分），可直接用于 create_tasks。",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "项目ID"},
                "phase_name": {"type": "string", "description": "阶段名称（idea/macro_supplement/research/mvp/p1/p2）"},
            },
            "required": ["project_id", "phase_name"],
        },
        layer=ToolLayer.LAYER2,
    ))
    async def generate_phase_tasks(params: Dict[str, Any]) -> ToolResult:
        project_id = params.get("project_id")
        phase_name = params.get("phase_name")
        if not project_id or not phase_name:
            return ToolResult.error("project_id 和 phase_name 不能为空")
        try:
            project = await store.get_project(project_id)
            tasks, prompt = generator.generate_phase_tasks_for_phase(project, phase_name)
            return ToolResult.success(data={
                "task_templates": [t.to_dict() for t in tasks],
                "prompt": prompt,
                "phase": phase_name,
                "hint": "可将 task_templates 直接传入 create_tasks 创建任务，或将 prompt 发送给 LLM 生成更详细的任务列表。",
            })
        except Exception as e:
            return ToolResult.error(str(e))

    @registry.register(ToolDef(
        name="generate_phase_summary",
        description="汇总当前阶段所有 Task 结果，生成阶段总结报告。\n"
        "返回：已完成/进行中/风险项/关键决策，以及是否可以提交审阅的判断。\n"
        "Agent 应在调用 submit_phase_review 前先调用此工具生成总结。",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "项目ID"},
                "phase_name": {"type": "string", "description": "阶段名称"},
                "completed_tasks": {"type": "array", "items": {"type": "string"}, "description": "已完成的任务标题列表"},
                "in_progress_tasks": {"type": "array", "items": {"type": "string"}, "description": "进行中的任务标题列表"},
            },
            "required": ["project_id", "phase_name"],
        },
        layer=ToolLayer.LAYER2,
    ))
    async def generate_phase_summary(params: Dict[str, Any]) -> ToolResult:
        project_id = params.get("project_id")
        phase_name = params.get("phase_name")
        if not project_id or not phase_name:
            return ToolResult.error("project_id 和 phase_name 不能为空")
        try:
            project = await store.get_project(project_id)
            completed_tasks = params.get("completed_tasks", [])
            in_progress_tasks = params.get("in_progress_tasks", [])

            summary, prompt = generator.generate_phase_summary(
                project, phase_name, completed_tasks, in_progress_tasks
            )

            # 检查准出条件满足情况
            all_met, unmet = await engine.check_all_exit_conditions_met(project_id, phase_name)

            return ToolResult.success(data={
                "summary": summary.to_dict(),
                "prompt": prompt,
                "exit_conditions_met": all_met,
                "unmet_conditions": unmet,
                "hint": "请将 prompt 发送给 LLM 生成详细总结，然后调用 submit_phase_review 提交审阅（将总结作为 summary 参数）。",
            })
        except Exception as e:
            return ToolResult.error(str(e))
