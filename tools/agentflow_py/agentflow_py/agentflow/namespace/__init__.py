"""
命名空间管理模块 - 提供多租户/多项目命名空间管理

每个 namespace 对应一个独立的数据隔离域（project_id）
Redis key 格式：{keyPrefix}:{namespace}:{resource}:{id}
如：af:proj_abc123:task:task_xxx
"""

from .manager import NamespaceInfo, NamespaceManager
from .tools import register_tools

__all__ = ["NamespaceInfo", "NamespaceManager", "register_tools"]
