import json
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from agentflow.common import generate_goal_id, NotFoundError, InvalidParamError
from agentflow.storage import RedisClient
from .model import Goal, GoalStatus


class GoalStore:
    def __init__(self, redis: RedisClient, logger: logging.Logger):
        self._redis = redis
        self._logger = logger

    async def create(self, title: str, description: str, priority: int = 5,
                     phases: Optional[List[str]] = None, parent_goal_id: str = "",
                     tags: Optional[List[str]] = None) -> Goal:
        if not title:
            raise InvalidParamError("title 不能为空")
        if priority < 1 or priority > 10:
            priority = 5

        now = datetime.now(timezone.utc).isoformat()
        goal = Goal(
            id=generate_goal_id(),
            title=title,
            description=description,
            status=GoalStatus.PENDING,
            priority=priority,
            parent_goal_id=parent_goal_id or "",
            phases=phases or [],
            tags=tags or [],
            progress=0.0,
            created_at=now,
            updated_at=now,
        )

        key = self._redis.key("goal", goal.id)
        mapping = {
            "id": goal.id,
            "title": goal.title,
            "description": goal.description,
            "status": goal.status,
            "priority": str(goal.priority),
            "parent_goal_id": goal.parent_goal_id,
            "tags": json.dumps(goal.tags),
            "progress": f"{goal.progress:.1f}",
            "created_at": goal.created_at,
            "updated_at": goal.updated_at,
        }
        await self._redis.hset(key, mapping)
        await self._redis.zadd(self._redis.key("goal", "list"), {goal.id: float(priority)})

        if phases:
            phase_key = self._redis.key("goal", goal.id, "phases")
            for p in phases:
                await self._redis.rpush(phase_key, p)

        if parent_goal_id:
            await self._redis.rpush(self._redis.key("goal", parent_goal_id, "subtasks"), goal.id)

        self._logger.info(f"目标已创建 id={goal.id} title={goal.title}")
        return goal

    async def get(self, goal_id: str) -> Goal:
        key = self._redis.key("goal", goal_id)
        data = await self._redis.hgetall(key)
        if not data:
            raise NotFoundError(f"goal {goal_id}")
        goal = self._map_to_goal(data)
        phases = await self._redis.lrange(self._redis.key("goal", goal_id, "phases"), 0, -1)
        goal.phases = phases
        return goal

    async def update(self, goal_id: str, fields: Dict) -> Goal:
        key = self._redis.key("goal", goal_id)
        exists = await self._redis.exists(key)
        if not exists:
            raise NotFoundError(f"goal {goal_id}")

        updates = {}
        allowed = {"title", "description", "status", "priority", "progress"}
        for k, v in fields.items():
            if k in allowed:
                updates[k] = str(v)
                if k == "priority":
                    await self._redis.zadd(
                        self._redis.key("goal", "list"),
                        {goal_id: float(v)},
                    )
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self._redis.hset(key, updates)
        return await self.get(goal_id)

    async def delete(self, goal_id: str, cascade: bool = False) -> None:
        key = self._redis.key("goal", goal_id)
        exists = await self._redis.exists(key)
        if not exists:
            raise NotFoundError(f"goal {goal_id}")

        await self._redis.delete(key)
        await self._redis.delete(self._redis.key("goal", goal_id, "phases"))
        await self._redis.zrem(self._redis.key("goal", "list"), goal_id)

        if cascade:
            subtask_ids = await self._redis.lrange(
                self._redis.key("goal", goal_id, "subtasks"), 0, -1
            )
            for sid in subtask_ids:
                await self._redis.delete(self._redis.key("goal", sid))
                await self._redis.zrem(self._redis.key("goal", "list"), sid)

        await self._redis.delete(self._redis.key("goal", goal_id, "subtasks"))
        self._logger.info(f"目标已删除 id={goal_id} cascade={cascade}")

    async def list(self, status: str = "", statuses: Optional[List[str]] = None,
                   name: str = "", page: int = 1, page_size: int = 20) -> Tuple[List[Goal], int]:
        if page < 1:
            page = 1
        if page_size < 1 or page_size > 100:
            page_size = 20

        list_key = self._redis.key("goal", "list")
        status_filter = set()
        if statuses:
            status_filter = set(statuses)
        elif status:
            status_filter = {status}

        if status_filter or name:
            members = await self._redis.zrevrange_withscores(list_key, 0, -1)
        else:
            start = (page - 1) * page_size
            stop = start + page_size - 1
            members = await self._redis.zrevrange_withscores(list_key, start, stop)

        total = await self._redis.zcard(list_key)
        all_filtered = []
        for gid, _ in members:
            try:
                goal = await self.get(gid)
            except Exception:
                continue
            if status_filter and goal.status not in status_filter:
                continue
            if name and name.lower() not in goal.title.lower():
                continue
            all_filtered.append(goal)

        filtered_total = len(all_filtered)
        if status_filter or name:
            start = (page - 1) * page_size
            end = start + page_size
            return all_filtered[start:end], filtered_total

        return all_filtered, total

    async def update_progress(self, goal_id: str, progress: float) -> None:
        key = self._redis.key("goal", goal_id)
        await self._redis.hset(key, {
            "progress": f"{progress:.1f}",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })

    def _map_to_goal(self, data: Dict) -> Goal:
        tags = []
        if data.get("tags"):
            try:
                tags = json.loads(data["tags"])
            except Exception:
                pass
        return Goal(
            id=data.get("id", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            status=data.get("status", GoalStatus.PENDING),
            priority=int(data.get("priority", 5)),
            parent_goal_id=data.get("parent_goal_id", ""),
            tags=tags,
            progress=float(data.get("progress", 0)),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )
