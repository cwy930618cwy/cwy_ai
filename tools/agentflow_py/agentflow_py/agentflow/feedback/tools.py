import logging
from typing import Dict

from agentflow.mcp_server import Registry, ToolDef, ToolLayer, new_json_result, new_error_result
from .store import FeedbackStore


def register_tools(registry: Registry, store: FeedbackStore, logger: logging.Logger) -> None:

    registry.register(
        ToolDef(
            name="agent_complaint",
            description=(
                "Agent上报吐槽或投诉。"
                "category: workflow/tool/skill/context/performance/other。"
                "severity: minor（轻微）/frustrating（令人沮丧）/blocking（严重阻塞）。"
                "related_tool/related_skill 用于热点统计和进化提案生成。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": ["workflow", "tool", "skill", "context", "performance", "other"],
                    },
                    "description": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["minor", "frustrating", "blocking"],
                        "default": "minor",
                    },
                    "affected_task_id": {"type": "string"},
                    "related_tool": {"type": "string", "description": "关联工具名"},
                    "related_skill": {"type": "string", "description": "关联 Skill"},
                    "suggestion": {"type": "string", "description": "改进建议"},
                },
                "required": ["agent_id", "category", "description"],
            },
            layer=ToolLayer.LAYER1,
        ),
        _make_complaint_handler(store),
    )

    registry.register(
        ToolDef(
            name="get_complaint_stats",
            description="获取吐槽统计（按类别/严重程度/工具/Skill分组，含热点检测）。",
            input_schema={"type": "object", "properties": {}},
            layer=ToolLayer.LAYER2,
        ),
        _make_stats_handler(store),
    )

    registry.register(
        ToolDef(
            name="list_complaints",
            description="分页查询吐槽记录（逆序，最新优先）。",
            input_schema={
                "type": "object",
                "properties": {
                    "cursor": {"type": "integer", "default": 0, "description": "分页偏移量"},
                    "limit": {"type": "integer", "default": 20, "description": "每页数量（最大50）"},
                    "filter_category": {"type": "string", "description": "按类型过滤（空表示全部）"},
                },
            },
            layer=ToolLayer.LAYER2,
        ),
        _make_list_handler(store),
    )

    logger.debug("Feedback 模块工具注册完成 count=3")


def _make_complaint_handler(store: FeedbackStore):
    async def handler(params: Dict):
        try:
            result = await store.report_complaint(
                agent_id=params["agent_id"],
                category=params["category"],
                description=params["description"],
                severity=params.get("severity", "minor"),
                affected_task_id=params.get("affected_task_id", ""),
                related_tool=params.get("related_tool", ""),
                related_skill=params.get("related_skill", ""),
                suggestion=params.get("suggestion", ""),
            )
            return new_json_result(result)
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_stats_handler(store: FeedbackStore):
    async def handler(params: Dict):
        try:
            stats = await store.get_stats()
            return new_json_result(stats)
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_list_handler(store: FeedbackStore):
    async def handler(params: Dict):
        try:
            records, next_cursor, has_more = await store.get_complaints(
                cursor=int(params.get("cursor", 0)),
                limit=int(params.get("limit", 20)),
                filter_category=params.get("filter_category", ""),
            )
            return new_json_result({
                "records": records,
                "next_cursor": next_cursor,
                "has_more": has_more,
                "count": len(records),
            })
        except Exception as e:
            return new_error_result(str(e))
    return handler
