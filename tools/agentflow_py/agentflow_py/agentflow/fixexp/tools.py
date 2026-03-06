import logging
from typing import Dict

from agentflow.mcp_server import Registry, ToolDef, ToolLayer, new_json_result, new_error_result
from .engine import FixExpEngine
from .store import FixExpStore


def register_tools(registry: Registry, engine: FixExpEngine, store: FixExpStore,
                   logger: logging.Logger) -> None:

    registry.register(
        ToolDef(
            name="query_fix_experience",
            description=(
                "查询修复经验。根据error_type和问题描述检索最相关的历史修复经验（TF-IDF+时间衰减评分）。"
                "首次调用会自动创建修复会话。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "agent_id": {"type": "string"},
                    "error_type": {"type": "string", "description": "错误类型(如 compile_error/runtime_error/test_failure)"},
                    "problem": {"type": "string", "description": "问题描述"},
                    "create_if_missing": {"type": "boolean", "default": True},
                },
                "required": ["task_id", "agent_id", "error_type", "problem"],
            },
            layer=ToolLayer.LAYER1,
        ),
        _make_query_handler(engine),
    )

    registry.register(
        ToolDef(
            name="report_fix_attempt",
            description=(
                "上报修复尝试。包含三级防死循环检测：相似度>60%警告/85%阻断/同方案>2次强制阻断。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "agent_id": {"type": "string"},
                    "approach": {"type": "string", "description": "修复方案描述"},
                    "reasoning": {"type": "string", "description": "方案推理过程"},
                    "result": {"type": "string", "enum": ["success", "failure", "partial", "blocked"]},
                    "result_detail": {"type": "string"},
                    "modified_files": {"type": "array", "items": {"type": "string"}},
                    "code_changes": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["session_id", "agent_id", "approach", "result"],
            },
            layer=ToolLayer.LAYER1,
        ),
        _make_report_attempt_handler(engine),
    )

    registry.register(
        ToolDef(
            name="close_fix_session",
            description="关闭修复会话。记录最终解决方案和经验。",
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "resolution": {"type": "string", "description": "最终解决方案"},
                    "final_experience": {"type": "string", "description": "值得记录的经验"},
                },
                "required": ["session_id", "resolution"],
            },
            layer=ToolLayer.LAYER1,
        ),
        _make_close_handler(store),
    )

    registry.register(
        ToolDef(
            name="update_fix_attempt_label",
            description="对修复尝试打标签（good/bad/misleading）。用于改进经验质量。",
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "attempt_id": {"type": "string"},
                    "label": {"type": "string", "enum": ["good", "bad", "misleading"]},
                },
                "required": ["session_id", "attempt_id", "label"],
            },
            layer=ToolLayer.LAYER1,
        ),
        _make_label_handler(store),
    )

    registry.register(
        ToolDef(
            name="feedback_experience",
            description=(
                "对经验质量进行反馈。支持正向(helpful)和负面(negative/misleading/irrelevant/outdated)反馈。"
                "负面反馈需要选择具体的负面词标签(如 misleading/not_applicable/outdated 等)。"
                "反馈会影响经验的有效可信度(衰减因子)。misleading 反馈累计≥3次将触发经验拉黑。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "exp_id": {"type": "string", "description": "经验/会话ID"},
                    "session_id": {"type": "string"},
                    "feedback_type": {
                        "type": "string",
                        "enum": ["helpful", "negative", "misleading", "irrelevant", "outdated"],
                        "description": "反馈类型",
                    },
                    "negative_tags": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "not_applicable",
                                "misleading",
                                "outdated",
                                "too_vague",
                                "wrong_root_cause",
                                "partial_match",
                                "duplicate_effort",
                                "context_mismatch",
                            ],
                        },
                        "description": "负面词标签（多选，仅负面反馈时有效）",
                    },
                    "reason": {"type": "string", "description": "反馈原因说明"},
                    "note": {"type": "string", "description": "备注（兼容旧接口）"},
                },
                "required": ["exp_id", "session_id", "feedback_type"],
            },
            layer=ToolLayer.LAYER1,
        ),
        _make_feedback_handler(engine),
    )

    logger.debug("FixExp 模块工具注册完成 count=5")


def _make_query_handler(engine: FixExpEngine):
    async def handler(params: Dict):
        try:
            result = await engine.query_fix_experience(
                task_id=params["task_id"],
                agent_id=params["agent_id"],
                error_type=params["error_type"],
                problem=params["problem"],
                create_if_missing=params.get("create_if_missing", True),
            )
            return new_json_result(result)
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_report_attempt_handler(engine: FixExpEngine):
    async def handler(params: Dict):
        try:
            result = await engine.report_fix_attempt(
                session_id=params["session_id"],
                agent_id=params["agent_id"],
                approach=params["approach"],
                reasoning=params.get("reasoning", ""),
                result=params["result"],
                result_detail=params.get("result_detail", ""),
                modified_files=params.get("modified_files"),
                code_changes=params.get("code_changes", ""),
                confidence=float(params.get("confidence", 0.5)),
            )
            return new_json_result(result)
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_close_handler(store: FixExpStore):
    async def handler(params: Dict):
        try:
            session = await store.close_session(
                params["session_id"],
                params["resolution"],
                params.get("final_experience", ""),
            )
            return new_json_result({
                "status": "closed",
                "session": session.to_dict() if session else None,
            })
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_label_handler(store: FixExpStore):
    async def handler(params: Dict):
        try:
            found = await store.update_attempt_label(
                params["session_id"], params["attempt_id"], params["label"]
            )
            return new_json_result({"status": "updated" if found else "not_found"})
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_feedback_handler(engine: FixExpEngine):
    async def handler(params: Dict):
        try:
            result = await engine.feedback_experience(
                exp_id=params["exp_id"],
                session_id=params["session_id"],
                feedback_type=params.get("feedback_type", params.get("label", "negative")),
                negative_tags=params.get("negative_tags"),
                reason=params.get("reason", ""),
                note=params.get("note", ""),
            )
            return new_json_result(result)
        except Exception as e:
            return new_error_result(str(e))
    return handler
