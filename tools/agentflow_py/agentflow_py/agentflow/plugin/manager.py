"""
Plugin 生命周期管理器

负责插件的注册、加载、卸载、健康检查和工具注册。
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..mcp_server.registry import Registry
from ..mcp_server.types import ToolDef, ToolLayer, ToolResult, new_error_result, new_json_result
from .http_plugin import HTTPPlugin
from .interfaces import (
    Plugin,
    PluginConfig,
    PluginInfo,
    PluginManifest,
    PluginStatus,
    PluginType,
)


class Manager:
    """
    Plugin 生命周期管理器
    负责插件的注册、加载、卸载、健康检查和工具注册
    """

    def __init__(self, registry: Registry, logger: Optional[logging.Logger] = None):
        self._plugins: Dict[str, Plugin] = {}
        self._registry = registry
        self._logger = logger or logging.getLogger("agentflow.plugin")
        self._lock = asyncio.Lock()
        self._stop_event = asyncio.Event()

    async def register(self, config: PluginConfig) -> PluginInfo:
        """注册并加载插件"""
        if not config.id:
            raise ValueError("插件 ID 不能为空")
        
        if not config.address:
            raise ValueError("HTTP 插件必须指定 address")

        async with self._lock:
            # 检查是否已注册
            if config.id in self._plugins:
                raise ValueError(f'插件 "{config.id}" 已注册，请先卸载再重新注册')

            # 创建插件实例
            plugin: Plugin
            if config.type == PluginType.HTTP:
                plugin = HTTPPlugin(config, self._logger)
            else:
                raise ValueError(f"不支持的插件类型: {config.type}（支持: http）")

            # 获取插件清单（验证连通性）
            try:
                manifest = await plugin.manifest()
            except Exception as e:
                await plugin.unload()
                raise ValueError(f'加载插件 "{config.id}" 失败（无法获取清单）: {e}') from e

            # 注册插件工具到 MCP Registry
            await self._register_plugin_tools(config.id, manifest, plugin)

            # 保存插件
            self._plugins[config.id] = plugin

            self._logger.info(
                f"插件已加载: plugin_id={config.id}, "
                f"name={manifest.name}, version={manifest.version}, "
                f"tools={len(manifest.tools)}"
            )

            return plugin.info()

    async def _register_plugin_tools(
        self, plugin_id: str, manifest: PluginManifest, plugin: Plugin
    ) -> None:
        """将插件工具注册到 MCP Registry"""
        for tool_def in manifest.tools:
            # 为插件工具添加前缀，避免与内置工具冲突
            tool_name = f"plugin_{plugin_id}_{tool_def.name}"

            # 捕获闭包变量
            captured_tool_name = tool_def.name
            captured_plugin = plugin

            input_schema = tool_def.input_schema
            if not input_schema:
                input_schema = {"type": "object", "properties": {}}

            # 创建工具定义
            defn = ToolDef(
                name=tool_name,
                description=f"[Plugin: {manifest.name}] {tool_def.description}",
                input_schema=input_schema,
                layer=ToolLayer.LAYER1,
            )

            # 创建工具处理器
            async def handler(params: Dict) -> ToolResult:
                return await self._call_with_recovery(
                    captured_plugin, captured_tool_name, params
                )

            self._registry.register(defn, handler)
            self._logger.debug(f"插件工具已注册: tool={tool_name}, plugin={plugin_id}")

    async def _call_with_recovery(
        self, plugin: Plugin, tool_name: str, params: Dict
    ) -> ToolResult:
        """带崩溃隔离的工具调用"""
        try:
            result = await plugin.call(tool_name, params)
            
            # 如果结果已经是 ToolResult 格式
            if isinstance(result, ToolResult):
                return result
            
            # 如果结果是字典，包装为 JSON 结果
            if isinstance(result, dict):
                # 检查是否是 ToolResult 格式的字典
                if "content" in result:
                    return new_json_result(result)
                # 普通结果直接返回
                return new_json_result(result)
            
            return new_json_result(result)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._logger.error(
                f"插件工具调用异常: plugin={plugin.id()}, tool={tool_name}, error={e}"
            )
            return new_error_result(f"插件崩溃: {e}")

    async def unload(self, plugin_id: str) -> None:
        """卸载插件"""
        async with self._lock:
            plugin = self._plugins.get(plugin_id)
            if not plugin:
                raise ValueError(f'插件 "{plugin_id}" 不存在')

            try:
                await plugin.unload()
            except Exception as e:
                self._logger.warning(f"卸载插件时出错: plugin_id={plugin_id}, error={e}")

            # 从 MCP Registry 中清理该插件注册的所有工具
            removed = self._registry.unregister_by_prefix(f"plugin_{plugin_id}_")
            if removed:
                self._logger.info(f"已从 Registry 注销插件工具: plugin_id={plugin_id}, count={removed}")

            del self._plugins[plugin_id]
            self._logger.info(f"插件已卸载: plugin_id={plugin_id}")

    def get(self, plugin_id: str) -> Optional[PluginInfo]:
        """获取插件信息"""
        plugin = self._plugins.get(plugin_id)
        if not plugin:
            return None
        return plugin.info()

    def list(self) -> List[PluginInfo]:
        """列出所有插件"""
        return [plugin.info() for plugin in self._plugins.values()]

    async def call_tool(
        self, plugin_id: str, tool_name: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """调用插件工具（带崩溃隔离）"""
        plugin = self._plugins.get(plugin_id)
        if not plugin:
            raise ValueError(f'插件 "{plugin_id}" 不存在')

        return await plugin.call(tool_name, params)

    async def health_check_all(self) -> Dict[str, Optional[Exception]]:
        """对所有插件执行健康检查"""
        results: Dict[str, Optional[Exception]] = {}
        
        # 复制插件列表以避免并发问题
        plugins = dict(self._plugins)
        
        for plugin_id, plugin in plugins.items():
            try:
                await plugin.health_check()
                results[plugin_id] = None
            except Exception as e:
                results[plugin_id] = e

        return results

    def start_health_check_loop(self, interval: int = 60) -> asyncio.Task:
        """
        启动后台健康检查循环
        
        Args:
            interval: 健康检查间隔秒数
            
        Returns:
            后台任务
        """
        async def health_check_loop():
            while not self._stop_event.is_set():
                try:
                    await asyncio.sleep(interval)
                    results = await self.health_check_all()
                    
                    for plugin_id, error in results.items():
                        if error:
                            self._logger.warning(
                                f"插件健康检查失败: plugin_id={plugin_id}, error={error}"
                            )
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self._logger.error(f"健康检查循环异常: {e}")

        return asyncio.create_task(health_check_loop())

    async def stop(self) -> None:
        """停止 Manager"""
        self._stop_event.set()

        # 卸载所有插件
        async with self._lock:
            for plugin_id, plugin in list(self._plugins.items()):
                try:
                    await plugin.unload()
                except Exception as e:
                    self._logger.warning(
                        f"停止时卸载插件失败: plugin_id={plugin_id}, error={e}"
                    )
            self._plugins.clear()
