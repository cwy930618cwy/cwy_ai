"""Archiver: periodic Redis → SQLite archival."""
import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from agentflow.config import ArchiveConfig
from agentflow.storage import RedisClient, SQLiteStore


class Archiver:
    def __init__(self, redis: RedisClient, sqlite: SQLiteStore,
                 cfg: ArchiveConfig, logger: logging.Logger):
        self._redis = redis
        self._sqlite = sqlite
        self._cfg = cfg
        self._logger = logger
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._archive_loop())
        self._logger.info("Archiver 已启动")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _archive_loop(self) -> None:
        interval = self._cfg.interval_minutes * 60
        while self._running:
            await asyncio.sleep(interval)
            try:
                await self.run_archive_cycle()
            except Exception as e:
                self._logger.error(f"归档周期失败: {e}")

    async def run_archive_cycle(self) -> dict:
        stats = {
            "tasks_archived": 0,
            "experiences_archived": 0,
            "fix_sessions_archived": 0,
        }
        try:
            stats["tasks_archived"] = await self._archive_completed_tasks()
            stats["experiences_archived"] = await self._archive_old_experiences()
            stats["fix_sessions_archived"] = await self._archive_fix_sessions()
            self._logger.info(f"归档完成: {stats}")
        except Exception as e:
            self._logger.error(f"归档异常: {e}")
        return stats

    async def _archive_completed_tasks(self) -> int:
        from agentflow.task.model import TaskStatus
        archive_days = self._cfg.task_archive_days
        threshold_ts = time.time() - archive_days * 86400
        queue_key = self._redis.key("task", "queue", TaskStatus.COMPLETED)
        # Get completed tasks older than threshold
        members = await self._redis.zrangebyscore(queue_key, "-inf", threshold_ts)
        count = 0
        for task_id in members:
            data = await self._redis.hgetall(self._redis.key("task", task_id))
            if not data:
                await self._redis.zrem(queue_key, task_id)
                continue
            try:
                await self._sqlite.archive_task(
                    task_id=task_id,
                    goal_id=data.get("goal_id", ""),
                    data=json.dumps(data),
                    completed_at=data.get("completed_at", ""),
                )
                await self._redis.delete(self._redis.key("task", task_id))
                await self._redis.zrem(queue_key, task_id)
                count += 1
            except Exception as e:
                self._logger.warning(f"归档任务失败 task_id={task_id}: {e}")
        return count

    async def _archive_old_experiences(self) -> int:
        count = 0
        archive_days = self._cfg.metrics_archive_days
        threshold_ts = time.time() - archive_days * 86400
        for stream_suffix in ("positive", "negative"):
            stream_key = self._redis.key("exp", stream_suffix)
            msgs = await self._redis.xrange(stream_key, count=100)
            for msg in msgs:
                try:
                    msg_ts_ms = int(msg["id"].split("-")[0])
                    if msg_ts_ms / 1000 < threshold_ts:
                        fields = msg.get("fields", {})
                        await self._sqlite.archive_experience(
                            exp_id=msg["id"],
                            exp_type=stream_suffix,
                            skill_type=fields.get("skill_type", ""),
                            category=fields.get("category", ""),
                            data=json.dumps(fields),
                            created_at=fields.get("timestamp", ""),
                        )
                        await self._redis.xdel(stream_key, msg["id"])
                        count += 1
                except Exception as e:
                    self._logger.warning(f"归档经验失败 id={msg.get('id', '')}: {e}")
        return count

    async def _archive_fix_sessions(self) -> int:
        from agentflow.fixexp.model import FixStatus
        pattern = self._redis.key("fixexp", "session", "*")
        all_keys = await self._redis.scan_iter(pattern, count=100)
        count = 0
        for key in all_keys:
            if "attempts" in key:
                continue
            data = await self._redis.hgetall(key)
            if not data:
                continue
            status = data.get("status", "")
            if status not in (FixStatus.RESOLVED, FixStatus.ABANDONED):
                continue
            session_id = data.get("id", "")
            if not session_id:
                continue
            attempt_key = self._redis.key("fixexp", "session", session_id, "attempts")
            attempt_items = await self._redis.lrange(attempt_key, 0, -1)
            attempts = []
            for item in attempt_items:
                try:
                    attempts.append(json.loads(item))
                except Exception:
                    pass
            try:
                data["data"] = json.dumps(data)
                await self._sqlite.archive_fix_session(data, attempts)
                await self._redis.delete(key)
                await self._redis.delete(attempt_key)
                count += 1
            except Exception as e:
                self._logger.warning(f"归档FixSession失败 id={session_id}: {e}")
        return count
