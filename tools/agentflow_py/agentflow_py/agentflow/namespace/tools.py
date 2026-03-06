"""
命名空间 MCP 工具注册

提供 create_namespace, list_namespaces, delete_namespace 三个工具
"""

import json
import logging
from typing import TYPE_CHECKING

from agentflow.mcp_server.types import ToolDef, ToolLayer, ToolResult, new_json_result, new_error_result

if TYPE_CHECKING:
    from agentflow.mcp_server.registry import Registry
    from .manager import NamespaceManager


def register_tools(registry: "Registry", mgr: "NamespaceManager", logger: logging.Logger) -> None:
    """
    注册命名空间管理 MCP 工具

    Args:
        registry: MCP 工具注册表
        mgr: 命名空间管理器
        logger: 日志记录器
    """

    # Tool: create_namespace
    registry.register(ToolDef(
        name="create_namespace",
        description="""创建一个新的项目命名空间（多租户隔离）。每个 namespace 对应独立的数据域，不同 namespace 的任务/目标/经验数据完全隔离。
创建后可在 claim_task、create_tasks 等工具中通过 namespace 参数指定数据域。""",
        input_schema={
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "命名空间 ID（如项目ID，建议使用 proj_xxx 格式）"},
                "name": {"type": "string", "description": "命名空间显示名称"},
                "description": {"type": "string", "description": "命名空间描述（可选）"}
            },
            "required": ["id", "name"]
        },
        layer=ToolLayer.LAYER1,
    ), _make_create_handler(mgr, logger))

    # Tool: list_namespaces
    registry.register(ToolDef(
        name="list_namespaces",
        description="列出所有已注册的项目命名空间。",
        input_schema={"type": "object", "properties": {}},
        layer=ToolLayer.LAYER1,
    ), _make_list_handler(mgr, logger))

    # Tool: delete_namespace
    registry.register(ToolDef(
        name="delete_namespace",
        description="""从注册表中删除命名空间（不删除实际数据，仅移除注册信息）。
⚠️ 删除后该 namespace 下的数据仍存在于 Redis 中，但不再被系统识别。""",
        input_schema={
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "要删除的命名空间 ID"},
                "confirm": {"type": "string", "description": "确认标记，必须为 'CONFIRM_DELETE'"}
            },
            "required": ["id", "confirm"]
        },
        layer=ToolLayer.LAYER1,
    ), _make_delete_handler(mgr, logger))

    logger.info("命名空间 MCP 工具注册完成: create_namespace, list_namespaces, delete_namespace")


def _make_create_handler(mgr: "NamespaceManager", logger: logging.Logger):
    """创建 create_namespace 工具处理器"""
    async def handler(params: dict) -> ToolResult:
        ns_id = params.get("id", "")
        name = params.get("name", "")
        description = params.get("description", "")

        if not ns_id:
            return new_error_result("参数 'id' 不能为空")
        if not name:
            return new_error_result("参数 'name' 不能为空")

        try:
            ns = await mgr.register(ns_id, name, description)
            return new_json_result({
                "success": True,
                "namespace": ns.to_dict(),
                "message": f"✅ 命名空间 {ns_id!r} 已创建，后续操作可通过 namespace={ns_id!r} 参数隔离数据"
            })
        except Exception as e:
            logger.error(f"创建命名空间失败: {e}")
            return new_error_result(str(e))

    return handler


def _make_list_handler(mgr: "NamespaceManager", logger: logging.Logger):
    """创建 list_namespaces 工具处理器"""
    async def handler(params: dict) -> ToolResult:
        try:
            namespaces = await mgr.list()
            return new_json_result({
                "namespaces": [ns.to_dict() for ns in namespaces],
                "total": len(namespaces)
            })
        except Exception as e:
            logger.error(f"列出命名空间失败: {e}")
            return new_error_result(str(e))

    return handler


def _make_delete_handler(mgr: "NamespaceManager", logger: logging.Logger):
    """创建 delete_namespace 工具处理器"""
    async def handler(params: dict) -> ToolResult:
        ns_id = params.get("id", "")
        confirm = params.get("confirm", "")

        if not ns_id:
            return new_error_result("参数 'id' 不能为空")
        if confirm != "CONFIRM_DELETE":
            return new_error_result("confirm 必须为 'CONFIRM_DELETE'")

        try:
            await mgr.delete(ns_id)
            return new_json_result({
                "success": True,
                "message": f"✅ 命名空间 {ns_id!r} 已从注册表删除"
            })
        except Exception as e:
            logger.error(f"删除命名空间失败: {e}")
            return new_error_result(str(e))

    return handler
