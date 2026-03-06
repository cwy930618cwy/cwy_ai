"""
命名空间管理器 - 核心业务逻辑

提供命名空间的 CRUD 操作，支持多租户数据隔离
"""

import json
import logging
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional

from agentflow.storage import RedisClient


# 默认命名空间（兼容单租户模式）
DEFAULT_NAMESPACE = ""

# 命名空间注册表的 Redis key
NAMESPACE_REGISTRY_KEY = "namespaces"


@dataclass
class NamespaceInfo:
    """命名空间信息"""
    id: str                          # namespace ID（即 project_id）
    name: str                        # 显示名称
    description: str = ""            # 描述（可选）
    created_at: str = ""             # 创建时间
    updated_at: str = ""             # 更新时间

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "NamespaceInfo":
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


class NamespaceManager:
    """
    命名空间管理器

    负责命名空间的注册、查询、删除等操作
    使用 Redis Hash 存储命名空间注册表
    """

    def __init__(self, redis: RedisClient, logger: logging.Logger):
        self._redis = redis
        self._logger = logger
        self._lock = threading.Lock()  # 用于本地缓存一致性

    @classmethod
    async def create(cls, redis: RedisClient, logger: logging.Logger) -> "NamespaceManager":
        """创建命名空间管理器实例"""
        mgr = cls(redis, logger)
        logger.info("命名空间管理器初始化成功")
        return mgr

    async def register(self, id: str, name: str, description: str = "") -> NamespaceInfo:
        """
        注册一个新的命名空间

        Args:
            id: 命名空间 ID（建议使用 proj_xxx 格式）
            name: 显示名称
            description: 描述（可选）

        Returns:
            创建的 NamespaceInfo

        Raises:
            ValueError: 当 ID 为空时
        """
        if not id:
            raise ValueError("namespace ID 不能为空")

        now = datetime.now().isoformat()
        ns = NamespaceInfo(
            id=id,
            name=name,
            description=description,
            created_at=now,
            updated_at=now,
        )

        # 序列化存储
        data = json.dumps(ns.to_dict(), ensure_ascii=False)

        # 存储到注册表（Hash: namespace_id -> json）
        registry_key = self._redis.key(NAMESPACE_REGISTRY_KEY)
        await self._redis.hset(registry_key, {id: data})

        self._logger.info(f"命名空间注册成功 id={id} name={name}")
        return ns

    async def get(self, id: str) -> NamespaceInfo:
        """
        获取命名空间信息

        Args:
            id: 命名空间 ID

        Returns:
            NamespaceInfo

        Raises:
            KeyError: 当命名空间不存在时
        """
        registry_key = self._redis.key(NAMESPACE_REGISTRY_KEY)
        data = await self._redis.hget(registry_key, id)

        if not data:
            raise KeyError(f"namespace {id!r} 不存在")

        ns_dict = json.loads(data)
        return NamespaceInfo.from_dict(ns_dict)

    async def list(self) -> List[NamespaceInfo]:
        """
        列出所有命名空间

        Returns:
            NamespaceInfo 列表
        """
        registry_key = self._redis.key(NAMESPACE_REGISTRY_KEY)
        all_data = await self._redis.hgetall(registry_key)

        result = []
        for ns_id, data in all_data.items():
            try:
                ns_dict = json.loads(data)
                result.append(NamespaceInfo.from_dict(ns_dict))
            except (json.JSONDecodeError, Exception) as e:
                self._logger.warning(f"解析命名空间数据失败 id={ns_id} error={e}")
                continue

        return result

    async def delete(self, id: str) -> None:
        """
        删除命名空间（不删除数据，仅从注册表移除）

        Args:
            id: 命名空间 ID
        """
        registry_key = self._redis.key(NAMESPACE_REGISTRY_KEY)
        await self._redis.hdel(registry_key, id)
        self._logger.info(f"命名空间已从注册表删除 id={id}")

    async def exists(self, id: str) -> bool:
        """
        检查命名空间是否存在

        Args:
            id: 命名空间 ID

        Returns:
            是否存在
        """
        if not id:
            return True  # 默认命名空间始终存在

        try:
            await self.get(id)
            return True
        except KeyError:
            return False

    def client_for(self, namespace: str) -> RedisClient:
        """
        获取指定命名空间的 Redis Client 视图

        注意：Python 版本直接返回原 client，namespace 通过参数传递

        Args:
            namespace: 命名空间 ID

        Returns:
            RedisClient 实例
        """
        # Python 版本直接返回原 client
        # 在调用 key() 方法时传入 namespace
        return self._redis
