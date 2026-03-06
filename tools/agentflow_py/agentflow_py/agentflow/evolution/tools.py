import logging
from typing import Dict

from agentflow.mcp_server import Registry, ToolDef, ToolLayer, new_json_result, new_error_result
from .engine import EvolutionEngine, DistillAndEvolveParams


def register_tools(registry: Registry, engine: EvolutionEngine, logger: logging.Logger) -> None:

    registry.register(
        ToolDef(
            name="report_experience",
            description=(
                "上报经验（正向/负向）。type=positive上报成功模式，type=negative上报失败坑。"
                "severity(严重性0-1)×confidence(置信度0-1)=经验权重。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string"},
                    "skill_type": {"type": "string"},
                    "type": {"type": "string", "enum": ["positive", "negative"]},
                    "category": {"type": "string", "description": "bug/design_flaw/pattern/technique/architecture等"},
                    "description": {"type": "string", "description": "经验描述(≥50字)"},
                    "evidence": {"type": "string", "description": "支持证据"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.7},
                    "severity": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5},
                },
                "required": ["agent_id", "skill_type", "type", "category", "description"],
            },
            layer=ToolLayer.LAYER1,
        ),
        _make_report_experience_handler(engine),
    )

    registry.register(
        ToolDef(
            name="get_experiences",
            description="获取经验列表。支持按skill_type/type过滤。",
            input_schema={
                "type": "object",
                "properties": {
                    "skill_type": {"type": "string"},
                    "type": {"type": "string", "enum": ["positive", "negative", "all"]},
                    "limit": {"type": "integer", "default": 20},
                },
            },
            layer=ToolLayer.LAYER2,
        ),
        _make_get_experiences_handler(engine),
    )

    registry.register(
        ToolDef(
            name="distill_and_evolve",
            description=(
                "Agent主动发起经验提炼整理和进化。汇总指定Skill的所有经验→去重整理→模式检测→"
                "生成进化提案→低影响自动应用/高影响待审批→清理陈旧规则。"
                "建议在完成一批任务后主动调用，促进Skill持续进化。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "skill_type": {"type": "string", "description": "目标Skill名称（必填）"},
                    "auto_apply": {"type": "boolean", "default": True, "description": "是否自动应用低影响提案"},
                    "include_stale": {"type": "boolean", "default": True, "description": "是否清理陈旧和重复规则"},
                    "max_proposals": {"type": "integer", "default": 5, "description": "最多生成多少个提案"},
                },
                "required": ["skill_type"],
            },
            layer=ToolLayer.LAYER1,
        ),
        _make_distill_advanced_handler(engine),
    )

    registry.register(
        ToolDef(
            name="audit_skill_quality",
            description="审计Skill DNA质量。检测过时规则/低置信度证据/成功率偏低等问题。",
            input_schema={
                "type": "object",
                "properties": {"skill_type": {"type": "string"}},
                "required": ["skill_type"],
            },
            layer=ToolLayer.LAYER1,
        ),
        _make_audit_handler(engine),
    )

    registry.register(
        ToolDef(
            name="get_evolution_status",
            description="查看当前进化状态: Archive最高分/待处理进化/最近进化记录/审批历史。",
            input_schema={"type": "object", "properties": {}},
            layer=ToolLayer.LAYER1,
        ),
        _make_get_status_handler(engine),
    )

    registry.register(
        ToolDef(
            name="get_safety_report",
            description=(
                "获取安全报告（五维检测）："
                "①进化频率检测 ②高影响进化比例 ③待审批积压 ④近期失败率 ⑤校准距离。"
                "返回各维度状态、警告和改进建议。"
            ),
            input_schema={"type": "object", "properties": {}},
            layer=ToolLayer.LAYER2,
        ),
        _make_safety_report_handler(engine),
    )

    registry.register(
        ToolDef(
            name="snapshot_agent",
            description=(
                "SICA核心: 保存当前Agent状态到Archive。自动计算综合评分（动态权重）。"
                "如果当前表现优于历史最佳→成为新baseline。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "trigger": {"type": "string", "enum": ["manual", "milestone", "auto"], "default": "manual"},
                    "note": {"type": "string", "description": "备注说明"},
                },
            },
            layer=ToolLayer.LAYER2,
        ),
        _make_snapshot_agent_handler(engine),
    )

    registry.register(
        ToolDef(
            name="approve_evolution",
            description=(
                "审批进化提案。action可选: approve(应用)/reject(拒绝)/modify(修改后应用)。"
                "高影响度进化需人工审批。"
                "⚠️ 重要：高影响提案(impact >= 0.5)审批时必须提供 approval_reason。"
                "审批通过时自动创建快照并关联 rollback_snapshot_id。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "evo_id": {"type": "string", "description": "进化提案ID"},
                    "action": {"type": "string", "enum": ["approve", "reject", "modify"]},
                    "modification": {"type": "string", "description": "修改内容(action=modify时)"},
                    "approver": {"type": "string", "description": "审批人标识"},
                    "approval_reason": {"type": "string", "description": "审批原因（高影响提案必填）"},
                },
                "required": ["evo_id", "action"],
            },
            layer=ToolLayer.LAYER2,
        ),
        _make_approve_evolution_handler(engine),
    )

    registry.register(
        ToolDef(
            name="trigger_evolution",
            description=(
                "手动触发进化分析。scope: skill/rules/strategy/all。"
                "target: skill名或global。force=true跳过最少证据阈值。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "scope": {"type": "string", "enum": ["skill", "rules", "strategy", "all"], "default": "all"},
                    "target": {"type": "string", "description": "指定skill_name或global"},
                    "force": {"type": "boolean", "default": False},
                },
            },
            layer=ToolLayer.LAYER2,
        ),
        _make_trigger_evolution_handler(engine),
    )

    registry.register(
        ToolDef(
            name="rollback_to_archive",
            description=(
                "回滚到历史最佳配置。从指定 Archive 恢复 Agent 状态。"
                "⚠️ 此操作会覆盖当前 Skill 版本，建议先调用 snapshot_agent 保存当前状态。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "archive_id": {"type": "string", "description": "Archive ID（从 get_evolution_status 获取）"},
                },
                "required": ["archive_id"],
            },
            layer=ToolLayer.LAYER2,
        ),
        _make_rollback_to_archive_handler(engine),
    )

    registry.register(
        ToolDef(
            name="get_extended_tools",
            description="启用 Layer 2 扩展工具（需要 Operator 角色调用）。",
            input_schema={
                "type": "object",
                "properties": {"agent_id": {"type": "string"}},
            },
            layer=ToolLayer.LAYER1,
        ),
        _make_enable_layer2_handler(registry, logger),
    )

    logger.debug("Evolution 模块工具注册完成 count=11")


def _make_report_experience_handler(engine: EvolutionEngine):
    async def handler(params: Dict):
        try:
            result = await engine.report_experience(
                agent_id=params.get("agent_id", ""),
                skill_type=params.get("skill_type", ""),
                exp_type=params.get("type", "positive"),
                category=params.get("category", "general"),
                description=params.get("description", ""),
                evidence=params.get("evidence", ""),
                confidence=float(params.get("confidence", 0.7)),
                severity=float(params.get("severity", 0.5)),
            )
            return new_json_result(result)
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_get_experiences_handler(engine: EvolutionEngine):
    async def handler(params: Dict):
        try:
            exps = await engine.get_experiences(
                skill_type=params.get("skill_type", ""),
                exp_type=params.get("type", ""),
                limit=params.get("limit", 20),
            )
            return new_json_result({"experiences": exps, "count": len(exps)})
        except Exception as e:
            return new_error_result(str(e))
    return handler



def _make_distill_advanced_handler(engine: EvolutionEngine):
    async def handler(params: Dict):
        try:
            p = DistillAndEvolveParams(
                skill_type=params["skill_type"],
                auto_apply=params.get("auto_apply", True),
                include_stale=params.get("include_stale", True),
                max_proposals=params.get("max_proposals", 5),
            )
            result = await engine.distill_and_evolve_advanced(p)
            return new_json_result(result.to_dict())
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_audit_handler(engine: EvolutionEngine):
    async def handler(params: Dict):
        try:
            result = await engine.audit_skill_quality(params["skill_type"])
            return new_json_result(result)
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_get_status_handler(engine: EvolutionEngine):
    async def handler(params: Dict):
        try:
            result = await engine.get_evolution_status()
            return new_json_result(result)
        except Exception as e:
            return new_error_result(str(e))
    return handler



def _make_approve_evolution_handler(engine: EvolutionEngine):
    async def handler(params: Dict):
        try:
            result = await engine.approve_evolution_v2(
                evo_id=params["evo_id"],
                action=params["action"],
                modification=params.get("modification", ""),
                approver=params.get("approver", ""),
                approval_reason=params.get("approval_reason", ""),
            )
            return new_json_result(result)
        except Exception as e:
            return new_error_result(str(e))
    return handler



def _make_rollback_to_archive_handler(engine: EvolutionEngine):
    async def handler(params: Dict):
        try:
            result = await engine.rollback_to_archive(params["archive_id"])
            return new_json_result(result)
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_safety_report_handler(engine: EvolutionEngine):
    async def handler(params: Dict):
        try:
            result = await engine.get_safety_report()
            return new_json_result(result)
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_snapshot_agent_handler(engine: EvolutionEngine):
    async def handler(params: Dict):
        try:
            result = await engine.snapshot_agent(
                trigger=params.get("trigger", "manual"),
                note=params.get("note", ""),
            )
            return new_json_result(result)
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_trigger_evolution_handler(engine: EvolutionEngine):
    async def handler(params: Dict):
        try:
            result = await engine.trigger_evolution_v2(
                scope=params.get("scope", "all"),
                target=params.get("target", ""),
                force=params.get("force", False),
            )
            return new_json_result(result)
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_enable_layer2_handler(registry: Registry, logger: logging.Logger):
    async def handler(params: Dict):
        registry.enable_layer2()
        total, l1, l2 = registry.stats()
        logger.info(f"Layer 2 工具已启用 agent_id={params.get('agent_id', '')}")
        return new_json_result({
            "status": "layer2_enabled",
            "total_tools": total,
            "layer1_tools": l1,
            "layer2_tools": l2,
        })
    return handler
