"""数据导出器实现。

提供 AgentFlow 数据导出功能，支持：
- Skills（含 DNA 和 Metrics）
- Experiences（正/负经验）
- GlobalRules（全局规则）
- Goals（目标）
- Tasks（任务）

支持全量和增量导出（通过 since 参数）。
"""
import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

from agentflow.storage import RedisClient
from agentflow.skill import SkillStore
from agentflow.goal import GoalStore
from agentflow.task import TaskStore
from .model import (
    ExportPackage, ExportParams, ExportScope, ExportStats,
    SkillExport, ExpExport,
)


EXPORT_VERSION = "1.0"


class Exporter:
    """数据导出器。

    负责将 AgentFlow 数据导出为可移植的 JSON 格式。
    支持范围过滤和增量导出。
    """

    def __init__(
        self,
        redis: RedisClient,
        skill_store: SkillStore,
        goal_store: GoalStore,
        task_store: TaskStore,
        logger: logging.Logger,
    ):
        self._redis = redis
        self._skill_store = skill_store
        self._goal_store = goal_store
        self._task_store = task_store
        self._logger = logger

    async def export(self, params: ExportParams) -> ExportPackage:
        """执行数据导出。

        Args:
            params: 导出参数，包含范围、格式和增量时间戳。

        Returns:
            ExportPackage: 导出数据包。

        Raises:
            Exception: 导出过程中发生的错误。
        """
        pkg = ExportPackage(
            version=EXPORT_VERSION,
            exported_at=datetime.now(timezone.utc).isoformat(),
            scope=params.scope,
            stats=ExportStats(),
        )

        # 导出 Skills
        if params.scope.skills:
            skills = await self._export_skills()
            pkg.skills = skills
            pkg.stats.skill_count = len(skills)

        # 导出 Experiences
        if params.scope.experiences:
            exps = await self._export_experiences(params.since)
            pkg.experiences = exps
            pkg.stats.positive_exp_count = len(exps.positive)
            pkg.stats.negative_exp_count = len(exps.negative)

        # 导出 GlobalRules
        if params.scope.global_rules:
            rules = await self._export_global_rules()
            pkg.global_rules = rules
            pkg.stats.global_rule_count = len(rules)

        # 导出 Goals
        if params.scope.goals:
            goals = await self._export_goals()
            pkg.goals = goals
            pkg.stats.goal_count = len(goals)

        # 导出 Tasks
        if params.scope.tasks:
            tasks = await self._export_tasks()
            pkg.tasks = tasks
            pkg.stats.task_count = len(tasks)

        self._logger.info(
            f"数据导出完成: skills={pkg.stats.skill_count}, "
            f"pos_exp={pkg.stats.positive_exp_count}, "
            f"neg_exp={pkg.stats.negative_exp_count}, "
            f"global_rules={pkg.stats.global_rule_count}, "
            f"goals={pkg.stats.goal_count}, "
            f"tasks={pkg.stats.task_count}"
        )
        return pkg

    async def _export_skills(self) -> List[SkillExport]:
        """导出所有 Skill（含 DNA 和 Metrics）。"""
        skills = await self._skill_store.list_skills()
        result = []
        for skill in skills:
            result.append(SkillExport(
                skill=skill.to_dict(),
                metrics=skill.metrics.to_dict() if skill.metrics else None,
            ))
        return result

    async def _export_experiences(self, since: str) -> ExpExport:
        """导出经验（支持增量导出）。

        Args:
            since: RFC3339 格式的时间戳，只导出此时间之后的数据。
                   为空则全量导出。

        Returns:
            ExpExport: 包含正/负经验列表。
        """
        exp = ExpExport()

        # 确定起始 Stream ID
        start_id = "-"
        if since:
            try:
                t = datetime.fromisoformat(since.replace("Z", "+00:00"))
                # Redis Stream ID 格式: <毫秒时间戳>-0
                start_id = f"{int(t.timestamp() * 1000)}-0"
            except Exception as e:
                self._logger.warning(f"解析 since 参数失败: {e}")

        # 导出正经验
        pos_entries = await self._redis.xrange(
            self._redis.key("exp", "positive"),
            min_id=start_id,
            max_id="+",
        )
        for entry in pos_entries:
            row = {"_id": entry["id"]}
            for k, v in entry["fields"].items():
                row[k] = v
            exp.positive.append(row)

        # 导出负经验
        neg_entries = await self._redis.xrange(
            self._redis.key("exp", "negative"),
            min_id=start_id,
            max_id="+",
        )
        for entry in neg_entries:
            row = {"_id": entry["id"]}
            for k, v in entry["fields"].items():
                row[k] = v
            exp.negative.append(row)

        return exp

    async def _export_global_rules(self) -> List[str]:
        """导出全局规则。"""
        return await self._redis.lrange(
            self._redis.key("ctx", "global_rules"), 0, -1
        )

    async def _export_goals(self) -> List[dict]:
        """导出所有 Goal。"""
        # 从有序集合获取所有 Goal ID
        members = await self._redis.zrevrange_withscores(
            self._redis.key("goal", "list"), 0, -1
        )
        goals = []
        for goal_id, _ in members:
            try:
                goal = await self._goal_store.get(goal_id)
                goals.append(goal.to_dict())
            except Exception as e:
                self._logger.warning(f"导出 Goal 失败，跳过: id={goal_id} error={e}")
        return goals

    async def _export_tasks(self) -> List[dict]:
        """导出所有 Task（从各状态队列读取）。"""
        task_ids = set()

        # 扫描所有状态队列
        queues = ["pending", "running", "completed", "failed", "blocked", "interrupted", "review"]
        for q in queues:
            members = await self._redis.zrangebyscore(
                self._redis.key("task", "queue", q), "-inf", "+inf"
            )
            task_ids.update(members)

        tasks = []
        for task_id in task_ids:
            try:
                task = await self._task_store.get(task_id)
                tasks.append(task.to_dict())
            except Exception as e:
                self._logger.warning(f"导出 Task 失败，跳过: id={task_id} error={e}")
        return tasks
