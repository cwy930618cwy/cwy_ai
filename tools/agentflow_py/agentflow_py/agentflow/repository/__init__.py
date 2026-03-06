"""
Repository 模块 - 存储层抽象接口

设计目标:
- 解耦业务逻辑与存储实现（Redis/SQLite/PostgreSQL/MySQL）
- 通过接口定义统一的 CRUD 契约
- 支持通过配置切换存储后端，无需修改业务代码
- 为未来支持关系数据库奠定基础

使用方式:
    from agentflow.repository import RepositoryFactory, Config
    
    factory = RepositoryFactory.create(config)
    task_repo = factory.task_repository()
    tasks = await task_repo.list(filter)
"""

from .interfaces import (
    Backend,
    PageResult,
    TaskFilter,
    TaskRecord,
    TaskRepository,
    GoalFilter,
    GoalRecord,
    GoalRepository,
    SkillRecord,
    SkillRepository,
    ExperienceFilter,
    ExperienceRecord,
    ExperienceRepository,
    RepositoryFactory,
    TaskStoreProvider,
)
from .factory import Config, default_config, new_repository_factory, RedisRepositoryFactory
from .redis_adapter import RedisTaskRepositoryAdapter

__all__ = [
    # 枚举类型
    "Backend",
    # 通用类型
    "PageResult",
    # Task 相关
    "TaskFilter",
    "TaskRecord",
    "TaskRepository",
    "TaskStoreProvider",
    # Goal 相关
    "GoalFilter",
    "GoalRecord",
    "GoalRepository",
    # Skill 相关
    "SkillRecord",
    "SkillRepository",
    # Experience 相关
    "ExperienceFilter",
    "ExperienceRecord",
    "ExperienceRepository",
    # 工厂
    "RepositoryFactory",
    "Config",
    "default_config",
    "new_repository_factory",
    # Redis 实现
    "RedisTaskRepositoryAdapter",
    "RedisRepositoryFactory",
]
