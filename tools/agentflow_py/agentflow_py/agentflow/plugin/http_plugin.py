"""
HTTP 远程插件客户端实现

通过 HTTP 协议与外部插件服务通信。
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, Optional

import aiohttp

from .interfaces import (
    Plugin,
    PluginConfig,
    PluginInfo,
    PluginManifest,
    PluginToolDef,
    PluginStatus,
)


class HTTPPlugin(Plugin):
    """
    HTTP 远程插件实现
    通过 HTTP 协议与外部插件服务通信
    """

    def __init__(self, config: PluginConfig, logger: Optional[logging.Logger] = None):
        self._config = config
        self._info = PluginInfo(
            config=config,
            status=PluginStatus.LOADING,
            loaded_at=datetime.now(),
        )
        self._logger = logger or logging.getLogger("agentflow.plugin")
        self._session: Optional[aiohttp.ClientSession] = None
        self._lock: Optional[asyncio.Lock] = None

    @property
    def lock(self) -> asyncio.Lock:
        """懒创建 asyncio.Lock，避免 event loop 绑定问题"""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 HTTP 会话"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self._config.timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close_session(self) -> None:
        """关闭 HTTP 会话"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def id(self) -> str:
        """返回插件唯一标识"""
        return self._config.id

    def info(self) -> PluginInfo:
        """返回插件运行时信息"""
        return self._info

    async def manifest(self) -> PluginManifest:
        """获取插件清单"""
        try:
            data = await self._do_get("/plugin/info")
            
            # 解析工具列表
            tools = []
            for tool_data in data.get("tools", []):
                tool = PluginToolDef(
                    name=tool_data.get("name", ""),
                    description=tool_data.get("description", ""),
                    input_schema=tool_data.get("input_schema", {"type": "object", "properties": {}}),
                )
                tools.append(tool)

            manifest = PluginManifest(
                id=data.get("id", self._config.id),
                name=data.get("name", self._config.name),
                version=data.get("version", "unknown"),
                description=data.get("description", ""),
                tools=tools,
            )

            # 更新插件信息
            async with self.lock:
                self._info.version = manifest.version
                self._info.tool_count = len(manifest.tools)
                self._info.status = PluginStatus.ACTIVE

            return manifest

        except Exception as e:
            self._logger.error(f"获取插件清单失败: plugin={self._config.id}, error={e}")
            raise

    async def call(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """调用插件工具"""
        try:
            body = {
                "tool": tool_name,
                "params": params,
            }
            data = await self._do_post("/plugin/call", body)
            return data

        except Exception as e:
            self._logger.error(
                f"调用插件工具失败: plugin={self._config.id}, tool={tool_name}, error={e}"
            )
            raise

    async def health_check(self) -> None:
        """健康检查"""
        url = self._config.address + "/plugin/health"
        session = self._get_session()
        headers = self._build_headers()
        timeout = aiohttp.ClientTimeout(total=self._config.timeout)
        try:
            async with session.get(url, headers=headers, timeout=timeout) as resp:
                status_code = resp.status

            async with self.lock:
                self._info.last_check_at = datetime.now()
                if status_code == 200:
                    self._info.status = PluginStatus.ACTIVE
                    self._info.error_msg = ""
                else:
                    self._info.status = PluginStatus.ERROR
                    self._info.error_msg = f"健康检查返回 HTTP {status_code}"

            if status_code != 200:
                raise Exception(f"插件 {self._config.id} 健康检查返回 HTTP {status_code}")

        except Exception as e:
            async with self.lock:
                self._info.status = PluginStatus.ERROR
                self._info.error_msg = str(e)
                self._info.last_check_at = datetime.now()
            
            self._logger.warning(f"插件健康检查失败: plugin={self._config.id}, error={e}")
            raise

    async def unload(self) -> None:
        """卸载插件"""
        async with self.lock:
            self._info.status = PluginStatus.INACTIVE
        
        await self.close_session()
        self._logger.info(f"插件已卸载: plugin={self._config.id}")

    # ==================== 辅助方法 ====================

    async def _do_get(self, path: str) -> Dict[str, Any]:
        """执行 GET 请求并返回 JSON 数据"""
        url = self._config.address + path
        session = self._get_session()
        
        headers = self._build_headers()
        
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"HTTP {resp.status}: {text}")
            return await resp.json()

    async def _do_get_raw(self, path: str) -> aiohttp.ClientResponse:
        """执行 GET 请求并返回原始响应"""
        url = self._config.address + path
        session = self._get_session()
        
        headers = self._build_headers()
        
        # 注意：调用者需要手动关闭响应
        return await session.get(url, headers=headers)

    async def _do_post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """执行 POST 请求并返回 JSON 数据"""
        url = self._config.address + path
        session = self._get_session()
        
        headers = self._build_headers()
        headers["Content-Type"] = "application/json"
        
        async with session.post(url, json=body, headers=headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"HTTP {resp.status}: {text}")
            return await resp.json()

    def _build_headers(self) -> Dict[str, str]:
        """构建请求头"""
        headers = {
            "User-Agent": "AgentFlow-Plugin-Client/1.0",
        }
        if self._config.token:
            headers["Authorization"] = f"Bearer {self._config.token}"
        return headers
