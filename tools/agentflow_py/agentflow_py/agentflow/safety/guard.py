"""Safety Guard: 6-dimensional health check."""
import logging
from typing import Any, Dict, List, Optional

from agentflow.config import SafetyConfig
from agentflow.storage import RedisClient, SQLiteStore


class SafetyGuard:
    def __init__(self, redis: RedisClient, sqlite: Optional[SQLiteStore],
                 cfg: SafetyConfig, logger: logging.Logger):
        self._redis = redis
        self._sqlite = sqlite
        self._cfg = cfg
        self._logger = logger

    async def get_health_report(self) -> Dict:
        checks = {}
        issues = []

        # 1. Redis health
        try:
            await self._redis.health_check()
            checks["redis"] = {"status": "ok"}
        except Exception as e:
            checks["redis"] = {"status": "error", "detail": str(e)}
            issues.append(f"Redis连接异常: {e}")

        # 2. SQLite health
        if self._sqlite:
            try:
                await self._sqlite.health_check()
                checks["sqlite"] = {"status": "ok"}
            except Exception as e:
                checks["sqlite"] = {"status": "error", "detail": str(e)}
                issues.append(f"SQLite连接异常: {e}")

        # 3. Task queue health
        task_checks = await self._check_task_queues()
        checks["task_queues"] = task_checks
        if task_checks.get("interrupted_tasks", 0) > 5:
            issues.append(f"中断任务过多: {task_checks['interrupted_tasks']}")

        # 4. Skill DNA health
        skill_checks = await self._check_skill_health()
        checks["skills"] = skill_checks
        if skill_checks.get("degraded_skills"):
            issues.append(f"技能退化: {skill_checks['degraded_skills']}")

        # 5. Evolution system
        evo_checks = await self._check_evolution()
        checks["evolution"] = evo_checks

        # 6. Memory usage
        mem_usage = await self._redis.memory_usage()
        checks["redis_memory"] = {"db_size": mem_usage}

        overall_status = "healthy" if not issues else "degraded" if len(issues) <= 2 else "critical"

        return {
            "overall_status": overall_status,
            "issues": issues,
            "checks": checks,
        }

    async def _check_task_queues(self) -> Dict:
        from agentflow.task.model import TaskStatus
        result = {}
        for status in TaskStatus.ALL:
            count = await self._redis.zcard(self._redis.key("task", "queue", status))
            result[f"{status}_tasks"] = count
        return result

    async def _check_skill_health(self) -> Dict:
        skill_types = await self._redis.smembers(self._redis.key("skill", "types"))
        degraded = []
        for st in skill_types:
            metrics = await self._redis.hgetall(self._redis.key("skill", st, "metrics"))
            total = int(metrics.get("total_tasks", 0))
            success = int(metrics.get("completed_tasks", 0))
            if total >= 5 and success / total < 0.5:
                degraded.append(st)
        return {
            "total_skills": len(skill_types),
            "degraded_skills": degraded,
        }

    async def _check_evolution(self) -> Dict:
        pending = await self._redis.llen(self._redis.key("evo", "pending_approvals"))
        log_len = await self._redis.xlen(self._redis.key("evo", "log"))
        return {
            "pending_approvals": pending,
            "evolution_log_size": log_len,
        }
