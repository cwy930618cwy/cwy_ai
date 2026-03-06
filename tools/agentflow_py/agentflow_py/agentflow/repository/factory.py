"""
存储工厂实现

通过配置选择存储后端，支持 Redis（默认）和未来的 PostgreSQL/MySQL。
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

from .interfaces import (
    Backend,
    GoalRepository,
    GoalRecord,
    GoalFilter,
    PageResult,
    SkillRepository,
    SkillRecord,
    ExperienceRepository,
    ExperienceRecord,
    ExperienceFilter,
    RepositoryFactory,
    TaskRepository,
    TaskStoreProvider,
)


# ==================== 工厂配置 ====================

@dataclass
class Config:
    """存储工厂配置"""
    backend: Backend = Backend.REDIS
    redis_enabled: bool = True
    postgres_dsn: Optional[str] = None
    mysql_dsn: Optional[str] = None


def default_config() -> Config:
    """返回默认配置（Redis 后端）"""
    return Config(
        backend=Backend.REDIS,
        redis_enabled=True,
    )


# ==================== Noop 实现（占位） ====================

class NoopGoalRepository(GoalRepository):
    """GoalRepository 占位实现"""
    
    async def get(self, goal_id: str):
        raise NotImplementedError("GoalRepository 尚未完整实现，请直接使用 goal.Store")
    
    async def list(self, filter: GoalFilter) -> PageResult[GoalRecord]:
        raise NotImplementedError("GoalRepository 尚未完整实现，请直接使用 goal.Store")
    
    async def create(self, goal: GoalRecord) -> None:
        raise NotImplementedError("GoalRepository 尚未完整实现，请直接使用 goal.Store")
    
    async def update(self, goal_id: str, fields: dict) -> None:
        raise NotImplementedError("GoalRepository 尚未完整实现，请直接使用 goal.Store")
    
    async def delete(self, goal_id: str) -> None:
        raise NotImplementedError("GoalRepository 尚未完整实现，请直接使用 goal.Store")
    
    async def health_check(self) -> None:
        pass


class NoopSkillRepository(SkillRepository):
    """SkillRepository 占位实现"""
    
    async def get(self, name: str, version: int):
        raise NotImplementedError("SkillRepository 尚未完整实现，请直接使用 skill.Store")
    
    async def list(self):
        raise NotImplementedError("SkillRepository 尚未完整实现，请直接使用 skill.Store")
    
    async def save(self, skill: SkillRecord) -> None:
        raise NotImplementedError("SkillRepository 尚未完整实现，请直接使用 skill.Store")
    
    async def delete(self, name: str) -> None:
        raise NotImplementedError("SkillRepository 尚未完整实现，请直接使用 skill.Store")
    
    async def health_check(self) -> None:
        pass


class NoopExperienceRepository(ExperienceRepository):
    """ExperienceRepository 占位实现"""
    
    async def get(self, exp_id: str):
        raise NotImplementedError("ExperienceRepository 尚未完整实现，请直接使用 fixexp.Store")
    
    async def list(self, filter: ExperienceFilter):
        raise NotImplementedError("ExperienceRepository 尚未完整实现，请直接使用 fixexp.Store")
    
    async def save(self, exp: ExperienceRecord) -> None:
        raise NotImplementedError("ExperienceRepository 尚未完整实现，请直接使用 fixexp.Store")
    
    async def delete(self, ids: list, exp_type: str) -> None:
        raise NotImplementedError("ExperienceRepository 尚未完整实现，请直接使用 fixexp.Store")
    
    async def health_check(self) -> None:
        pass


# ==================== Redis 工厂实现 ====================

class RedisRepositoryFactory(RepositoryFactory):
    """Redis 后端工厂 - 包装现有各模块的 Store，提供统一的 Repository 接口"""
    
    def __init__(self, cfg: Config, task_store: Optional[TaskStoreProvider] = None):
        self._cfg = cfg
        self._task_store = task_store
        self._noop_goal = NoopGoalRepository()
        self._noop_skill = NoopSkillRepository()
        self._noop_experience = NoopExperienceRepository()
    
    @property
    def backend(self) -> Backend:
        return Backend.REDIS
    
    def task_repository(self) -> TaskRepository:
        if self._task_store is None:
            raise RuntimeError("TaskStore 未注入，请在创建工厂时提供 task_store 参数")
        from .redis_adapter import RedisTaskRepositoryAdapter
        return RedisTaskRepositoryAdapter(self._task_store)
    
    def goal_repository(self) -> GoalRepository:
        return self._noop_goal
    
    def skill_repository(self) -> SkillRepository:
        return self._noop_skill
    
    def experience_repository(self) -> ExperienceRepository:
        return self._noop_experience
    
    async def close(self) -> None:
        """Redis 连接由外部管理，此处无需关闭"""
        pass


# ==================== 工厂注册表 ====================

# 工厂构造函数类型
FactoryConstructor = Callable[[Config, Optional[TaskStoreProvider]], RepositoryFactory]

# 已注册的工厂
_registered_factories: Dict[Backend, FactoryConstructor] = {}


def _register_default_factories():
    """注册默认工厂"""
    _registered_factories[Backend.REDIS] = lambda cfg, task_store=None: RedisRepositoryFactory(cfg, task_store)


# 模块加载时注册默认工厂
_register_default_factories()


def new_repository_factory(
    cfg: Config,
    task_store: Optional[TaskStoreProvider] = None
) -> RepositoryFactory:
    """根据配置创建对应的存储工厂
    
    Args:
        cfg: 存储配置
        task_store: Task Store 实例（可选）
    
    Returns:
        RepositoryFactory 实例
    
    Raises:
        ValueError: 不支持的存储后端
    """
    constructor = _registered_factories.get(cfg.backend)
    if constructor is None:
        supported = ", ".join([b.value for b in _registered_factories.keys()])
        raise ValueError(f"不支持的存储后端: {cfg.backend.value}（支持: {supported}）")
    return constructor(cfg, task_store)


def register_backend(backend: Backend, constructor: FactoryConstructor) -> None:
    """注册新的存储后端（扩展点）
    
    第三方可通过此函数注册 PostgreSQL/MySQL 等后端实现。
    
    Args:
        backend: 后端类型
        constructor: 工厂构造函数
    """
    _registered_factories[backend] = constructor
