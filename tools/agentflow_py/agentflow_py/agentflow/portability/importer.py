"""数据导入器实现。

提供 AgentFlow 数据导入功能，支持：
- Skills（含 DNA 和 Metrics）
- Experiences（正/负经验）
- GlobalRules（全局规则）
- Goals（目标）
- Tasks（任务）

支持三种冲突策略：
- skip: 跳过已存在的数据
- overwrite: 覆盖已存在的数据
- merge: 合并（仅对 Skill DNA 有效，追加规则/反模式/最佳实践）
"""
import json
import logging
from datetime import datetime, timezone
from typing import List, Tuple

from agentflow.storage import RedisClient
from agentflow.skill import SkillStore, SkillDNA
from .model import (
    ExportPackage, ExportScope, ImportParams, ImportResult,
    SkillExport,
)


class Importer:
    """数据导入器。

    负责从 JSON 格式的导出包中导入 AgentFlow 数据。
    支持冲突策略和范围过滤。
    """

    def __init__(
        self,
        redis: RedisClient,
        skill_store: SkillStore,
        goal_store,  # GoalStore
        logger: logging.Logger,
    ):
        self._redis = redis
        self._skill_store = skill_store
        self._goal_store = goal_store
        self._logger = logger

    async def import_data(
        self,
        pkg: ExportPackage,
        params: ImportParams
    ) -> ImportResult:
        """执行数据导入。

        Args:
            pkg: 导出数据包。
            params: 导入参数，包含冲突策略和范围过滤。

        Returns:
            ImportResult: 导入结果统计。
        """
        result = ImportResult()

        # 确定导入范围
        scope = pkg.scope or ExportScope()
        if params.scope:
            scope = params.scope

        # 导入 GlobalRules
        if scope.global_rules and pkg.global_rules:
            n, err = await self._import_global_rules(
                pkg.global_rules, params.conflict_policy
            )
            if err:
                result.errors.append(f"导入 GlobalRules 失败: {err}")
            else:
                result.global_rules_imported = n

        # 导入 Skills
        if scope.skills and pkg.skills:
            imported, skipped, errs = await self._import_skills(
                pkg.skills, params.conflict_policy
            )
            result.skills_imported = imported
            result.skills_skipped = skipped
            result.errors.extend(errs)

        # 导入 Experiences
        if scope.experiences and pkg.experiences:
            pos_n, neg_n, errs = await self._import_experiences(pkg.experiences)
            result.positive_exp_imported = pos_n
            result.negative_exp_imported = neg_n
            result.errors.extend(errs)

        # 导入 Goals
        if scope.goals and pkg.goals:
            n, errs = await self._import_goals(pkg.goals, params.conflict_policy)
            result.goals_imported = n
            result.errors.extend(errs)

        # 导入 Tasks
        if scope.tasks and pkg.tasks:
            n, errs = await self._import_tasks(pkg.tasks, params.conflict_policy)
            result.tasks_imported = n
            result.errors.extend(errs)

        self._logger.info(
            f"数据导入完成: skills={result.skills_imported}, "
            f"skills_skipped={result.skills_skipped}, "
            f"pos_exp={result.positive_exp_imported}, "
            f"neg_exp={result.negative_exp_imported}, "
            f"global_rules={result.global_rules_imported}, "
            f"goals={result.goals_imported}, "
            f"tasks={result.tasks_imported}, "
            f"errors={len(result.errors)}"
        )
        return result

    async def _import_global_rules(
        self,
        rules: List[str],
        policy: str
    ) -> Tuple[int, str]:
        """导入全局规则。

        Args:
            rules: 规则列表。
            policy: 冲突策略。

        Returns:
            (导入数量, 错误信息)
        """
        rules_key = self._redis.key("ctx", "global_rules")

        if policy == "overwrite":
            # 覆盖：先清空再写入
            await self._redis.delete(rules_key)

        # 获取现有规则（用于去重）
        existing = await self._redis.lrange(rules_key, 0, -1)
        existing_set = set(existing)

        count = 0
        for rule in rules:
            if policy == "skip" and rule in existing_set:
                continue
            if rule not in existing_set:
                await self._redis.rpush(rules_key, rule)
                count += 1

        return count, ""

    async def _import_skills(
        self,
        skills: List[SkillExport],
        policy: str
    ) -> Tuple[int, int, List[str]]:
        """导入 Skills。

        Args:
            skills: Skill 导出数据列表。
            policy: 冲突策略 (skip/overwrite/merge)。

        Returns:
            (导入数量, 跳过数量, 错误列表)
        """
        imported, skipped = 0, 0
        errs = []

        for se in skills:
            if not se.skill:
                continue
            skill_name = se.skill.get("name") or se.skill.get("skill_type", "")
            if not skill_name:
                continue

            # 检查是否已存在
            existing = await self._skill_store.get_skill(skill_name)

            if existing:
                if policy == "skip":
                    skipped += 1
                    continue
                elif policy == "merge":
                    # merge：合并 DNA（追加规则/反模式/最佳实践）
                    if se.skill.get("dna"):
                        try:
                            await self._merge_skill_dna(skill_name, se.skill["dna"])
                            imported += 1
                        except Exception as e:
                            errs.append(f"merge Skill {skill_name} 失败: {e}")
                        continue
                elif policy == "overwrite":
                    # overwrite：删除后重建
                    await self._delete_skill(skill_name)

            # 创建 Skill
            try:
                await self._create_skill(se.skill, se.metrics)
                imported += 1
            except Exception as e:
                errs.append(f"创建 Skill {skill_name} 失败: {e}")

        return imported, skipped, errs

    async def _merge_skill_dna(self, skill_name: str, dna_data: dict) -> None:
        """合并 Skill DNA（追加规则/反模式/最佳实践）。"""
        existing = await self._skill_store.get_skill(skill_name)
        if not existing or not existing.dna:
            return

        updates = {}
        if dna_data.get("rules"):
            existing_rules = set(existing.dna.rules)
            new_rules = [r for r in dna_data["rules"] if r not in existing_rules]
            if new_rules:
                updates["rules"] = existing.dna.rules + new_rules

        if dna_data.get("anti_patterns"):
            existing_anti = set(existing.dna.anti_patterns)
            new_anti = [a for a in dna_data["anti_patterns"] if a not in existing_anti]
            if new_anti:
                updates["anti_patterns"] = existing.dna.anti_patterns + new_anti

        if dna_data.get("best_practices"):
            existing_bp = set(existing.dna.best_practices)
            new_bp = [b for b in dna_data["best_practices"] if b not in existing_bp]
            if new_bp:
                updates["best_practices"] = existing.dna.best_practices + new_bp

        if updates:
            await self._skill_store.update_dna_fields(skill_name, updates)

    async def _delete_skill(self, skill_name: str) -> None:
        """删除 Skill 相关所有 key。"""
        await self._redis.delete(
            self._redis.key("skill", skill_name),
            self._redis.key("skill", skill_name, "dna"),
            self._redis.key("skill", skill_name, "metrics"),
            self._redis.key("skill", skill_name, "meta"),
        )
        await self._redis.srem(self._redis.key("skill", "types"), skill_name)

    async def _create_skill(self, skill_data: dict, metrics_data: dict = None) -> None:
        """创建 Skill。"""
        skill_type = skill_data.get("skill_type") or skill_data.get("name", "")
        if not skill_type:
            raise ValueError("skill_type 不能为空")

        # 创建 DNA
        dna_data = skill_data.get("dna") or {}
        dna = SkillDNA(
            skill_type=skill_type,
            rules=dna_data.get("rules", []),
            templates=dna_data.get("templates", []),
            checklist=dna_data.get("checklist", []),
            anti_patterns=dna_data.get("anti_patterns", []),
            best_practices=dna_data.get("best_practices", []),
            context_hints=dna_data.get("context_hints", []),
            version=dna_data.get("version", 1),
        )
        await self._skill_store.save_dna(dna)

        # 保存 meta 信息
        meta_key = self._redis.key("skill", skill_type, "meta")
        now = datetime.now(timezone.utc).isoformat()
        await self._redis.hset(meta_key, {
            "name": skill_data.get("name", skill_type),
            "description": skill_data.get("description", ""),
            "version": str(skill_data.get("version", 1)),
            "updated_at": now,
        })

    async def _import_experiences(
        self,
        exps
    ) -> Tuple[int, int, List[str]]:
        """导入经验（追加到 Stream，支持幂等性保护）。"""
        pos_n, neg_n = 0, 0
        errs = []

        now = datetime.now(timezone.utc).isoformat()

        # 幂等性保护：维护已导入经验 ID 的 Redis Set
        imported_ids_key = self._redis.key("portability", "imported_exp_ids")
        already_imported = await self._redis.smembers(imported_ids_key)

        # 导入正经验
        for row in exps.positive:
            exp_id = row.get("id") or row.get("_id", "")
            # skip 策略下：有 ID 且已导入则跳过
            if exp_id and exp_id in already_imported:
                continue
            fields = {}
            for k, v in row.items():
                if k == "_id":
                    continue
                fields[k] = v
            fields["imported_at"] = now
            try:
                await self._redis.xadd(
                    self._redis.key("exp", "positive"),
                    fields
                )
                if exp_id:
                    await self._redis.sadd(imported_ids_key, exp_id)
                pos_n += 1
            except Exception as e:
                errs.append(f"导入正经验失败: {e}")

        # 导入负经验
        for row in exps.negative:
            exp_id = row.get("id") or row.get("_id", "")
            # skip 策略下：有 ID 且已导入则跳过
            if exp_id and exp_id in already_imported:
                continue
            fields = {}
            for k, v in row.items():
                if k == "_id":
                    continue
                fields[k] = v
            fields["imported_at"] = now
            try:
                await self._redis.xadd(
                    self._redis.key("exp", "negative"),
                    fields
                )
                if exp_id:
                    await self._redis.sadd(imported_ids_key, exp_id)
                neg_n += 1
            except Exception as e:
                errs.append(f"导入负经验失败: {e}")

        return pos_n, neg_n, errs

    async def _import_goals(
        self,
        goals: List[dict],
        policy: str
    ) -> Tuple[int, List[str]]:
        """导入 Goals。"""
        n = 0
        errs = []

        for g in goals:
            if not g or not g.get("id"):
                continue
            goal_id = g["id"]
            key = self._redis.key("goal", goal_id)
            exists = await self._redis.exists(key)

            if exists:
                if policy == "skip":
                    continue
                if policy == "overwrite":
                    await self._redis.delete(
                        key,
                        self._redis.key("goal", goal_id, "phases"),
                        self._redis.key("goal", goal_id, "subtasks"),
                    )
                    await self._redis.zrem(self._redis.key("goal", "list"), goal_id)

            # 写入 Goal Hash
            data = {
                "id": goal_id,
                "title": g.get("title", ""),
                "description": g.get("description", ""),
                "status": g.get("status", "pending"),
                "priority": str(g.get("priority", 5)),
                "parent_goal_id": g.get("parent_goal_id", ""),
                "tags": json.dumps(g.get("tags", [])),
                "progress": f"{g.get('progress', 0):.1f}",
                "created_at": g.get("created_at", ""),
                "updated_at": g.get("updated_at", ""),
            }

            try:
                await self._redis.hset(key, data)
                await self._redis.zadd(
                    self._redis.key("goal", "list"),
                    {goal_id: float(g.get("priority", 5))},
                )
                phases = g.get("phases", [])
                if phases:
                    for p in phases:
                        await self._redis.rpush(
                            self._redis.key("goal", goal_id, "phases"), p
                        )
                n += 1
            except Exception as e:
                errs.append(f"导入 Goal {goal_id} 失败: {e}")

        return n, errs

    async def _import_tasks(
        self,
        tasks: List[dict],
        policy: str
    ) -> Tuple[int, List[str]]:
        """导入 Tasks。"""
        n = 0
        errs = []
        import time

        for t in tasks:
            if not t or not t.get("id"):
                continue
            task_id = t["id"]
            key = self._redis.key("task", task_id)
            exists = await self._redis.exists(key)

            if exists:
                if policy == "skip":
                    continue
                if policy == "overwrite":
                    await self._redis.delete(key)
                    # 从各队列中移除
                    for q in ["pending", "running", "completed", "failed", "blocked", "interrupted", "review"]:
                        await self._redis.zrem(
                            self._redis.key("task", "queue", q), task_id
                        )

            # 写入 Task Hash
            # 状态规范化：running→interrupted（避免被watchdog误判为僵尸任务），review→pending
            status = t.get("status", "pending")
            if status == "running":
                status = "interrupted"
            elif status == "review":
                status = "pending"
            data = self._task_to_map(t)
            data["status"] = status
            try:
                await self._redis.hset(key, data)
                # 加入对应状态队列
                await self._redis.zadd(
                    self._redis.key("task", "queue", status),
                    {task_id: float(time.time())},
                )
                n += 1
            except Exception as e:
                errs.append(f"导入 Task {task_id} 失败: {e}")

        return n, errs

    def _task_to_map(self, t: dict) -> dict:
        """将 Task dict 转换为 Redis Hash 存储格式。"""
        return {
            "id": t.get("id", ""),
            "goal_id": t.get("goal_id", ""),
            "parent_task_id": t.get("parent_task_id", ""),
            "title": t.get("title", ""),
            "description": t.get("description", ""),
            "status": t.get("status", "pending"),
            "progress": f"{t.get('progress', 0):.1f}",
            "skill_type": t.get("skill_type", ""),
            "phase": t.get("phase", ""),
            "dependencies": json.dumps(t.get("dependencies", [])),
            "prerequisites": json.dumps(t.get("prerequisites", [])),
            "artifacts": json.dumps(t.get("artifacts", [])),
            "test_design": json.dumps(t.get("test_design", {})) if t.get("test_design") else "",
            "estimated_tokens": str(t.get("estimated_tokens", 0)),
            "difficulty": str(t.get("difficulty", 5)),
            "priority": str(t.get("priority", 5)),
            "claimed_by": t.get("claimed_by", ""),
            "summary": t.get("summary", ""),
            "tokens_used": str(t.get("tokens_used", 0)),
            "retry_count": str(t.get("retry_count", 0)),
            "created_at": t.get("created_at", ""),
            "updated_at": t.get("updated_at", ""),
            "completed_at": t.get("completed_at", ""),
        }
