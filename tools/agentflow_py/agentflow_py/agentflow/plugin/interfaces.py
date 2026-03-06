"""
插件接口定义

定义插件的类型、状态、配置和核心接口。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class PluginType(str, Enum):
    """插件类型"""
    HTTP = "http"       # HTTP 远程插件
    GRPC = "grpc"       # gRPC 远程插件（未来支持）
    NATIVE = "native"   # 原生 Python 插件（进程内）


class PluginStatus(str, Enum):
    """插件状态"""
    LOADING = "loading"     # 加载中
    ACTIVE = "active"       # 正常运行
    INACTIVE = "inactive"   # 已停用
    ERROR = "error"         # 错误状态


@dataclass
class PluginConfig:
    """插件配置"""
    # ID 插件唯一标识（如 "my-plugin"）
    id: str
    # Name 插件显示名称
    name: str = ""
    # Description 插件描述
    description: str = ""
    # Type 插件类型（http/grpc/native）
    type: PluginType = PluginType.HTTP
    # Address 插件服务地址（HTTP/gRPC 插件使用）
    # 示例：http://localhost:8090
    address: str = ""
    # Token 认证令牌（可选，用于插件服务鉴权）
    token: str = ""
    # Timeout 调用超时秒数（默认 30）
    timeout: int = 30
    # HealthCheckInterval 健康检查间隔秒数（默认 60）
    health_check_interval: int = 60
    # AutoReload 是否在健康检查失败后自动重试（默认 True）
    auto_reload: bool = True
    # Metadata 自定义元数据
    metadata: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if not self.name:
            self.name = self.id


@dataclass
class PluginToolDef:
    """插件工具定义（从插件服务获取）"""
    name: str
    description: str = ""
    input_schema: Dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})


@dataclass
class PluginManifest:
    """插件清单（从 /plugin/info 获取）"""
    id: str
    name: str
    version: str
    description: str = ""
    tools: List[PluginToolDef] = field(default_factory=list)


@dataclass
class PluginInfo:
    """插件运行时信息"""
    config: PluginConfig
    status: PluginStatus = PluginStatus.LOADING
    version: str = ""
    tool_count: int = 0
    loaded_at: datetime = field(default_factory=datetime.now)
    last_check_at: datetime = field(default_factory=datetime.now)
    error_msg: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "config": {
                "id": self.config.id,
                "name": self.config.name,
                "description": self.config.description,
                "type": self.config.type.value,
                "address": self.config.address,
                "timeout": self.config.timeout,
                "health_check_interval": self.config.health_check_interval,
                "auto_reload": self.config.auto_reload,
                "metadata": self.config.metadata,
            },
            "status": self.status.value,
            "version": self.version,
            "tool_count": self.tool_count,
            "loaded_at": self.loaded_at.isoformat(),
            "last_check_at": self.last_check_at.isoformat(),
            "error_msg": self.error_msg,
        }


class Plugin(ABC):
    """
    插件接口
    所有插件类型必须实现此接口
    """

    @abstractmethod
    def id(self) -> str:
        """返回插件唯一标识"""
        pass

    @abstractmethod
    def info(self) -> PluginInfo:
        """返回插件运行时信息"""
        pass

    @abstractmethod
    async def manifest(self) -> PluginManifest:
        """获取插件清单（工具列表等）"""
        pass

    @abstractmethod
    async def call(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        调用插件工具
        
        Args:
            tool_name: 工具名称
            params: 工具参数
            
        Returns:
            工具执行结果
        """
        pass

    @abstractmethod
    async def health_check(self) -> None:
        """
        健康检查
        
        Raises:
            Exception: 健康检查失败时抛出异常
        """
        pass

    @abstractmethod
    async def unload(self) -> None:
        """卸载插件（释放资源）"""
        pass


class PluginRegistry(ABC):
    """
    插件注册表接口
    """

    @abstractmethod
    async def register(self, config: PluginConfig) -> PluginInfo:
        """注册并加载插件"""
        pass

    @abstractmethod
    async def unload(self, plugin_id: str) -> None:
        """卸载插件"""
        pass

    @abstractmethod
    def get(self, plugin_id: str) -> Optional[PluginInfo]:
        """获取插件信息"""
        pass

    @abstractmethod
    def list(self) -> List[PluginInfo]:
        """列出所有插件"""
        pass

    @abstractmethod
    async def call_tool(self, plugin_id: str, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """调用插件工具（带崩溃隔离）"""
        pass

    @abstractmethod
    async def health_check_all(self) -> Dict[str, Optional[Exception]]:
        """对所有插件执行健康检查"""
        pass
