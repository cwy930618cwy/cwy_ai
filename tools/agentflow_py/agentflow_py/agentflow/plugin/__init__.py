"""
插件/扩展系统

设计目标：
  - 允许外部模块注册自定义工具，无需修改 AgentFlow 内部代码
  - 支持 HTTP 远程插件（调用外部 HTTP 服务）
  - Plugin 生命周期管理（加载/卸载/升级/健康检查）
  - Plugin 注册表和发现机制
  - Plugin 崩溃隔离（不影响主服务）

插件协议（HTTP Plugin Protocol）：
  外部服务需实现以下 HTTP 端点：
    GET  /plugin/info     — 返回插件元信息（名称/版本/工具列表）
    GET  /plugin/tools    — 返回工具定义列表（JSON Schema）
    POST /plugin/call     — 调用工具（请求体: {tool: string, params: object}）
    GET  /plugin/health   — 健康检查（返回 200 表示正常）

使用方式：
    # 注册 HTTP 远程插件
    await mgr.register(PluginConfig(
        id="my-plugin",
        name="我的插件",
        type=PluginType.HTTP,
        address="http://localhost:8090",
    ))
"""

from .interfaces import (
    PluginType,
    PluginStatus,
    PluginConfig,
    PluginInfo,
    PluginToolDef,
    PluginManifest,
    Plugin,
    PluginRegistry,
)
from .http_plugin import HTTPPlugin
from .manager import Manager
from .tools import register_tools

__all__ = [
    # 枚举类型
    "PluginType",
    "PluginStatus",
    # 数据类
    "PluginConfig",
    "PluginInfo",
    "PluginToolDef",
    "PluginManifest",
    # 接口
    "Plugin",
    "PluginRegistry",
    # 实现
    "HTTPPlugin",
    "Manager",
    # 工具注册
    "register_tools",
]
