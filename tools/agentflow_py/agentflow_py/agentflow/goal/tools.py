import logging
from typing import Dict

from agentflow.mcp_server import Registry, ToolDef, ToolLayer, new_json_result, new_error_result
from .store import GoalStore


def register_tools(registry: Registry, store: GoalStore, logger: logging.Logger) -> None:
    registry.register(
        ToolDef(
            name="create_goal",
            description="创建目标。支持子目标、阶段(phases)和标签(tags)。priority范围1-10(10最高)。",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "目标标题"},
                    "description": {"type": "string", "description": "目标描述"},
                    "priority": {"type": "integer", "description": "优先级1-10,默认5", "minimum": 1, "maximum": 10},
                    "phases": {"type": "array", "items": {"type": "string"}, "description": "阶段列表"},
                    "parent_goal_id": {"type": "string", "description": "父目标ID"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "标签"},
                },
                "required": ["title", "description"],
            },
            layer=ToolLayer.LAYER1,
        ),
        _make_create_handler(store),
    )

    registry.register(
        ToolDef(
            name="update_goal",
            description="修改目标信息。可更新title/description/status/priority/progress等字段。",
            input_schema={
                "type": "object",
                "properties": {
                    "goal_id": {"type": "string"},
                    "fields": {"type": "object", "description": "要更新的字段键值对"},
                },
                "required": ["goal_id", "fields"],
            },
            layer=ToolLayer.LAYER1,
        ),
        _make_update_handler(store),
    )

    registry.register(
        ToolDef(
            name="delete_goal",
            description="删除目标。cascade=true时级联删除子目标。confirm必须为'CONFIRM_DELETE'。",
            input_schema={
                "type": "object",
                "properties": {
                    "goal_id": {"type": "string"},
                    "cascade": {"type": "boolean"},
                    "confirm": {"type": "string", "description": "必须为CONFIRM_DELETE"},
                },
                "required": ["goal_id", "confirm"],
            },
            layer=ToolLayer.LAYER1,
        ),
        _make_delete_handler(store),
    )

    registry.register(
        ToolDef(
            name="get_goal",
            description="获取目标详情，包含阶段进度和完成度。",
            input_schema={
                "type": "object",
                "properties": {
                    "goal_id": {"type": "string"},
                    "depth": {"type": "integer", "description": "子目标递归深度,默认1"},
                },
                "required": ["goal_id"],
            },
            layer=ToolLayer.LAYER1,
        ),
        _make_get_handler(store),
    )

    registry.register(
        ToolDef(
            name="list_goals",
            description="目标列表。支持按status/statuses过滤、按name模糊搜索、分页查询。",
            input_schema={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["pending", "active", "completed", "cancelled"]},
                    "statuses": {"type": "array", "items": {"type": "string"}},
                    "name": {"type": "string", "description": "模糊搜索"},
                    "page": {"type": "integer", "default": 1},
                    "page_size": {"type": "integer", "default": 20},
                },
            },
            layer=ToolLayer.LAYER1,
        ),
        _make_list_handler(store),
    )

    logger.debug("Goal 模块工具注册完成 count=5")


def _make_create_handler(store: GoalStore):
    async def handler(params: Dict):
        try:
            goal = await store.create(
                title=params.get("title", ""),
                description=params.get("description", ""),
                priority=params.get("priority", 5),
                phases=params.get("phases"),
                parent_goal_id=params.get("parent_goal_id", ""),
                tags=params.get("tags"),
            )
            return new_json_result(goal.to_dict())
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_update_handler(store: GoalStore):
    async def handler(params: Dict):
        try:
            goal = await store.update(params["goal_id"], params.get("fields", {}))
            return new_json_result(goal.to_dict())
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_delete_handler(store: GoalStore):
    async def handler(params: Dict):
        if params.get("confirm") != "CONFIRM_DELETE":
            return new_error_result("删除确认失败: confirm 必须为 'CONFIRM_DELETE'")
        try:
            await store.delete(params["goal_id"], params.get("cascade", False))
            return new_json_result({"status": "deleted", "goal_id": params["goal_id"]})
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_get_handler(store: GoalStore):
    async def handler(params: Dict):
        try:
            goal = await store.get(params["goal_id"])
            return new_json_result(goal.to_dict())
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_list_handler(store: GoalStore):
    async def handler(params: Dict):
        try:
            goals, total = await store.list(
                status=params.get("status", ""),
                statuses=params.get("statuses"),
                name=params.get("name", ""),
                page=params.get("page", 1),
                page_size=params.get("page_size", 20),
            )
            return new_json_result({
                "goals": [g.to_dict() for g in goals],
                "total": total,
                "page": params.get("page", 1),
            })
        except Exception as e:
            return new_error_result(str(e))
    return handler
