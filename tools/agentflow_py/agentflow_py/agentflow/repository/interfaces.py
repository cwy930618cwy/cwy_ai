"""
存储层抽象接口定义

使用 Repository Pattern 解耦业务逻辑与存储实现。
所有存储后端必须实现对应的 Repository 接口。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, TypeVar, Generic


# ==================== 枚举类型 ====================

class Backend(str, Enum):
    """存储后端类型"""
    REDIS = "redis"        # Redis（默认，热数据）
    SQLITE = "sqlite"      # SQLite（冷存储/归档）
    POSTGRES = "postgres"  # PostgreSQL（未来支持）
    MYSQL = "mysql"        # MySQL（未来支持）


# ==================== 通用类型 ====================

T = TypeVar('T')


@dataclass
class PageResult(Generic[T]):
    """分页结果"""
    items: List[T] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


# ==================== Task Repository ====================

@dataclass
class TaskFilter:
    """任务查询过滤条件"""
    goal_id: Optional[str] = None
    parent_task_id: Optional[str] = None
    status: Optional[str] = None
    statuses: List[str] = field(default_factory=list)
    exclude_status: List[str] = field(default_factory=list)
    skill_type: Optional[str] = None
    claimed_by: Optional[str] = None
    min_difficulty: Optional[int] = None
    max_difficulty: Optional[int] = None
    keyword: Optional[str] = None
    group_by: Optional[str] = None
    page: int = 1
    page_size: int = 20
    namespace: Optional[str] = None


@dataclass
class TaskRecord:
    """任务记录（存储层通用表示）"""
    id: str = ""
    goal_id: str = ""
    parent_task_id: str = ""
    title: str = ""
    description: str = ""
    status: str = ""
    progress: float = 0.0
    skill_type: str = ""
    phase: str = ""
    priority: int = 0
    difficulty: int = 0
    claimed_by: str = ""
    tokens_used: int = 0
    retry_count: int = 0
    namespace: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    deadline: Optional[datetime] = None
    # 复杂字段以 JSON 字符串存储
    dependencies_json: str = ""
    prerequisites_json: str = ""
    test_design_json: str = ""
    summary_json: str = ""
    checkpoint_json: str = ""


class TaskRepository(ABC):
    """任务存储接口 - 所有存储后端必须实现此接口"""
    
    @abstractmethod
    async def get(self, task_id: str) -> Optional[TaskRecord]:
        """按 ID 获取任务"""
        pass
    
    @abstractmethod
    async def list(self, filter: TaskFilter) -> PageResult[TaskRecord]:
        """按条件查询任务列表"""
        pass
    
    @abstractmethod
    async def create(self, task: TaskRecord) -> None:
        """创建任务"""
        pass
    
    @abstractmethod
    async def update(self, task_id: str, fields: Dict[str, Any]) -> None:
        """更新任务字段"""
        pass
    
    @abstractmethod
    async def delete(self, task_id: str) -> None:
        """删除任务"""
        pass
    
    @abstractmethod
    async def claim(self, task_id: str, agent_id: str) -> None:
        """原子认领任务（CAS 操作）"""
        pass
    
    @abstractmethod
    async def release(self, task_id: str, agent_id: str) -> None:
        """释放任务（归还到 pending 队列）"""
        pass
    
    @abstractmethod
    async def count_by_status(self, namespace: str) -> Dict[str, int]:
        """按状态统计任务数量"""
        pass
    
    @abstractmethod
    async def health_check(self) -> None:
        """健康检查"""
        pass


# ==================== Goal Repository ====================

@dataclass
class GoalFilter:
    """目标查询过滤条件"""
    status: Optional[str] = None
    statuses: List[str] = field(default_factory=list)
    name: Optional[str] = None
    sort_by: Optional[str] = None
    page: int = 1
    page_size: int = 20
    namespace: Optional[str] = None


@dataclass
class GoalRecord:
    """目标记录"""
    id: str = ""
    title: str = ""
    description: str = ""
    status: str = ""
    priority: int = 0
    progress: float = 0.0
    parent_goal_id: str = ""
    namespace: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    # 复杂字段以 JSON 字符串存储
    phases_json: str = ""
    tags_json: str = ""


class GoalRepository(ABC):
    """目标存储接口"""
    
    @abstractmethod
    async def get(self, goal_id: str) -> Optional[GoalRecord]:
        pass
    
    @abstractmethod
    async def list(self, filter: GoalFilter) -> PageResult[GoalRecord]:
        pass
    
    @abstractmethod
    async def create(self, goal: GoalRecord) -> None:
        pass
    
    @abstractmethod
    async def update(self, goal_id: str, fields: Dict[str, Any]) -> None:
        pass
    
    @abstractmethod
    async def delete(self, goal_id: str) -> None:
        pass
    
    @abstractmethod
    async def health_check(self) -> None:
        pass


# ==================== Skill Repository ====================

@dataclass
class SkillRecord:
    """Skill 记录"""
    name: str = ""
    version: int = 0
    description: str = ""
    skill_type: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    # DNA 以 JSON 字符串存储
    dna_json: str = ""


class SkillRepository(ABC):
    """Skill 存储接口"""
    
    @abstractmethod
    async def get(self, name: str, version: int) -> Optional[SkillRecord]:
        pass
    
    @abstractmethod
    async def list(self) -> List[SkillRecord]:
        pass
    
    @abstractmethod
    async def save(self, skill: SkillRecord) -> None:
        pass
    
    @abstractmethod
    async def delete(self, name: str) -> None:
        pass
    
    @abstractmethod
    async def health_check(self) -> None:
        pass


# ==================== Experience Repository ====================

@dataclass
class ExperienceFilter:
    """经验查询过滤条件"""
    type: Optional[str] = None  # positive / negative
    skill_type: Optional[str] = None
    category: Optional[str] = None
    keyword: Optional[str] = None
    cursor: Optional[str] = None
    batch_size: int = 20


@dataclass
class ExperienceRecord:
    """经验记录"""
    id: str = ""
    type: str = ""
    skill_type: str = ""
    category: str = ""
    description: str = ""
    root_cause: str = ""
    solution: str = ""
    confidence: float = 0.0
    severity: str = ""
    occurrences: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    # 复杂字段以 JSON 字符串存储
    tags_json: str = ""


class ExperienceRepository(ABC):
    """经验存储接口"""
    
    @abstractmethod
    async def get(self, exp_id: str) -> Optional[ExperienceRecord]:
        pass
    
    @abstractmethod
    async def list(self, filter: ExperienceFilter) -> Tuple[List[ExperienceRecord], Optional[str]]:
        """返回 (records, next_cursor)"""
        pass
    
    @abstractmethod
    async def save(self, exp: ExperienceRecord) -> None:
        pass
    
    @abstractmethod
    async def delete(self, ids: List[str], exp_type: str) -> None:
        pass
    
    @abstractmethod
    async def health_check(self) -> None:
        pass


# ==================== Repository Factory ====================

class RepositoryFactory(ABC):
    """存储工厂接口 - 通过工厂统一创建各类 Repository，支持后端切换"""
    
    @property
    @abstractmethod
    def backend(self) -> Backend:
        """返回当前后端类型"""
        pass
    
    @abstractmethod
    def task_repository(self) -> TaskRepository:
        """获取任务存储"""
        pass
    
    @abstractmethod
    def goal_repository(self) -> GoalRepository:
        """获取目标存储"""
        pass
    
    @abstractmethod
    def skill_repository(self) -> SkillRepository:
        """获取 Skill 存储"""
        pass
    
    @abstractmethod
    def experience_repository(self) -> ExperienceRepository:
        """获取经验存储"""
        pass
    
    @abstractmethod
    async def close(self) -> None:
        """关闭所有连接"""
        pass


# ==================== Task Store Provider ====================

class TaskStoreProvider(ABC):
    """Task Store 需要提供的最小接口 - 避免直接依赖 task 模块（防止循环依赖）"""
    
    @abstractmethod
    async def get_raw(self, task_id: str) -> Dict[str, str]:
        """按 ID 获取任务原始数据（dict 格式）"""
        pass
    
    @abstractmethod
    async def count_by_status(self, namespace: str) -> Dict[str, int]:
        """按状态统计任务数量"""
        pass
    
    @abstractmethod
    async def health_check(self) -> None:
        """健康检查"""
        pass
