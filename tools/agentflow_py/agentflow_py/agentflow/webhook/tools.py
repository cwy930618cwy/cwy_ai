"""
Webhook MCP 工具

移植自 Go 工程 internal/webhook/tools.go

提供以下工具:
- webhook_add: 添加 Webhook 端点
- webhook_remove: 删除 Webhook 端点
- webhook_list: 列出所有端点
- webhook_test: 发送测试事件
"""

import json
import logging
from typing import Dict, Any

from agentflow.mcp_server.types import ToolDef, ToolLayer, ToolResult, new_json_result, new_error_result
from agentflow.mcp_server.registry import Registry
from .model import EventType, WebhookEndpoint
from .dispatcher import Dispatcher


def register_tools(registry: Registry, dispatcher: Dispatcher) -> None:
    """
    注册 Webhook 管理 MCP 工具
    
    Args:
        registry: MCP 工具注册表
        dispatcher: Webhook 分发器
    """

    # webhook_add: 添加 Webhook 端点
    async def webhook_add(params: Dict) -> ToolResult:
        """添加 Webhook 端点"""
        url = params.get("url", "")
        if not url:
            return new_error_result("url 不能为空")

        # 解析事件类型
        event_types = []
        raw_types = params.get("event_types", [])
        if raw_types:
            for et in raw_types:
                if isinstance(et, str):
                    try:
                        event_types.append(EventType(et))
                    except ValueError:
                        return new_error_result(f"无效的事件类型: {et}")

        secret = params.get("secret", "")

        ep = WebhookEndpoint(
            url=url,
            event_types=event_types,
            secret=secret,
        )

        try:
            await dispatcher.add_endpoint(ep)
        except Exception as e:
            return new_error_result(f"添加 Webhook 失败: {e}")

        return new_json_result({
            "id": ep.id,
            "url": ep.url,
            "event_types": [et.value for et in ep.event_types],
            "enabled": ep.enabled,
            "created_at": ep.created_at,
            "message": "✅ Webhook 端点已添加",
        })

    registry.register(
        ToolDef(
            name="webhook_add",
            description="添加 Webhook 端点。当指定事件发生时，AgentFlow 会向该 URL 发送 HTTP POST 通知。",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Webhook 接收 URL（必须是 http/https）",
                    },
                    "event_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要订阅的事件类型列表。可选值：task_completed/task_failed/agent_blocked/evolution_triggered/safety_alert/experience_reported。留空表示接收所有事件。",
                    },
                    "secret": {
                        "type": "string",
                        "description": "HMAC 签名密钥（可选）。设置后，每次请求会在 X-AgentFlow-Signature 头中附带 sha256 签名。",
                    },
                },
                "required": ["url"],
            },
            layer=ToolLayer.LAYER1,
        ),
        webhook_add,
    )

    # webhook_list: 列出所有 Webhook 端点
    async def webhook_list(params: Dict) -> ToolResult:
        """列出所有 Webhook 端点"""
        try:
            endpoints = await dispatcher.list_endpoints()
        except Exception as e:
            return new_error_result(f"获取 Webhook 列表失败: {e}")

        if not endpoints:
            return new_json_result({
                "endpoints": [],
                "total": 0,
                "message": "暂无 Webhook 端点，使用 webhook_add 添加",
            })

        return new_json_result({
            "endpoints": [ep.to_dict() for ep in endpoints],
            "total": len(endpoints),
        })

    registry.register(
        ToolDef(
            name="webhook_list",
            description="列出所有已配置的 Webhook 端点。",
            input_schema={"type": "object", "properties": {}},
            layer=ToolLayer.LAYER1,
        ),
        webhook_list,
    )

    # webhook_remove: 删除 Webhook 端点
    async def webhook_remove(params: Dict) -> ToolResult:
        """删除 Webhook 端点"""
        id_ = params.get("id", "")
        if not id_:
            return new_error_result("id 不能为空")

        try:
            await dispatcher.remove_endpoint(id_)
        except Exception as e:
            return new_error_result(f"删除 Webhook 失败: {e}")

        return new_json_result({
            "id": id_,
            "message": "✅ Webhook 端点已删除",
        })

    registry.register(
        ToolDef(
            name="webhook_remove",
            description="删除指定 ID 的 Webhook 端点。",
            input_schema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "要删除的 Webhook 端点 ID（从 webhook_list 获取）",
                    },
                },
                "required": ["id"],
            },
            layer=ToolLayer.LAYER1,
        ),
        webhook_remove,
    )

    # webhook_test: 发送测试事件
    async def webhook_test(params: Dict) -> ToolResult:
        """发送测试事件"""
        url = params.get("url", "")
        if not url:
            return new_error_result("url 不能为空")

        try:
            await dispatcher.test_endpoint(url)
        except Exception as e:
            return new_json_result({
                "url": url,
                "success": False,
                "error": str(e),
                "message": "❌ 测试失败，请检查 URL 是否可达",
            })

        return new_json_result({
            "url": url,
            "success": True,
            "message": "✅ 测试事件发送成功",
        })

    registry.register(
        ToolDef(
            name="webhook_test",
            description="向指定 URL 发送一条测试 Webhook 事件，验证端点是否可达。",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "要测试的 Webhook URL",
                    },
                },
                "required": ["url"],
            },
            layer=ToolLayer.LAYER1,
        ),
        webhook_test,
    )
