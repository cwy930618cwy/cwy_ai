"""
Redis 后端适配器

将现有 task.Store 包装为 TaskRepository 接口实现。
采用适配器模式（Adapter Pattern），无需修改现有业务代码。
"""

from datetime import datetime
from typing import Any, Dict, Optional

from .interfaces import (
    PageResult,
    TaskFilter,
    TaskRecord,
    TaskRepository,
    TaskStoreProvider,
)


# ==================== Redis Task Repository 适配器 ====================

class RedisTaskRepositoryAdapter(TaskRepository):
    """将 TaskStoreProvider 适配为 TaskRepository 接口"""
    
    def __init__(self, store: TaskStoreProvider):
        self._store = store
    
    async def get(self, task_id: str) -> Optional[TaskRecord]:
        """按 ID 获取任务"""
        try:
            raw = await self._store.get_raw(task_id)
        except Exception as e:
            raise RuntimeError(f"获取任务失败 [{task_id}]: {e}") from e
        
        if not raw:
            return None
        return self._map_to_task_record(raw)
    
    async def list(self, filter: TaskFilter) -> PageResult[TaskRecord]:
        """按条件查询任务列表
        
        注意：当前 Redis 实现需要在 TaskStoreProvider 中添加 list_raw 方法
        """
        # TODO: 调用 task.Store.list_raw 获取原始数据
        # 当前返回空结果，完整实现需要 TaskStoreProvider 暴露 list_raw 方法
        return PageResult(
            items=[],
            total=0,
            page=filter.page,
            page_size=filter.page_size,
        )
    
    async def create(self, task: TaskRecord) -> None:
        """创建任务（委托给 task.Store）"""
        # TODO: 调用 task.Store.create_raw
        raise NotImplementedError("create 需要通过 task.Store 实现，请直接使用 task.Store.create_batch")
    
    async def update(self, task_id: str, fields: Dict[str, Any]) -> None:
        """更新任务字段"""
        # TODO: 调用 task.Store.update_raw
        raise NotImplementedError("update 需要通过 task.Store 实现，请直接使用 task.Store.update")
    
    async def delete(self, task_id: str) -> None:
        """删除任务"""
        # TODO: 调用 task.Store.delete_raw
        raise NotImplementedError("delete 需要通过 task.Store 实现，请直接使用 task.Store.delete")
    
    async def claim(self, task_id: str, agent_id: str) -> None:
        """原子认领任务"""
        raise NotImplementedError("claim 需要通过 task.Store 实现，请直接使用 task.Store.claim")
    
    async def release(self, task_id: str, agent_id: str) -> None:
        """释放任务"""
        raise NotImplementedError("release 需要通过 task.Store 实现，请直接使用 task.Store.release")
    
    async def count_by_status(self, namespace: str) -> Dict[str, int]:
        """按状态统计任务数量"""
        return await self._store.count_by_status(namespace)
    
    async def health_check(self) -> None:
        """健康检查"""
        await self._store.health_check()
    
    # ==================== 辅助方法 ====================
    
    @staticmethod
    def _map_to_task_record(raw: Dict[str, str]) -> TaskRecord:
        """将 Redis Hash 数据转换为 TaskRecord"""
        rec = TaskRecord()
        
        # 字符串字段
        if raw.get("id"):
            rec.id = raw["id"]
        if raw.get("goal_id"):
            rec.goal_id = raw["goal_id"]
        if raw.get("parent_task_id"):
            rec.parent_task_id = raw["parent_task_id"]
        if raw.get("title"):
            rec.title = raw["title"]
        if raw.get("description"):
            rec.description = raw["description"]
        if raw.get("status"):
            rec.status = raw["status"]
        if raw.get("skill_type"):
            rec.skill_type = raw["skill_type"]
        if raw.get("phase"):
            rec.phase = raw["phase"]
        if raw.get("claimed_by"):
            rec.claimed_by = raw["claimed_by"]
        if raw.get("namespace"):
            rec.namespace = raw["namespace"]
        
        # JSON 字段
        if raw.get("dependencies"):
            rec.dependencies_json = raw["dependencies"]
        if raw.get("prerequisites"):
            rec.prerequisites_json = raw["prerequisites"]
        if raw.get("test_design"):
            rec.test_design_json = raw["test_design"]
        if raw.get("summary"):
            rec.summary_json = raw["summary"]
        if raw.get("checkpoint"):
            rec.checkpoint_json = raw["checkpoint"]
        
        # 数值字段
        if raw.get("progress"):
            try:
                rec.progress = float(raw["progress"])
            except ValueError:
                pass
        if raw.get("priority"):
            try:
                rec.priority = int(raw["priority"])
            except ValueError:
                pass
        if raw.get("difficulty"):
            try:
                rec.difficulty = int(raw["difficulty"])
            except ValueError:
                pass
        if raw.get("tokens_used"):
            try:
                rec.tokens_used = int(raw["tokens_used"])
            except ValueError:
                pass
        if raw.get("retry_count"):
            try:
                rec.retry_count = int(raw["retry_count"])
            except ValueError:
                pass
        
        # 时间字段
        if raw.get("created_at"):
            try:
                rec.created_at = datetime.fromisoformat(raw["created_at"])
            except ValueError:
                pass
        if raw.get("updated_at"):
            try:
                rec.updated_at = datetime.fromisoformat(raw["updated_at"])
            except ValueError:
                pass
        if raw.get("completed_at"):
            try:
                rec.completed_at = datetime.fromisoformat(raw["completed_at"])
            except ValueError:
                pass
        if raw.get("deadline"):
            try:
                rec.deadline = datetime.fromisoformat(raw["deadline"])
            except ValueError:
                pass
        
        return rec
