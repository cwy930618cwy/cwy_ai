import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from agentflow.common import (
    generate_task_id, NotFoundError, InvalidParamError,
    TaskAlreadyClaimedError, DependencyNotMetError,
)
from agentflow.storage import RedisClient
from agentflow.lock import LockManager
from .model import Task, TaskStatus, TestDesign


class TaskStore:
    def __init__(self, redis: RedisClient, lock_mgr: LockManager,
                 logger: logging.Logger, lock_ttl: int = 1800,
                 namespace: str = ""):
        self._redis = redis
        self._lock_mgr = lock_mgr
        self._logger = logger
        self._lock_ttl = lock_ttl
        self._namespace = namespace  # 当前命名空间（project_id），空表示默认命名空间

    def with_namespace(self, namespace: str) -> "TaskStore":
        """返回一个指定命名空间的 Store 视图（多租户隔离）。
        namespace 通常为 project_id，不同 namespace 的数据完全隔离。
        如果 namespace 为空，返回当前 Store 本身。
        """
        if not namespace:
            return self
        return TaskStore(
            redis=self._redis.with_namespace(namespace),
            lock_mgr=self._lock_mgr,
            logger=self._logger,
            lock_ttl=self._lock_ttl,
            namespace=namespace,
        )

    # ── Batch Create ──────────────────────────────────────────────────────────

    async def create_batch(self, goal_id: str, tasks_params: List[Dict]) -> List[Task]:
        if not goal_id:
            raise InvalidParamError("goal_id 不能为空")
        if not tasks_params:
            raise InvalidParamError("tasks 列表不能为空")

        # Generate IDs first for dependency resolution
        task_ids = [generate_task_id() for _ in tasks_params]
        title_to_id = {item.get("title", ""): task_ids[i] for i, item in enumerate(tasks_params)}

        # 循环依赖检测（防止任务永远无法被认领）
        cycle_err = self._validate_no_cycles(tasks_params, title_to_id)
        if cycle_err:
            raise InvalidParamError(cycle_err)

        tasks = []
        now = datetime.now(timezone.utc).isoformat()
        for i, item in enumerate(tasks_params):
            resolved_deps = self._resolve_dependencies(item.get("dependencies", []), title_to_id)
            difficulty = item.get("difficulty", 5)
            if difficulty <= 0:
                difficulty = 5
            if difficulty > 10:
                difficulty = 10
            test_design = None
            if td := item.get("test_design"):
                test_design = TestDesign.from_dict(td) if isinstance(td, dict) else None
            t = Task(
                id=task_ids[i],
                goal_id=goal_id,
                title=item.get("title", ""),
                description=item.get("description", ""),
                status=TaskStatus.PENDING,
                skill_type=item.get("skill_type", ""),
                phase=item.get("phase", ""),
                dependencies=resolved_deps,
                prerequisites=item.get("prerequisites", []),
                estimated_tokens=item.get("estimated_tokens", 0),
                difficulty=difficulty,
                priority=item.get('priority', 5),
                test_design=test_design,
                created_at=now,
                updated_at=now,
            )
            tasks.append(t)

        ts = int(time.time() * 1000)
        for t in tasks:
            key = self._redis.key("task", t.id)
            await self._redis.hset(key, self._task_to_map(t))
            await self._redis.zadd(
                self._redis.key("task", "queue", TaskStatus.PENDING),
                {t.id: float(ts)},
            )
            await self._redis.rpush(self._redis.key("goal", goal_id, "subtasks"), t.id)

        self._logger.info(f"任务批量创建完成 goal_id={goal_id} count={len(tasks)}")
        return tasks

    # ── Claim ─────────────────────────────────────────────────────────────────

    async def claim(self, agent_id: str, task_id: str = "",
                    skill_types: Optional[List[str]] = None,
                    affinity_skills: Optional[List[str]] = None,
                    max_difficulty: int = 0, strict_skill: bool = False) -> Dict:
        """认领任务。
        affinity_skills: Agent 历史擅长的 skill_type 列表，命中时综合得分 +5（亲和性调度）。
        """
        if not agent_id:
            raise InvalidParamError("agent_id 不能为空")

        if task_id:
            exists = await self._redis.exists(self._redis.key("task", task_id))
            if not exists:
                return {"result": "not_found"}
            if err := await self._check_goal_active(task_id):
                return {"result": "goal_not_active"}
            current_status = await self._redis.hget(self._redis.key("task", task_id), "status") or ""
            if current_status == TaskStatus.PENDING:
                return await self._claim_from_pending(task_id, agent_id)
            elif current_status in (TaskStatus.RUNNING, TaskStatus.INTERRUPTED,
                                     TaskStatus.FAILED, TaskStatus.BLOCKED):
                return await self._force_claim(task_id, agent_id)
            elif current_status == TaskStatus.COMPLETED:
                return {"result": "already_completed"}
            else:
                return {"result": "invalid_status"}

        # 智能派发（带重试，应对并发竞争场景）
        for attempt in range(3):
            dispatch = await self._smart_dispatch(
                agent_id, skill_types or [], affinity_skills or [], max_difficulty, strict_skill
            )
            if not dispatch:
                wait_result = await self._check_all_blocked_by_running()
                if wait_result:
                    return wait_result
                return {"result": "no_available"}

            tid = dispatch["task_id"]
            claim_reason = dispatch["claim_reason"]
            source_queue = dispatch["source_queue"]

            if source_queue in (TaskStatus.INTERRUPTED, TaskStatus.FAILED, TaskStatus.BLOCKED):
                result = await self._force_claim(tid, agent_id)
                if result.get("result") == "success":
                    result["claim_reason"] = claim_reason
                return result
            else:
                result = await self._claim_from_pending(tid, agent_id)
                if result.get("result") == "success":
                    result["claim_reason"] = claim_reason
                    return result
                if result.get("result") == "dependency_not_met":
                    return result

        return {"result": "no_available"}

    async def _check_goal_active(self, task_id: str) -> Optional[str]:
        goal_id = await self._redis.hget(self._redis.key("task", task_id), "goal_id")
        if not goal_id:
            return None
        status = await self._redis.hget(self._redis.key("goal", goal_id), "status")
        if status != "active":
            return f"目标 {goal_id} 未处于进行中状态(当前: {status})"
        return None

    async def _claim_from_pending(self, task_id: str, agent_id: str) -> Dict:
        if not await self._check_dependencies(task_id):
            return {"result": "dependency_not_met"}
        lock_key = self._redis.key("lock", "task", task_id)
        pending_queue = self._redis.key("task", "queue", TaskStatus.PENDING)
        running_queue = self._redis.key("task", "queue", TaskStatus.RUNNING)
        r = await self._lock_mgr.claim_task(
            lock_key, pending_queue, running_queue, agent_id, task_id, self._lock_ttl
        )
        if r == 1:
            now = datetime.now(timezone.utc).isoformat()
            await self._redis.hset(self._redis.key("task", task_id), {
                "claimed_by": agent_id,
                "status": TaskStatus.RUNNING,
                "updated_at": now,
            })
            await self._lock_mgr.update_heartbeat(agent_id, 90)
            task = await self.get(task_id)
            return {"result": "success", "task": task.to_dict()}
        elif r == 0:
            return {"result": "already_claimed"}
        else:
            return {"result": "no_available"}

    async def _force_claim(self, task_id: str, agent_id: str) -> Dict:
        lock_key = self._redis.key("lock", "task", task_id)
        running_queue = self._redis.key("task", "queue", TaskStatus.RUNNING)
        all_queues = [
            self._redis.key("task", "queue", s)
            for s in TaskStatus.ALL
        ]
        await self._lock_mgr.force_claim_task(
            lock_key, running_queue, agent_id, task_id, self._lock_ttl, *all_queues
        )
        now = datetime.now(timezone.utc).isoformat()
        await self._redis.hset(self._redis.key("task", task_id), {
            "claimed_by": agent_id,
            "status": TaskStatus.RUNNING,
            "updated_at": now,
        })
        await self._lock_mgr.update_heartbeat(agent_id, 90)
        task = await self.get(task_id)
        return {"result": "success", "task": task.to_dict()}

    async def _smart_dispatch(self, agent_id: str, skill_types: List[str],
                               affinity_skills: List[str],
                               max_difficulty: int, strict_skill: bool) -> Optional[Dict]:
        # 按优先级顺序扫描队列：interrupted > blocked > failed > pending
        queue_priority = [
            (TaskStatus.INTERRUPTED, "recovery", False),
            (TaskStatus.BLOCKED, "unblocked", True),
            (TaskStatus.FAILED, "retry", False),
            (TaskStatus.PENDING, "normal", True),
        ]
        for status, claim_reason, check_deps in queue_priority:
            result = await self._find_best_from_queue(
                status, claim_reason, check_deps,
                skill_types, affinity_skills, max_difficulty, strict_skill
            )
            if result:
                return result
        return None

    async def _find_best_from_queue(self, status: str, claim_reason: str, check_deps: bool,
                                     skill_types: List[str], affinity_skills: List[str],
                                     max_difficulty: int, strict_skill: bool) -> Optional[Dict]:
        """从指定队列中查找最佳任务。
        综合得分 = priority*10 + affinity_bonus + deadline_bonus
          - 亲和性加分：affinity_skills 中包含的 skill_type +5
          - deadline 紧迫度加分：24h内 +8，48h内 +4，72h内 +2
        """
        queue_key = self._redis.key("task", "queue", status)
        members = await self._redis.zrangebyscore(queue_key, "-inf", "+inf")
        if not members:
            return None

        # 构建亲和性集合，O(1) 查找
        affinity_set = set(affinity_skills)
        now = datetime.now(timezone.utc)

        candidates = []
        for task_id in members:
            if check_deps and not await self._check_dependencies(task_id):
                continue
            data = await self._redis.hgetall(self._redis.key("task", task_id))
            if not data:
                continue
            goal_id = data.get("goal_id", "")
            if goal_id:
                goal_status = await self._redis.hget(self._redis.key("goal", goal_id), "status")
                if goal_status != "active":
                    continue
            difficulty = int(data.get("difficulty", 5))
            if max_difficulty > 0 and difficulty > max_difficulty:
                continue
            skill_type = data.get("skill_type", "")
            matched = not skill_types or skill_type in skill_types
            priority = int(data.get("priority", 5))

            # 综合得分计算
            score = float(priority) * 10.0

            # 亲和性加分：Agent 历史擅长的 skill_type 优先
            if skill_type in affinity_set:
                score += 5.0

            # deadline 紧迫度加分
            deadline_str = data.get("deadline", "")
            if deadline_str:
                try:
                    dl = datetime.fromisoformat(deadline_str)
                    # 确保时区一致
                    if dl.tzinfo is None:
                        dl = dl.replace(tzinfo=timezone.utc)
                    remaining_hours = (dl - now).total_seconds() / 3600
                    if remaining_hours <= 24:
                        score += 8.0   # 24h 内：紧急
                    elif remaining_hours <= 48:
                        score += 4.0   # 48h 内：较紧
                    elif remaining_hours <= 72:
                        score += 2.0   # 72h 内：关注
                except Exception:
                    pass

            candidates.append({"task_id": task_id, "score": score, "match": matched})

        if not candidates:
            return None

        if strict_skill and skill_types:
            candidates = [c for c in candidates if c["match"]]
            if not candidates:
                return None

        # 排序：先匹配的 → 再按综合得分降序（含亲和性+deadline紧迫度+优先级）
        candidates.sort(key=lambda c: (not c["match"], -c["score"]))
        return {
            "task_id": candidates[0]["task_id"],
            "claim_reason": claim_reason,
            "source_queue": status,
        }

    async def _check_all_blocked_by_running(self) -> Optional[Dict]:
        running_members = await self._redis.zrangebyscore(
            self._redis.key("task", "queue", TaskStatus.RUNNING), "-inf", "+inf"
        )
        if not running_members:
            return None
        pending_members = await self._redis.zrangebyscore(
            self._redis.key("task", "queue", TaskStatus.PENDING), "-inf", "+inf"
        )
        if not pending_members:
            return None
        running_set = set(running_members)
        all_blocked = True
        for task_id in pending_members:
            if await self._check_dependencies(task_id):
                all_blocked = False
                break
        if not all_blocked:
            return None
        running_infos = []
        for task_id in running_members:
            data = await self._redis.hgetall(self._redis.key("task", task_id))
            if data:
                running_infos.append({
                    "task_id": task_id,
                    "title": data.get("title", ""),
                    "claimed_by": data.get("claimed_by", ""),
                    "progress": data.get("progress", "0"),
                })
        return {
            "result": "wait_for_running",
            "wait_info": {
                "message": f"当前有 {len(running_members)} 个任务正在运行中，所有 {len(pending_members)} 个待处理任务都依赖于运行中的任务。",
                "running_tasks": running_infos,
                "pending_task_count": len(pending_members),
                "suggestion": "等待运行中的任务完成，或使用指定 task_id 强制接管",
            },
        }

    # ── Report Result ─────────────────────────────────────────────────────────

    async def report_result(self, task_id: str, agent_id: str, status: str,
                             summary: str, tokens_used: int = 0,
                             key_decisions: Optional[List[str]] = None,
                             self_reflection: str = "") -> Dict:
        task = await self.get(task_id)
        now = datetime.now(timezone.utc).isoformat()

        updates: Dict[str, Any] = {
            "status": status,
            "summary": summary,
            "updated_at": now,
        }
        if tokens_used:
            updates["tokens_used"] = str(task.tokens_used + tokens_used)
        if status == TaskStatus.COMPLETED:
            updates["completed_at"] = now
        if key_decisions:
            updates["key_decisions"] = json.dumps(key_decisions)

        await self._redis.hset(self._redis.key("task", task_id), updates)

        # Move between queues
        old_queue = self._redis.key("task", "queue", TaskStatus.RUNNING)
        new_queue = self._redis.key("task", "queue", status)
        await self._redis.zrem(old_queue, task_id)
        await self._redis.zadd(new_queue, {task_id: float(time.time())})

        # Release lock
        lock_key = self._redis.key("lock", "task", task_id)
        await self._redis.delete(lock_key)

        # Update goal progress
        goal_progress = await self._calculate_goal_progress(task.goal_id)

        # Try auto-complete parent
        if task.parent_task_id:
            await self._try_auto_complete_parent(task.parent_task_id)

        # Unblock dependent tasks
        if status == TaskStatus.COMPLETED:
            await self._unblock_dependents(task_id)

        # 更新 Skill pass_rate（任务完成/失败时统计）
        if task.skill_type:
            import asyncio
            asyncio.ensure_future(
                self._update_skill_pass_rate(task.skill_type, status == TaskStatus.COMPLETED)
            )

        return {
            "confirm": f"任务 {task_id} 已{status}",
            "goal_progress": goal_progress,
            "next_recommendation": "继续认领下一个任务" if status == TaskStatus.COMPLETED else "",
        }

    async def _calculate_goal_progress(self, goal_id: str) -> float:
        if not goal_id:
            return 0.0
        subtask_ids = await self._redis.lrange(
            self._redis.key("goal", goal_id, "subtasks"), 0, -1
        )
        if not subtask_ids:
            return 0.0
        completed = 0
        for tid in subtask_ids:
            st = await self._redis.hget(self._redis.key("task", tid), "status")
            if st == TaskStatus.COMPLETED:
                completed += 1
        progress = completed / len(subtask_ids) * 100
        await self._redis.hset(self._redis.key("goal", goal_id), {
            "progress": f"{progress:.1f}",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        return round(progress, 1)

    async def _unblock_dependents(self, completed_task_id: str) -> None:
        blocked = await self._redis.zrangebyscore(
            self._redis.key("task", "queue", TaskStatus.BLOCKED), "-inf", "+inf"
        )
        for tid in blocked:
            if await self._check_dependencies(tid):
                await self._redis.zrem(self._redis.key("task", "queue", TaskStatus.BLOCKED), tid)
                await self._redis.zadd(
                    self._redis.key("task", "queue", TaskStatus.PENDING),
                    {tid: float(time.time())},
                )
                await self._redis.hset(self._redis.key("task", tid), {
                    "status": TaskStatus.PENDING,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                self._logger.info(f"任务解除阻塞 id={tid}")

    async def _try_auto_complete_parent(self, parent_task_id: str) -> None:
        children = await self._redis.lrange(
            self._redis.key("task", parent_task_id, "subtasks"), 0, -1
        )
        if not children:
            return
        for cid in children:
            st = await self._redis.hget(self._redis.key("task", cid), "status")
            if st != TaskStatus.COMPLETED:
                return
        now = datetime.now(timezone.utc).isoformat()
        await self._redis.hset(self._redis.key("task", parent_task_id), {
            "status": TaskStatus.COMPLETED,
            "completed_at": now,
            "updated_at": now,
            "summary": "所有子任务已完成，自动标记为完成",
        })
        parent_queue_key = None
        for s in TaskStatus.ALL:
            if s != TaskStatus.COMPLETED:
                await self._redis.zrem(self._redis.key("task", "queue", s), parent_task_id)
        await self._redis.zadd(
            self._redis.key("task", "queue", TaskStatus.COMPLETED),
            {parent_task_id: float(time.time())},
        )
        self._logger.info(f"父任务自动完成 id={parent_task_id}")

    # ── Release ───────────────────────────────────────────────────────────────

    async def release(self, task_id: str, agent_id: str, reason: str) -> None:
        task = await self.get(task_id)
        now = datetime.now(timezone.utc).isoformat()
        await self._redis.hset(self._redis.key("task", task_id), {
            "status": TaskStatus.PENDING,
            "claimed_by": "",
            "updated_at": now,
        })
        await self._redis.zrem(self._redis.key("task", "queue", TaskStatus.RUNNING), task_id)
        await self._redis.zadd(
            self._redis.key("task", "queue", TaskStatus.PENDING),
            {task_id: float(time.time())},
        )
        lock_key = self._redis.key("lock", "task", task_id)
        await self._redis.delete(lock_key)
        self._logger.info(f"任务已释放 id={task_id} agent={agent_id} reason={reason}")

    # ── Get / Update / List ───────────────────────────────────────────────────

    async def get(self, task_id: str) -> Task:
        data = await self._redis.hgetall(self._redis.key("task", task_id))
        if not data:
            raise NotFoundError(f"task {task_id}")
        return self._map_to_task(data)

    async def update(self, task_id: str, fields: Dict) -> Task:
        key = self._redis.key("task", task_id)
        if not await self._redis.exists(key):
            raise NotFoundError(f"task {task_id}")

        allowed = {"title", "description", "priority", "skill_type", "phase",
                   "dependencies", "prerequisites", "estimated_tokens", "difficulty",
                   "status", "test_design",
                   # 调度增强字段
                   "deadline",
                   # Review 相关字段
                   "review_result", "reviewed_at", "reviewed_by", "review_comment"}
        updates: Dict[str, Any] = {}
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k in ("dependencies", "prerequisites", "artifacts"):
                updates[k] = json.dumps(v) if isinstance(v, list) else v
            elif k == "test_design":
                updates[k] = json.dumps(v) if isinstance(v, dict) else v
            else:
                updates[k] = str(v)

        # deadline 字段格式校验（必须在写入之前）
        if "deadline" in fields:
            dl_val = fields["deadline"]
            if dl_val:
                try:
                    datetime.fromisoformat(str(dl_val))
                except ValueError:
                    raise InvalidParamError("deadline 格式无效，需为 ISO8601 格式")

        if "status" in fields:
            new_status = str(fields["status"])
            # 委托给 update_status 方法处理（含队列迁移、review级联等完整逻辑）
            await self.update_status(task_id, new_status)
            del updates["status"]  # 已由 update_status 处理，从 updates 中移除

        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self._redis.hset(key, updates)
        return await self.get(task_id)

    async def update_progress(self, task_id: str, agent_id: str, progress: float, message: str = "") -> Task:
        key = self._redis.key("task", task_id)
        data = await self._redis.hgetall(key)
        if not data:
            raise NotFoundError(f"task {task_id}")
        if data.get("claimed_by") != agent_id:
            raise InvalidParamError(f"只有任务认领者才能更新进度")
        updates = {
            "progress": f"{progress:.1f}",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._redis.hset(key, updates)
        await self._lock_mgr.update_heartbeat(agent_id, 90)
        return await self.get(task_id)

    async def list_by_goal(self, goal_id: str) -> List[Task]:
        """获取目标下所有任务列表。"""
        subtask_ids = await self._redis.lrange(
            self._redis.key("goal", goal_id, "subtasks"), 0, -1
        )
        tasks = []
        for tid in subtask_ids:
            try:
                t = await self.get(tid)
                tasks.append(t)
            except Exception:
                self._logger.warning(f"获取任务详情失败 task_id={tid}")
        return tasks

    async def list_by_status(self, status: str, page: int = 1, page_size: int = 20) -> Tuple[List[Task], int]:
        """获取指定状态的任务列表（分页）。"""
        queue_key = self._redis.key("task", "queue", status)
        total = await self._redis.zcard(queue_key)
        start = (page - 1) * page_size
        stop = start + page_size - 1
        # 使用 zrange 获取（按分数升序），stop=-1 表示到末尾
        members = await self._redis.zrange(queue_key, start, stop)
        tasks = []
        for task_id in members:
            try:
                t = await self.get(task_id)
                tasks.append(t)
            except Exception:
                self._logger.warning(f"获取任务详情失败 task_id={task_id}")
        return tasks, total

    async def list(self, goal_id: str = "", parent_task_id: str = "",
                   status: str = "", statuses: Optional[List[str]] = None,
                   exclude_status: Optional[List[str]] = None,
                   skill_type: str = "", claimed_by: str = "",
                   min_difficulty: int = 0, max_difficulty: int = 0,
                   keyword: str = "", group_by: str = "",
                   page: int = 1, page_size: int = 20) -> Tuple[Any, int]:
        if page < 1:
            page = 1
        if page_size < 1 or page_size > 100:
            page_size = 20

        # 构建状态过滤集合（statuses 优先级高于 status）
        status_filter: set = set()
        if statuses:
            status_filter = set(statuses)
        elif status:
            status_filter = {status}
        exclude_set = set(exclude_status or [])

        # 判断是否有高级过滤条件（需要全量扫描再过滤）
        has_advanced_filter = (
            len(statuses or []) > 0 or len(exclude_status or []) > 0
            or skill_type or claimed_by
            or min_difficulty > 0 or max_difficulty > 0
            or keyword or group_by
        )

        # 收集全部任务 ID
        all_ids: List[str] = []
        if goal_id:
            ids = await self._redis.lrange(self._redis.key("goal", goal_id, "subtasks"), 0, -1)
            all_ids = list(ids)
        elif parent_task_id:
            # 从父任务的子任务列表获取
            ids = await self._redis.lrange(self._redis.key("task", parent_task_id, "subtasks"), 0, -1)
            all_ids = list(ids)
        elif not has_advanced_filter and status:
            # 简单状态查询（旧路径，保持兼容）
            tasks, total = await self.list_by_status(status, page, page_size)
            return [t.to_dict() for t in tasks], total
        else:
            # 全量扫描所有状态队列
            queues_to_scan = list(TaskStatus.ALL)
            seen: set = set()
            for q in queues_to_scan:
                members = await self._redis.zrangebyscore(
                    self._redis.key("task", "queue", q), "-inf", "+inf"
                )
                for m in members:
                    if m not in seen:
                        seen.add(m)
                        all_ids.append(m)

        # 多维过滤
        tasks = []
        for tid in all_ids:
            try:
                t = await self.get(tid)
            except Exception:
                continue
            # parent_task_id 过滤（当从全量扫描时）
            if parent_task_id and t.parent_task_id != parent_task_id:
                continue
            # 多状态过滤
            if status_filter and t.status not in status_filter:
                continue
            # 排除状态
            if exclude_set and t.status in exclude_set:
                continue
            # skill_type 过滤
            if skill_type and t.skill_type != skill_type:
                continue
            # 领取者过滤
            if claimed_by and t.claimed_by != claimed_by:
                continue
            # 难度范围过滤
            if min_difficulty > 0 and t.difficulty < min_difficulty:
                continue
            if max_difficulty > 0 and t.difficulty > max_difficulty:
                continue
            # 关键词搜索（标题+描述，不区分大小写）
            if keyword:
                kw = keyword.lower()
                if kw not in t.title.lower() and kw not in t.description.lower():
                    continue
            tasks.append(t)

        # 聚合统计模式
        if group_by:
            groups: Dict[str, int] = {}
            for t in tasks:
                if group_by == "skill_type":
                    key_val = t.skill_type or "未分类"
                elif group_by == "status":
                    key_val = t.status or "未分类"
                elif group_by == "phase":
                    key_val = t.phase or "未分类"
                else:
                    key_val = getattr(t, group_by, None) or "未分类"
                groups[key_val] = groups.get(key_val, 0) + 1
            return {
                "group_by": group_by,
                "groups": groups,
                "total": len(tasks),
            }, len(tasks)

        # 分页
        total = len(tasks)
        start = (page - 1) * page_size
        end = start + page_size
        return [t.to_dict() for t in tasks[start:end]], total

    async def split_task(self, parent_task_id: str, agent_id: str, subtasks: List[Dict]) -> List[Task]:
        parent = await self.get(parent_task_id)
        if parent.claimed_by != agent_id:
            raise InvalidParamError(f"只有任务认领者才能拆分任务")

        task_ids = [generate_task_id() for _ in subtasks]
        title_to_id = {item.get("title", ""): task_ids[i] for i, item in enumerate(subtasks)}
        now = datetime.now(timezone.utc).isoformat()
        result = []

        for i, item in enumerate(subtasks):
            difficulty = item.get("difficulty", 5) or 5
            test_design = None
            if td := item.get("test_design"):
                test_design = TestDesign.from_dict(td) if isinstance(td, dict) else None
            resolved_deps = self._resolve_dependencies(item.get("dependencies", []), title_to_id)
            t = Task(
                id=task_ids[i],
                goal_id=parent.goal_id,
                parent_task_id=parent_task_id,
                title=item.get("title", ""),
                description=item.get("description", ""),
                status=TaskStatus.PENDING,
                skill_type=item.get("skill_type", parent.skill_type),
                phase=item.get("phase", parent.phase),
                dependencies=resolved_deps,
                prerequisites=item.get("prerequisites", []),
                difficulty=min(max(difficulty, 1), 10),
                priority=5,
                test_design=test_design,
                created_at=now,
                updated_at=now,
            )
            await self._redis.hset(self._redis.key("task", t.id), self._task_to_map(t))
            await self._redis.zadd(
                self._redis.key("task", "queue", TaskStatus.PENDING),
                {t.id: float(time.time())},
            )
            await self._redis.rpush(self._redis.key("task", parent_task_id, "subtasks"), t.id)
            result.append(t)

        return result

    async def update_status(self, task_id: str, new_status: str) -> None:
        """手动更新任务状态（Dashboard 看板操作）。
        支持任意状态之间的迁移，包括队列移动和字段更新。
        """
        key = self._redis.key("task", task_id)
        if not await self._redis.exists(key):
            raise NotFoundError(f"task {task_id}")

        valid_statuses = {"pending", "running", "completed", "failed",
                          "blocked", "interrupted", "review"}
        if new_status not in valid_statuses:
            raise InvalidParamError(f"无效的状态 {new_status}")

        old_status = await self._redis.hget(key, "status") or ""
        if old_status == new_status:
            return  # 无需变更

        # review 状态特殊逻辑：必须所有子任务都已 completed
        if new_status == "review":
            await self._validate_all_subtasks_completed(task_id)

        now = datetime.now(timezone.utc).isoformat()
        updates: Dict[str, Any] = {
            "status": new_status,
            "updated_at": now,
        }
        if new_status == "pending":
            updates["claimed_by"] = ""
        if new_status == "completed":
            updates["progress"] = "100"

        await self._redis.hset(key, updates)

        # 从旧队列移除，加入新队列
        old_queue = self._redis.key("task", "queue", old_status)
        new_queue = self._redis.key("task", "queue", new_status)
        await self._redis.zrem(old_queue, task_id)
        await self._redis.zadd(new_queue, {task_id: float(time.time())})

        # 如果从 running 离开，释放锁
        if old_status == "running":
            lock_key = self._redis.key("lock", "task", task_id)
            await self._redis.delete(lock_key)

        # review 状态：级联设置所有子任务为 review
        if new_status == "review":
            await self._cascade_set_review(task_id)

        # 重新计算目标进度
        goal_id = await self._redis.hget(key, "goal_id") or ""
        if goal_id:
            await self._calculate_goal_progress(goal_id)

        self._logger.info(f"任务状态已手动更新 task_id={task_id} {old_status} -> {new_status}")

    async def _validate_all_subtasks_completed(self, task_id: str) -> None:
        """校验任务的所有子任务（包括孙任务）都已 completed。
        只有满足此条件，才允许切换到 review 状态。
        """
        subtask_ids = await self._redis.lrange(
            self._redis.key("task", task_id, "subtasks"), 0, -1
        )
        if not subtask_ids:
            return  # 没有子任务，允许直接 review（叶子任务）

        for sub_id in subtask_ids:
            status = await self._redis.hget(self._redis.key("task", sub_id), "status") or ""
            if status != TaskStatus.COMPLETED:
                sub_title = await self._redis.hget(self._redis.key("task", sub_id), "title") or sub_id
                raise InvalidParamError(
                    f"子任务 [{sub_title}] 当前状态为 {status}，需所有子任务/孙任务完成后才能切换 review"
                )
            # 递归检查孙任务
            await self._validate_all_subtasks_completed(sub_id)

    async def _cascade_set_review(self, parent_task_id: str) -> None:
        """级联设置所有子任务/孙任务为 review 状态。"""
        subtask_ids = await self._redis.lrange(
            self._redis.key("task", parent_task_id, "subtasks"), 0, -1
        )
        if not subtask_ids:
            return

        now = datetime.now(timezone.utc).isoformat()
        for sub_id in subtask_ids:
            old_status = await self._redis.hget(self._redis.key("task", sub_id), "status") or ""
            if old_status == "review":
                continue
            await self._redis.hset(self._redis.key("task", sub_id), {
                "status": "review",
                "updated_at": now,
            })
            await self._redis.zrem(self._redis.key("task", "queue", old_status), sub_id)
            await self._redis.zadd(
                self._redis.key("task", "queue", "review"),
                {sub_id: float(time.time())},
            )
            self._logger.info(f"子任务级联设置为 review sub_id={sub_id} old_status={old_status}")
            # 递归处理孙任务
            await self._cascade_set_review(sub_id)

    async def accumulate_tokens(self, task_id: str, tokens: int) -> None:
        """累加任务 Token 消耗（由上下文编译自动调用）。"""
        if not task_id or tokens <= 0:
            return
        key = self._redis.key("task", task_id)
        current_str = await self._redis.hget(key, "tokens_used") or "0"
        try:
            current = int(current_str)
        except ValueError:
            current = 0
        new_total = current + tokens
        await self._redis.hset(key, {
            "tokens_used": str(new_total),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })

    async def _update_skill_pass_rate(self, skill_type: str, passed: bool) -> None:
        """更新 Skill 的通过率（任务完成/失败时调用）。
        采用滑动窗口统计：pass_count / total_count，存储在 metrics Hash 中。
        """
        try:
            metrics_key = self._redis.key("skill", skill_type, "metrics")
            # 原子递增总任务数
            total = await self._redis.hincr_by(metrics_key, "total_count", 1)
            # 如果通过，递增通过数
            if passed:
                pass_count = await self._redis.hincr_by(metrics_key, "pass_count", 1)
            else:
                pass_count_str = await self._redis.hget(metrics_key, "pass_count") or "0"
                try:
                    pass_count = int(pass_count_str)
                except ValueError:
                    pass_count = 0
            # 计算并更新 pass_rate
            if total > 0:
                pass_rate = pass_count / total
                await self._redis.hset(metrics_key, {"pass_rate": f"{pass_rate:.4f}"})
            self._logger.debug(f"Skill pass_rate 已更新 skill={skill_type} pass={pass_count} total={total}")
        except Exception as e:
            self._logger.warning(f"更新 Skill pass_rate 失败 skill={skill_type} err={e}")

    async def get_task_skill_type(self, task_id: str) -> str:
        """获取任务的 skill_type（供 evolution_hint 使用）。"""
        return await self._redis.hget(self._redis.key("task", task_id), "skill_type") or ""

    async def count_by_status(self, namespace: str = "") -> Dict[str, int]:
        """按状态统计任务数量。"""
        result: Dict[str, int] = {}
        for status in TaskStatus.ALL:
            queue_key = self._redis.key("task", "queue", status)
            count = await self._redis.zcard(queue_key)
            result[status] = count
        return result

    async def delete(self, task_id: str) -> None:
        for s in TaskStatus.ALL:
            await self._redis.zrem(self._redis.key("task", "queue", s), task_id)
        await self._redis.delete(self._redis.key("task", task_id))

    async def delete_by_goal(self, goal_id: str) -> int:
        subtask_ids = await self._redis.lrange(
            self._redis.key("goal", goal_id, "subtasks"), 0, -1
        )
        for tid in subtask_ids:
            await self.delete(tid)
        await self._redis.delete(self._redis.key("goal", goal_id, "subtasks"))
        return len(subtask_ids)

    # ── Dependencies ─────────────────────────────────────────────────────────

    async def _check_dependencies(self, task_id: str) -> bool:
        deps_json = await self._redis.hget(self._redis.key("task", task_id), "dependencies")
        if not deps_json or deps_json in ("[]", "null"):
            return True
        try:
            deps = json.loads(deps_json)
        except Exception:
            return True
        for dep_id in deps:
            status = await self._redis.hget(self._redis.key("task", dep_id), "status")
            if status != TaskStatus.COMPLETED:
                return False
        return True

    def _resolve_dependencies(self, deps: List[str], title_to_id: Dict[str, str]) -> List[str]:
        if not deps:
            return []
        resolved = []
        for dep in deps:
            if dep.startswith("task_"):
                resolved.append(dep)
            elif dep in title_to_id:
                resolved.append(title_to_id[dep])
            else:
                # 尝试全局标题搜索（跨目标依赖）
                global_id = self._find_task_by_title_sync(dep)
                if global_id:
                    resolved.append(global_id)
                else:
                    self._logger.warning(f"依赖引用无法解析，已忽略: {dep}")
        return resolved

    def _find_task_by_title_sync(self, title: str) -> str:
        """同步版本的全局标题搜索（仅在初始化时使用）。
        
        注意：此方法在异步环境中不可用，仅作为占位符。
        跨目标的标题依赖解析请使用异步方法 find_task_by_title()。
        在 create_batch/split_task 中，同批次内的标题依赖已通过 title_to_id 字典解析，
        仅跨批次/跨目标的依赖才会走到此方法（此时无法解析，会记录警告日志）。
        """
        # 此方法无法在同步上下文中访问 Redis，返回空字符串表示无法解析
        return ""

    async def find_task_by_title(self, title: str) -> str:
        """全局搜索任务标题（跨目标依赖支持）。"""
        for status in TaskStatus.ALL:
            queue_key = self._redis.key("task", "queue", status)
            members = await self._redis.zrangebyscore(queue_key, "-inf", "+inf")
            for task_id in members:
                t = await self._redis.hget(self._redis.key("task", task_id), "title")
                if t == title:
                    return task_id
        return ""

    def _validate_no_cycles(self, tasks: List[Dict], title_to_id: Dict[str, str]) -> Optional[str]:
        """检测循环依赖（DFS）。返回错误信息，无循环则返回 None。"""
        # 构建邻接表: task_id -> 依赖的 task_id 列表
        graph: Dict[str, List[str]] = {}
        for item in tasks:
            tid = title_to_id.get(item.get("title", ""), "")
            if not tid:
                continue
            graph[tid] = []
            for dep in item.get("dependencies", []):
                dep_id = dep if dep.startswith("task_") else title_to_id.get(dep, dep)
                graph[tid].append(dep_id)

        # DFS 检测环: 0=未访问, 1=访问中, 2=已完成
        visited: Dict[str, int] = {}
        cycle_node = [""]

        def dfs(node: str) -> bool:
            visited[node] = 1
            for nxt in graph.get(node, []):
                if visited.get(nxt) == 1:
                    cycle_node[0] = nxt
                    return True
                if visited.get(nxt, 0) == 0 and dfs(nxt):
                    return True
            visited[node] = 2
            return False

        for node_id in list(graph.keys()):
            if visited.get(node_id, 0) == 0 and dfs(node_id):
                # 找到涉及环的任务标题
                cycle_name = cycle_node[0]
                for title, tid in title_to_id.items():
                    if tid == cycle_node[0]:
                        cycle_name = title
                        break
                return f"检测到循环依赖，涉及任务: {cycle_name}"
        return None

    # ── Serialization ─────────────────────────────────────────────────────────

    def _task_to_map(self, t: Task) -> Dict[str, str]:
        m: Dict[str, str] = {
            "id": t.id,
            "goal_id": t.goal_id,
            "parent_task_id": t.parent_task_id,
            "title": t.title,
            "description": t.description,
            "status": t.status,
            "progress": f"{t.progress:.1f}",
            "skill_type": t.skill_type,
            "phase": t.phase,
            "dependencies": json.dumps(t.dependencies),
            "prerequisites": json.dumps(t.prerequisites),
            "estimated_tokens": str(t.estimated_tokens),
            "difficulty": str(t.difficulty),
            "priority": str(t.priority),
            "claimed_by": t.claimed_by,
            "artifacts": json.dumps(t.artifacts),
            "summary": t.summary,
            "tokens_used": str(t.tokens_used),
            "retry_count": str(t.retry_count),
            "created_at": t.created_at,
            "updated_at": t.updated_at,
            # 调度增强字段
            "deadline": t.deadline,
            # Review 相关字段
            "review_result": t.review_result,
            "reviewed_by": t.reviewed_by,
            "review_comment": t.review_comment,
            "reviewed_at": t.reviewed_at,
        }
        if t.test_design:
            m["test_design"] = json.dumps(t.test_design.to_dict())
        if t.completed_at:
            m["completed_at"] = t.completed_at
        if t.interrupted_at:
            m["interrupted_at"] = t.interrupted_at
        return m

    def _map_to_task(self, data: Dict) -> Task:
        dependencies = []
        if dep_str := data.get("dependencies"):
            try:
                dependencies = json.loads(dep_str)
            except Exception:
                pass
        prerequisites = []
        if pre_str := data.get("prerequisites"):
            try:
                prerequisites = json.loads(pre_str)
            except Exception:
                pass
        artifacts = []
        if art_str := data.get("artifacts"):
            try:
                artifacts = json.loads(art_str)
            except Exception:
                pass
        test_design = None
        if td_str := data.get("test_design"):
            try:
                test_design = TestDesign.from_dict(json.loads(td_str))
            except Exception:
                pass
        return Task(
            id=data.get("id", ""),
            goal_id=data.get("goal_id", ""),
            parent_task_id=data.get("parent_task_id", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            status=data.get("status", TaskStatus.PENDING),
            progress=float(data.get("progress", 0)),
            skill_type=data.get("skill_type", ""),
            phase=data.get("phase", ""),
            dependencies=dependencies,
            prerequisites=prerequisites,
            estimated_tokens=int(data.get("estimated_tokens", 0)),
            difficulty=int(data.get("difficulty", 5)),
            priority=int(data.get("priority", 5)),
            claimed_by=data.get("claimed_by", ""),
            test_design=test_design,
            artifacts=artifacts,
            summary=data.get("summary", ""),
            tokens_used=int(data.get("tokens_used", 0)),
            retry_count=int(data.get("retry_count", 0)),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            completed_at=data.get("completed_at", ""),
            interrupted_at=data.get("interrupted_at", ""),
            last_heartbeat=data.get("last_heartbeat", ""),
            # 调度增强字段
            deadline=data.get("deadline", ""),
            # Review 相关字段
            review_result=data.get("review_result", ""),
            reviewed_by=data.get("reviewed_by", ""),
            review_comment=data.get("review_comment", ""),
            reviewed_at=data.get("reviewed_at", ""),
        )
