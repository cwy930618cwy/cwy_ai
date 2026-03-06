import logging
from typing import Dict

from agentflow.mcp_server import Registry, ToolDef, ToolLayer, new_json_result, new_error_result
from .guard import SafetyGuard


def register_tools(registry: Registry, guard: SafetyGuard, logger: logging.Logger) -> None:
    # 注意：get_health_check 已移至 dashboard 模块注册

    logger.debug("Safety 模块工具注册完成 count=0 (get_safety_report 在 evolution 模块中注册)")