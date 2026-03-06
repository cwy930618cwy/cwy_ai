"""
MCP 工具注册

注册 Plugin 管理相关的 MCP 工具。
"""

import asyncio
from datetime import datetime
from typing import Any, Dict

from ..mcp_server.registry import Registry
from ..mcp_server.types import ToolDef, ToolLayer, ToolResult, new_error_result, new_json_result
from .interfaces import PluginConfig, PluginType
from .manager import Manager


def register_tools(registry: Registry, manager: Manager) -> None:
    """
    注册 Plugin 管理 MCP 工具
    
    Args:
        registry: MCP 工具注册表
        manager: Plugin 管理器
    """

    # Tool: register_plugin
    registry.register(
        ToolDef(
            name="register_plugin",
            description=(
                "注册并加载外部插件（Extension）。插件通过 HTTP 协议与 AgentFlow 通信，可注册自定义工具。\n"
                "📋 插件协议：外部服务需实现以下端点：\n"
                "  GET  /plugin/info   — 返回插件元信息（名称/版本/工具列表）\n"
                "  GET  /plugin/tools  — 返回工具定义列表\n"
                "  POST /plugin/call   — 调用工具（请求体: {tool: string, params: object}）\n"
                "  GET  /plugin/health — 健康检查（返回 200 表示正常）\n"
                "注册成功后，插件工具将以 plugin_{id}_{tool_name} 格式出现在工具列表中。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "插件唯一标识（如 my-plugin）"},
                    "name": {"type": "string", "description": "插件显示名称"},
                    "description": {"type": "string", "description": "插件描述（可选）"},
                    "type": {
                        "type": "string",
                        "enum": ["http"],
                        "description": "插件类型（当前支持 http）",
                        "default": "http",
                    },
                    "address": {"type": "string", "description": "插件服务地址（如 http://localhost:8090）"},
                    "token": {"type": "string", "description": "认证令牌（可选）"},
                    "timeout_seconds": {
                        "type": "integer",
                        "description": "调用超时秒数（默认 30）",
                        "default": 30,
                    },
                },
                "required": ["id", "address"],
            },
            layer=ToolLayer.LAYER1,
        ),
        _create_register_plugin_handler(manager),
    )

    # Tool: list_plugins
    registry.register(
        ToolDef(
            name="list_plugins",
            description="列出所有已注册的插件及其状态。",
            input_schema={"type": "object", "properties": {}},
            layer=ToolLayer.LAYER1,
        ),
        _create_list_plugins_handler(manager),
    )

    # Tool: unload_plugin
    registry.register(
        ToolDef(
            name="unload_plugin",
            description="卸载插件。卸载后该插件注册的工具将不再可用（已注册的工具定义仍在列表中，但调用会返回错误）。",
            input_schema={
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "要卸载的插件 ID"}
                },
                "required": ["id"],
            },
            layer=ToolLayer.LAYER1,
        ),
        _create_unload_plugin_handler(manager),
    )

    # Tool: check_plugin_health
    registry.register(
        ToolDef(
            name="check_plugin_health",
            description="对所有已注册插件执行健康检查，返回各插件的健康状态。",
            input_schema={"type": "object", "properties": {}},
            layer=ToolLayer.LAYER1,
        ),
        _create_check_health_handler(manager),
    )


def _create_register_plugin_handler(manager: Manager):
    """创建 register_plugin 工具处理器"""
    
    async def handler(params: Dict[str, Any]) -> ToolResult:
        try:
            plugin_id = params.get("id")
            if not plugin_id:
                return new_error_result("参数 'id' 是必需的")
            
            address = params.get("address")
            if not address:
                return new_error_result("参数 'address' 是必需的")

            name = params.get("name", plugin_id)
            description = params.get("description", "")
            plugin_type = PluginType(params.get("type", "http"))
            token = params.get("token", "")
            timeout_seconds = params.get("timeout_seconds", 30)

            config = PluginConfig(
                id=plugin_id,
                name=name,
                description=description,
                type=plugin_type,
                address=address,
                token=token,
                timeout=timeout_seconds,
            )

            info = await manager.register(config)

            return new_json_result({
                "success": True,
                "plugin_id": info.config.id,
                "name": info.config.name,
                "version": info.version,
                "tool_count": info.tool_count,
                "status": info.status.value,
                "message": f"✅ 插件 \"{info.config.name}\" 已加载，注册了 {info.tool_count} 个工具（工具名前缀: plugin_{info.config.id}_）",
            })

        except ValueError as e:
            return new_error_result(str(e))
        except Exception as e:
            return new_error_result(f"注册插件失败: {e}")

    return handler


def _create_list_plugins_handler(manager: Manager):
    """创建 list_plugins 工具处理器"""
    
    async def handler(params: Dict[str, Any]) -> ToolResult:
        infos = manager.list()

        items = []
        for info in infos:
            items.append({
                "id": info.config.id,
                "name": info.config.name,
                "type": info.config.type.value,
                "address": info.config.address,
                "status": info.status.value,
                "version": info.version,
                "tool_count": info.tool_count,
                "loaded_at": info.loaded_at.isoformat(),
                "last_check_at": info.last_check_at.isoformat(),
                "error_msg": info.error_msg,
            })

        return new_json_result({
            "plugins": items,
            "total": len(items),
        })

    return handler


def _create_unload_plugin_handler(manager: Manager):
    """创建 unload_plugin 工具处理器"""
    
    async def handler(params: Dict[str, Any]) -> ToolResult:
        try:
            plugin_id = params.get("id")
            if not plugin_id:
                return new_error_result("参数 'id' 是必需的")

            await manager.unload(plugin_id)

            return new_json_result({
                "success": True,
                "message": f"✅ 插件 \"{plugin_id}\" 已卸载",
            })

        except ValueError as e:
            return new_error_result(str(e))
        except Exception as e:
            return new_error_result(f"卸载插件失败: {e}")

    return handler


def _create_check_health_handler(manager: Manager):
    """创建 check_plugin_health 工具处理器"""
    
    async def handler(params: Dict[str, Any]) -> ToolResult:
        try:
            results = await asyncio.wait_for(
                manager.health_check_all(),
                timeout=15.0
            )
        except asyncio.TimeoutError:
            return new_error_result("健康检查超时")

        health_map = {}
        all_healthy = True

        for plugin_id, error in results.items():
            if error:
                health_map[plugin_id] = {
                    "healthy": False,
                    "error": str(error),
                }
                all_healthy = False
            else:
                health_map[plugin_id] = {"healthy": True}

        return new_json_result({
            "all_healthy": all_healthy,
            "plugins": health_map,
            "checked_at": datetime.now().isoformat(),
        })

    return handler
