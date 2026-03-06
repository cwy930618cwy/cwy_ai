"""Dashboard MCP 工具注册。"""
import logging
from typing import TYPE_CHECKING

from agentflow.mcp_server.types import ToolDef, ToolLayer, new_json_result, new_error_result

if TYPE_CHECKING:
    from agentflow.mcp_server.registry import Registry
    from .service import DashboardService


def register_tools(registry: "Registry", service: "DashboardService", logger: logging.Logger) -> None:
    """注册 Dashboard 模块的 MCP 工具。"""

    # Tool: get_dashboard [Layer 1]
    async def get_dashboard_handler(params: dict):
        try:
            data = await service.get_dashboard_data()
            return new_json_result(data)
        except Exception as e:
            logger.error(f"get_dashboard 错误: {e}")
            return new_error_result(str(e))

    registry.register(
        ToolDef(
            name="get_dashboard",
            description="获取AgentFlow全局仪表盘: 目标进度/任务统计/通过率/Token消耗/Skill效能/进化状态/经验库/Archive分数。",
            input_schema={"type": "object", "properties": {}},
            layer=ToolLayer.LAYER1,
        ),
        get_dashboard_handler,
    )

    # Tool: get_health_check [Layer 1]
    async def get_health_check_handler(params: dict):
        try:
            data = await service.health_check()
            return new_json_result(data)
        except Exception as e:
            logger.error(f"get_health_check 错误: {e}")
            return new_error_result(str(e))

    registry.register(
        ToolDef(
            name="get_health_check",
            description="系统健康检查: Redis连接/SQLite状态/锁泄漏/僵尸任务/进化健康度/归档状态。",
            input_schema={"type": "object", "properties": {}},
            layer=ToolLayer.LAYER1,
        ),
        get_health_check_handler,
    )

    logger.debug("Dashboard 模块工具注册完成")
