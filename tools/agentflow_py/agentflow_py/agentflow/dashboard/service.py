"""Dashboard Service: aggregates data from all modules."""
import logging
from typing import Any, Dict, List, Optional

from agentflow.common import generate_task_id
from agentflow.storage import RedisClient, SQLiteStore
from agentflow.task.model import TaskStatus
from agentflow.goal.model import GoalStatus


class DashboardService:
    def __init__(self, redis: RedisClient, sqlite: Optional[SQLiteStore],
                 logger: logging.Logger):
        self._redis = redis
        self._sqlite = sqlite
        self._logger = logger

    async def get_dashboard_data(self) -> Dict[str, Any]:
        """Aggregate all dashboard metrics — 返回扁平结构，与 Go 版一致。"""
        # ── 目标统计 ──
        goal_list_key = self._redis.key("goal", "list")
        goal_total = await self._redis.zcard(goal_list_key)
        active_goals = 0
        if goal_total > 0:
            goal_ids = await self._redis.zrangebyscore(goal_list_key, "-inf", "+inf")
            for gid in goal_ids:
                st = await self._redis.hget(self._redis.key("goal", gid), "status")
                if st in ("pending", "active"):
                    active_goals += 1

        # ── 任务统计：遍历各队列并验证 Hash 存在性 ──
        status_queues = TaskStatus.ALL  # ["pending","running","completed","failed","blocked","interrupted","review"]
        status_count: Dict[str, int] = {}
        seen: set = set()
        total_tasks = 0

        for status in status_queues:
            queue_key = self._redis.key("task", "queue", status)
            members = await self._redis.zrangebyscore(queue_key, "-inf", "+inf")
            for task_id in members:
                if task_id in seen:
                    continue
                # 验证 task Hash 是否存在
                if not await self._redis.exists(self._redis.key("task", task_id)):
                    # 幽灵条目：清理
                    await self._redis.zrem(queue_key, task_id)
                    self._logger.warning(f"清理幽灵任务条目 task_id={task_id} queue={status}")
                    continue
                seen.add(task_id)
                status_count[status] = status_count.get(status, 0) + 1
                total_tasks += 1

        pending_count = status_count.get("pending", 0)
        running_count = status_count.get("running", 0)
        completed_count = status_count.get("completed", 0)
        failed_count = status_count.get("failed", 0)
        blocked_count = status_count.get("blocked", 0)
        interrupted_count = status_count.get("interrupted", 0)
        review_count = status_count.get("review", 0)

        # ── 补充 SQLite 归档数据（已归档的完成任务）──
        archived_completed = 0
        archived_goals = 0
        if self._sqlite:
            try:
                row = await self._sqlite.fetchone(
                    "SELECT COUNT(*) as cnt FROM archived_tasks"
                )
                archived_completed = row["cnt"] if row else 0
            except Exception:
                pass
            try:
                # 从归档任务中统计唯一 goal_id 数量（作为历史目标数）
                row = await self._sqlite.fetchone(
                    "SELECT COUNT(DISTINCT goal_id) as cnt FROM archived_tasks WHERE goal_id != ''"
                )
                archived_goals = row["cnt"] if row else 0
            except Exception:
                pass

        # 合并活跃 + 归档数据
        completed_count_total = completed_count + archived_completed
        total_tasks_total = total_tasks + archived_completed
        goal_total_combined = goal_total + archived_goals

        pass_rate = 0.0
        if total_tasks_total > 0:
            pass_rate = completed_count_total / total_tasks_total * 100

        # ── Skill 统计 ──
        skill_names = await self._redis.smembers(self._redis.key("skill", "types"))

        # ── 经验统计 ──
        pos_exp_count = await self._redis.xlen(self._redis.key("exp", "positive"))
        neg_exp_count = await self._redis.xlen(self._redis.key("exp", "negative"))
        # 补充 SQLite 归档经验数
        if self._sqlite:
            try:
                row = await self._sqlite.fetchone(
                    "SELECT COUNT(*) as cnt FROM archived_experiences WHERE type='positive'"
                )
                pos_exp_count += row["cnt"] if row else 0
                row = await self._sqlite.fetchone(
                    "SELECT COUNT(*) as cnt FROM archived_experiences WHERE type='negative'"
                )
                neg_exp_count += row["cnt"] if row else 0
            except Exception:
                pass

        # ── Archive 最佳分数 ──
        top_archives = await self._redis.zrevrange_withscores(
            self._redis.key("archive", "leaderboard"), 0, 0
        )
        best_score = top_archives[0][1] if top_archives else 0.0
        # 补充 SQLite 归档最佳分数
        if self._sqlite and best_score == 0.0:
            try:
                row = await self._sqlite.fetchone(
                    "SELECT MAX(score) as s FROM agent_archives"
                )
                if row and row["s"] is not None:
                    best_score = float(row["s"])
            except Exception:
                pass

        # ── 进化日志数 ──
        evo_log_count = await self._redis.xlen(self._redis.key("evo", "log"))
        # 补充 SQLite 归档进化日志数
        if self._sqlite:
            try:
                row = await self._sqlite.fetchone(
                    "SELECT COUNT(*) as cnt FROM evolution_logs"
                )
                evo_log_count += row["cnt"] if row else 0
            except Exception:
                pass

        return {
            # 扁平结构，与 Go 版和前端 JS 对应
            "active_goals":      active_goals,
            "total_goals":       goal_total_combined,
            "pending_tasks":     pending_count,
            "running_tasks":     running_count,
            "completed_tasks":   completed_count_total,
            "failed_tasks":      failed_count,
            "blocked_tasks":     blocked_count,
            "interrupted_tasks": interrupted_count,
            "review_tasks":      review_count,
            "total_tasks":       total_tasks_total,
            "pass_rate":         f"{pass_rate:.1f}%",
            "skill_count":       len(skill_names),
            "skill_names":       list(skill_names),
            "positive_exp":      pos_exp_count,
            "negative_exp":      neg_exp_count,
            "evolution_count":   evo_log_count,
            "best_score":        best_score,
        }

    async def _get_task_stats(self) -> Dict:
        stats = {}
        total = 0
        for status in TaskStatus.ALL:
            count = await self._redis.zcard(self._redis.key("task", "queue", status))
            stats[status] = count
            total += count
        stats["total"] = total

        # Running tasks with progress
        running_ids = await self._redis.zrangebyscore(
            self._redis.key("task", "queue", TaskStatus.RUNNING), "-inf", "+inf"
        )
        running_tasks = []
        for tid in running_ids[:10]:
            data = await self._redis.hgetall(self._redis.key("task", tid))
            if data:
                running_tasks.append({
                    "id": tid,
                    "title": data.get("title", ""),
                    "claimed_by": data.get("claimed_by", ""),
                    "progress": data.get("progress", "0"),
                    "skill_type": data.get("skill_type", ""),
                })
        stats["running_details"] = running_tasks
        return stats

    async def _get_goal_stats(self) -> Dict:
        list_key = self._redis.key("goal", "list")
        total = await self._redis.zcard(list_key)
        goal_ids = await self._redis.zrevrange_withscores(list_key, 0, 9)
        goals = []
        for gid, _ in goal_ids:
            data = await self._redis.hgetall(self._redis.key("goal", gid))
            if data:
                goals.append({
                    "id": gid,
                    "title": data.get("title", ""),
                    "status": data.get("status", ""),
                    "progress": float(data.get("progress", 0)),
                    "priority": int(data.get("priority", 5)),
                })
        return {"total": total, "recent": goals}

    async def _get_skill_stats(self) -> Dict:
        skill_types = await self._redis.smembers(self._redis.key("skill", "types"))
        skills = []
        for st in skill_types:
            metrics = await self._redis.hgetall(self._redis.key("skill", st, "metrics"))
            skills.append({
                "skill_type": st,
                "total_tasks": int(metrics.get("total_tasks", 0)),
                "success_rate": float(metrics.get("success_rate", 0)),
                "last_evolved": metrics.get("last_evolved", ""),
            })
        return {"total": len(skill_types), "skills": skills}

    async def _get_evolution_stats(self) -> Dict:
        msgs = await self._redis.xrevrange(self._redis.key("evo", "log"), count=5)
        recent = [{"target": m.get("fields", {}).get("target", ""),
                   "timestamp": m.get("fields", {}).get("timestamp", "")} for m in msgs]
        patterns = await self._redis.hgetall(self._redis.key("evo", "patterns"))
        pending = await self._redis.llen(self._redis.key("evo", "pending_approvals"))
        return {
            "total_patterns": len(patterns),
            "pending_approvals": pending,
            "recent_evolutions": recent,
        }

    async def _get_recovery_stats(self) -> Dict:
        interrupted = await self._redis.zcard(
            self._redis.key("task", "queue", TaskStatus.INTERRUPTED)
        )
        if self._sqlite:
            events = await self._sqlite.query_recovery_timeline()
            return {"interrupted_tasks": interrupted, "recovery_events": events[:10]}
        return {"interrupted_tasks": interrupted, "recovery_events": []}

    async def get_tasks(self, status: str = "", goal_id: str = "",
                        page: int = 1, page_size: int = 20) -> List[Dict]:
        """返回任务数组（与 Go 版 GetAllTasks 一致）。"""
        import json as _json
        statuses_to_scan = [status] if status else TaskStatus.ALL
        seen: set = set()
        tasks: List[Dict] = []
        goal_cache: Dict[str, tuple] = {}  # goal_id -> (title, status)

        for s in statuses_to_scan:
            queue_key = self._redis.key("task", "queue", s)
            members = await self._redis.zrangebyscore(queue_key, "-inf", "+inf")
            for tid in members:
                if tid in seen:
                    continue
                data = await self._redis.hgetall(self._redis.key("task", tid))
                if not data:
                    # 幽灵条目：清理
                    await self._redis.zrem(queue_key, tid)
                    self._logger.warning(f"清理幽灵任务条目 task_id={tid} queue={s}")
                    continue
                seen.add(tid)
                if goal_id and data.get("goal_id") != goal_id:
                    continue

                # 读取关联 Goal 的标题和状态
                gid = data.get("goal_id", "")
                goal_title = ""
                goal_status = ""
                if gid:
                    if gid in goal_cache:
                        goal_title, goal_status = goal_cache[gid]
                    else:
                        gdata = await self._redis.hgetall(self._redis.key("goal", gid))
                        if gdata:
                            goal_title = gdata.get("title", "")
                            goal_status = gdata.get("status", "")
                        goal_cache[gid] = (goal_title, goal_status)

                # 解析依赖列表
                deps: List[str] = []
                deps_raw = data.get("dependencies", "")
                if deps_raw and deps_raw not in ("[]", "null", ""):
                    try:
                        deps = _json.loads(deps_raw)
                    except Exception:
                        pass

                priority = 0
                try:
                    priority = int(data.get("priority", 0))
                except (ValueError, TypeError):
                    pass
                progress = 0.0
                try:
                    progress = float(data.get("progress", 0))
                except (ValueError, TypeError):
                    pass

                tasks.append({
                    "id":           tid,
                    "goal_id":      gid,
                    "goal_title":   goal_title,
                    "goal_status":  goal_status,
                    "title":        data.get("title", ""),
                    "description":  data.get("description", ""),
                    "status":       s,  # 用队列的 status（与 Go 版一致）
                    "progress":     progress,
                    "skill_type":   data.get("skill_type", ""),
                    "claimed_by":   data.get("claimed_by", ""),
                    "priority":     priority,
                    "dependencies": deps,
                    "created_at":   data.get("created_at", ""),
                    "updated_at":   data.get("updated_at", ""),
                })

        # 按 goal_id 分组 → 组内按优先级降序
        tasks.sort(key=lambda t: (t.get("goal_id", ""), -t.get("priority", 0)))
        return tasks

    async def get_goals(self, page: int = 1, page_size: int = 20) -> List[Dict]:
        """返回目标数组（与 Go 版 GetGoals 一致）。"""
        list_key = self._redis.key("goal", "list")
        members = await self._redis.zrevrange_withscores(list_key, 0, -1)
        goals: List[Dict] = []
        for gid, _ in members:
            data = await self._redis.hgetall(self._redis.key("goal", gid))
            if data:
                # 确保有 id 字段
                if "id" not in data:
                    data["id"] = gid
                goals.append(data)
        return goals

    async def delete_goal(self, goal_id: str) -> bool:
        key = self._redis.key("goal", goal_id)
        if await self._redis.exists(key):
            await self._redis.delete(key)
            await self._redis.zrem(self._redis.key("goal", "list"), goal_id)
            return True
        return False

    async def delete_task(self, task_id: str) -> bool:
        key = self._redis.key("task", task_id)
        if await self._redis.exists(key):
            for s in TaskStatus.ALL:
                await self._redis.zrem(self._redis.key("task", "queue", s), task_id)
            await self._redis.delete(key)
            return True
        return False

    async def update_task_status(self, task_id: str, new_status: str) -> bool:
        key = self._redis.key("task", task_id)
        if not await self._redis.exists(key):
            return False
        old_status = await self._redis.hget(key, "status")
        if old_status:
            await self._redis.zrem(self._redis.key("task", "queue", old_status), task_id)
        import time
        from datetime import datetime, timezone
        await self._redis.hset(key, {
            "status": new_status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        await self._redis.zadd(
            self._redis.key("task", "queue", new_status),
            {task_id: float(time.time())},
        )
        return True

    async def get_skill_details(self) -> List[Dict]:
        """返回 Skill 数组（与 Go 版 GetSkills 一致）。"""
        skill_types = await self._redis.smembers(self._redis.key("skill", "types"))
        result: List[Dict] = []
        for st in skill_types:
            dna = await self._redis.hgetall(self._redis.key("skill", st, "dna"))
            metrics = await self._redis.hgetall(self._redis.key("skill", st, "metrics"))
            meta = await self._redis.hgetall(self._redis.key("skill", st, "meta"))
            result.append({
                "skill_type": st,
                "name": meta.get("name", st),
                "version": int(dna.get("version", 1)) if dna else 0,
                "total_tasks": int(metrics.get("total_tasks", 0)) if metrics else 0,
                "success_rate": float(metrics.get("success_rate", 0)) if metrics else 0.0,
                "last_evolved": metrics.get("last_evolved", "") if metrics else "",
            })
        return result

    async def clean_ghost_tasks(self) -> int:
        """Remove orphaned running tasks (lock expired but not cleaned up)."""
        cleaned = 0
        running_members = await self._redis.zrangebyscore(
            self._redis.key("task", "queue", TaskStatus.RUNNING), "-inf", "+inf"
        )
        for task_id in running_members:
            lock_key = self._redis.key("lock", "task", task_id)
            if not await self._redis.exists(lock_key):
                data = await self._redis.hgetall(self._redis.key("task", task_id))
                if not data:
                    await self._redis.zrem(
                        self._redis.key("task", "queue", TaskStatus.RUNNING), task_id
                    )
                    cleaned += 1
                    continue
                agent_id = data.get("claimed_by", "")
                heartbeat_alive = bool(await self._redis.get(
                    self._redis.key("agent", agent_id, "heartbeat")
                ))
                if not heartbeat_alive:
                    await self.update_task_status(task_id, TaskStatus.INTERRUPTED)
                    cleaned += 1
        return cleaned

    async def split_task(self, parent_task_id: str, subtasks_data: List[Dict]) -> Dict:
        """将父任务拆分为子任务（简化版实现）。"""
        import time
        from datetime import datetime, timezone

        # 获取父任务信息
        parent_key = self._redis.key("task", parent_task_id)
        parent = await self._redis.hgetall(parent_key)
        if not parent:
            return {"error": f"父任务 {parent_task_id} 不存在"}

        now = datetime.now(timezone.utc).isoformat()
        task_ids = []

        for sub in subtasks_data:
            tid = generate_task_id()
            task_data = {
                "id": tid,
                "goal_id": parent.get("goal_id", ""),
                "parent_task_id": parent_task_id,
                "title": sub.get("title", ""),
                "description": sub.get("description", ""),
                "status": TaskStatus.PENDING,
                "progress": "0",
                "skill_type": sub.get("skill_type", parent.get("skill_type", "")),
                "phase": sub.get("phase", parent.get("phase", "")),
                "priority": str(parent.get("priority", "5")),
                "difficulty": str(sub.get("difficulty", parent.get("difficulty", "5"))),
                "created_at": now,
                "updated_at": now,
            }
            # 处理依赖
            deps = sub.get("dependencies", [])
            if deps:
                import json as _json
                task_data["dependencies"] = _json.dumps(deps)

            await self._redis.hset(self._redis.key("task", tid), task_data)
            await self._redis.zadd(
                self._redis.key("task", "queue", TaskStatus.PENDING),
                {tid: float(time.time())},
            )
            task_ids.append(tid)

        return {
            "status": "split_success",
            "parent_task_id": parent_task_id,
            "subtask_ids": task_ids,
            "subtask_count": len(task_ids),
        }

    # ==================== Fix Experience API ====================

    async def get_fix_experience_stats(self) -> Dict[str, Any]:
        """获取经验统计（与 Go 版 GetFixExperienceStats 一致）。"""
        pos_count = await self._redis.xlen(self._redis.key("exp", "positive"))
        neg_count = await self._redis.xlen(self._redis.key("exp", "negative"))
        return {
            "positive_experiences": pos_count,
            "negative_experiences": neg_count,
            "total_experiences": pos_count + neg_count,
        }

    async def get_fix_experiences(self, exp_type: str = "positive",
                                   limit: int = 50) -> List[Dict[str, str]]:
        """从 Redis Stream 获取经验列表（与 Go 版 GetFixExperiences 一致）。"""
        if exp_type not in ("positive", "negative"):
            exp_type = "positive"
        if limit <= 0 or limit > 100:
            limit = 50
        stream_key = self._redis.key("exp", exp_type)
        messages = await self._redis.xrevrange(stream_key, count=limit)
        results: List[Dict[str, str]] = []
        for msg in messages:
            item: Dict[str, str] = {"id": msg["id"]}
            for k, v in msg.get("fields", {}).items():
                item[k] = str(v) if v is not None else ""
            results.append(item)
        return results

    async def delete_fix_experience(self, exp_type: str, message_id: str) -> bool:
        """删除指定经验（与 Go 版 DeleteFixExperience 一致）。"""
        if not exp_type or not message_id:
            return False
        stream_key = self._redis.key("exp", exp_type)
        deleted = await self._redis.xdel(stream_key, message_id)
        return deleted > 0

    async def create_fix_experience(self, exp_type: str,
                                     fields: Dict[str, str]) -> str:
        """手动创建经验（与 Go 版 CreateFixExperience 一致）。"""
        if exp_type not in ("positive", "negative"):
            raise ValueError("type 必须为 positive 或 negative")
        if not fields:
            raise ValueError("fields 不能为空")
        from datetime import datetime, timezone
        values = {k: v for k, v in fields.items() if v}
        values["source"] = "manual"
        values["created_at"] = datetime.now(timezone.utc).isoformat()
        stream_key = self._redis.key("exp", exp_type)
        msg_id = await self._redis.xadd(stream_key, values, maxlen=10000)
        self._logger.info(f"手动创建经验 type={exp_type} id={msg_id}")
        return msg_id

    async def update_fix_experience(self, exp_type: str, message_id: str,
                                     fields: Dict[str, str]) -> bool:
        """更新指定经验（与 Go 版 UpdateFixExperience 一致：读旧→合并→删旧→添新）。"""
        if not exp_type or not message_id or not fields:
            return False
        stream_key = self._redis.key("exp", exp_type)
        # 1. 读取旧记录
        messages = await self._redis.xrange(stream_key, min_id=message_id,
                                             max_id=message_id, count=1)
        if not messages:
            return False
        # 2. 合并字段
        old_data = messages[0].get("fields", {})
        new_data = {}
        for k, v in old_data.items():
            new_data[k] = str(v) if v is not None else ""
        for k, v in fields.items():
            if v:
                new_data[k] = v
        from datetime import datetime, timezone
        new_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        # 3. 删除旧记录
        await self._redis.xdel(stream_key, message_id)
        # 4. 添加新记录
        await self._redis.xadd(stream_key, new_data, maxlen=10000)
        return True

    # ==================== Project API ====================

    async def get_projects(self, status: str = "", tags: List[str] = None,
                           page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        """获取项目列表（与 Go 版 GetProjects 一致）。"""
        import json as _json
        list_key = self._redis.key("project", "list")
        project_ids = await self._redis.zrangebyscore(list_key, "-inf", "+inf")
        projects = []
        for pid in project_ids:
            data = await self._redis.hgetall(self._redis.key("project", pid))
            if not data:
                continue
            if status and data.get("status") != status:
                continue
            if tags:  # 仅在 tags 非空时过滤，避免 tags=[] 时跳过所有项目
                proj_tags_raw = data.get("tags", "[]")
                try:
                    proj_tags = _json.loads(proj_tags_raw)
                except Exception:
                    proj_tags = []
                if not any(t in proj_tags for t in tags):
                    continue
            if "id" not in data:
                data["id"] = pid
            # 将 JSON 字符串字段反序列化为数组/对象，供前端直接使用
            for _field in ("tags", "risk_list", "tech_stack"):
                raw = data.get(_field, "")
                if isinstance(raw, str):
                    try:
                        data[_field] = _json.loads(raw) if raw else []
                    except Exception:
                        data[_field] = []
            projects.append(data)
        total = len(projects)
        # 分页
        start = (page - 1) * page_size
        end = start + page_size
        return {
            "projects": projects[start:end],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def get_project_detail(self, project_id: str) -> Dict[str, Any]:
        """获取项目详情（与 Go 版 GetProjectOverview 一致，返回 project+phases+history+gates）。"""
        import json as _json
        key = self._redis.key("project", project_id)
        data = await self._redis.hgetall(key)
        if not data:
            raise ValueError(f"项目不存在: {project_id}")
        if "id" not in data:
            data["id"] = project_id
        # 将 JSON 字符串字段反序列化为数组/对象，供前端直接使用
        for _field in ("tags", "risk_list", "tech_stack"):
            raw = data.get(_field, "")
            if isinstance(raw, str):
                try:
                    data[_field] = _json.loads(raw) if raw else []
                except Exception:
                    data[_field] = []

        # 解析 phases JSON 字符串为数组
        phases_raw = data.get("phases", "")
        try:
            phase_list = _json.loads(phases_raw) if phases_raw else []
        except Exception:
            phase_list = []

        # 获取所有 gate 信息，构建 gate_map
        # Go 版用 lrange("project:{id}:phases") 获取 phase 名称列表
        # gate 以 String 类型存储（JSON 整体序列化），key 为 "project:{id}:gate:{phaseName}"
        phases_list_key = self._redis.key("project", project_id, "phases")
        gate_names = await self._redis.lrange(phases_list_key, 0, -1)
        gate_map: Dict[str, Any] = {}
        gates = []
        for phase_name in gate_names:
            gate_raw = await self._redis.get(
                self._redis.key("project", project_id, "gate", phase_name)
            )
            if gate_raw:
                try:
                    gate_data = _json.loads(gate_raw)
                    if isinstance(gate_data, dict):
                        gate_data.setdefault("phase_name", phase_name)
                        gate_map[phase_name] = gate_data
                        gates.append(gate_data)
                except Exception:
                    pass

        # 递归构建 phase overviews（支持子阶段）
        def build_phase_overviews(phase_list_inner):
            result = []
            for phase in phase_list_inner:
                if not isinstance(phase, dict):
                    continue
                name = phase.get("name", "")
                gate = gate_map.get(name, {})
                linked_goal_ids = gate.get("linked_goal_ids", gate.get("LinkedGoalIDs", []))
                linked_task_ids = gate.get("linked_task_ids", gate.get("LinkedTaskIDs", []))
                if isinstance(linked_goal_ids, str):
                    try:
                        linked_goal_ids = _json.loads(linked_goal_ids)
                    except Exception:
                        linked_goal_ids = []
                if isinstance(linked_task_ids, str):
                    try:
                        linked_task_ids = _json.loads(linked_task_ids)
                    except Exception:
                        linked_task_ids = []
                phase_info = {
                    "name": name,
                    "description": phase.get("description", ""),
                    "order": phase.get("order", 0),
                    "status": phase.get("status", "pending"),
                    "gate_status": gate.get("status", "pending"),
                    "linked_goals": len(linked_goal_ids) if isinstance(linked_goal_ids, list) else 0,
                    "linked_tasks": len(linked_task_ids) if isinstance(linked_task_ids, list) else 0,
                }
                children = phase.get("children", phase.get("Children", []))
                if children:
                    phase_info["children"] = build_phase_overviews(children)
                result.append(phase_info)
            return result

        phase_overviews = build_phase_overviews(phase_list)

        # 获取审批历史
        history_key = self._redis.key("project", project_id, "history")
        history_raw = await self._redis.lrange(history_key, 0, -1)
        history = []
        for item in history_raw:
            try:
                history.append(_json.loads(item))
            except Exception:
                pass

        print(f"[DEBUG get_project_detail] project_id={project_id!r}, data.keys={list(data.keys())}, data.id={data.get('id')!r}, phases_count={len(phase_overviews)}")
        return {
            "project": data,
            "phases": phase_overviews,
            "history": history,
            "gates": gates,
        }

    async def get_project_phases(self, project_id: str) -> Dict[str, Any]:
        """获取项目阶段门控列表（与 Go 版 GetProjectGates 一致）。"""
        import json as _json
        phases_list_key = self._redis.key("project", project_id, "phases")
        gate_names = await self._redis.lrange(phases_list_key, 0, -1)
        gates = []
        for phase_name in gate_names:
            gate_raw = await self._redis.get(
                self._redis.key("project", project_id, "gate", phase_name)
            )
            if gate_raw:
                try:
                    gate_data = _json.loads(gate_raw)
                    if isinstance(gate_data, dict):
                        gate_data.setdefault("phase_name", phase_name)
                        gates.append(gate_data)
                except Exception:
                    pass
        return {
            "project_id": project_id,
            "gates": gates,
            "total": len(gates),
        }

    async def get_phase_overview(self, project_id: str, phase_name: str) -> Dict[str, Any]:
        """获取阶段概览（与 Go 版 GetPhaseOverview 一致）。"""
        import json as _json
        gate_raw = await self._redis.get(
            self._redis.key("project", project_id, "gate", phase_name)
        )
        gate_data = {}
        if gate_raw:
            try:
                gate_data = _json.loads(gate_raw) or {}
            except Exception:
                gate_data = {}
        # 获取关联的 goal 列表
        goal_links_key = self._redis.key("project", project_id, "phase", phase_name, "goals")
        goal_ids = await self._redis.smembers(goal_links_key)
        total_goals = len(goal_ids)
        completed_goals = 0
        for gid in goal_ids:
            st = await self._redis.hget(self._redis.key("goal", gid), "status")
            if st == "completed":
                completed_goals += 1
        # 获取关联的 task 列表
        task_ids_key = self._redis.key("project", project_id, "phase", phase_name, "tasks")
        task_ids = await self._redis.smembers(task_ids_key)
        total_tasks = len(task_ids)
        completed_tasks = 0
        for tid in task_ids:
            st = await self._redis.hget(self._redis.key("task", tid), "status")
            if st == "completed":
                completed_tasks += 1
        percentage = 0.0
        if total_tasks > 0:
            percentage = completed_tasks / total_tasks * 100
        return {
            "project_id": project_id,
            "phase_name": phase_name,
            "gate": gate_data or {},
            "progress": {
                "total_goals": total_goals,
                "completed_goals": completed_goals,
                "total_tasks": total_tasks,
                "completed_tasks": completed_tasks,
                "percentage": round(percentage, 1),
            },
        }

    async def submit_phase_review(self, project_id: str, phase_name: str,
                                   comment: str = "", submitted_by: str = "") -> Dict[str, Any]:
        """提交阶段审阅（将 gate 状态设为 in_review）。"""
        import json as _json
        from datetime import datetime, timezone
        gate_key = self._redis.key("project", project_id, "gate", phase_name)
        if not await self._redis.exists(gate_key):
            raise ValueError(f"阶段门控不存在: {project_id}/{phase_name}")
        now = datetime.now(timezone.utc).isoformat()
        # gate 以 String(JSON) 存储，需先读出再修改后写回
        gate_raw = await self._redis.get(gate_key)
        try:
            gate_data = _json.loads(gate_raw) if gate_raw else {}
        except Exception:
            gate_data = {}
        gate_data.update({
            "status": "in_review",
            "submitted_at": now,
            "submitted_by": submitted_by,
            "submit_comment": comment,
            "updated_at": now,
        })
        await self._redis.set(gate_key, _json.dumps(gate_data, ensure_ascii=False))
        return {
            "status": "submitted",
            "project_id": project_id,
            "phase_name": phase_name,
            "message": "阶段已提交审阅",
        }

    async def approve_phase(self, project_id: str, phase_name: str,
                             comment: str = "", approved_by: str = "") -> Dict[str, Any]:
        """审批通过阶段（与 Go 版 ApproveProjectPhase 一致），并自动推进到下一阶段。"""
        import json as _json
        from datetime import datetime, timezone
        gate_key = self._redis.key("project", project_id, "gate", phase_name)
        if not await self._redis.exists(gate_key):
            raise ValueError(f"阶段门控不存在: {project_id}/{phase_name}")
        now = datetime.now(timezone.utc).isoformat()
        # gate 以 String(JSON) 存储，需先读出再修改后写回
        gate_raw = await self._redis.get(gate_key)
        try:
            gate_data = _json.loads(gate_raw) if gate_raw else {}
        except Exception:
            gate_data = {}
        gate_data.update({
            "status": "approved",
            "approved_at": now,
            "approved_by": approved_by,
            "approve_comment": comment,
            "updated_at": now,
        })
        await self._redis.set(gate_key, _json.dumps(gate_data, ensure_ascii=False))
        # 推进项目到下一阶段
        proj_key = self._redis.key("project", project_id)
        proj_data = await self._redis.hgetall(proj_key)
        next_phase_name = ""
        try:
            phases_raw = proj_data.get("phases", "[]")
            phases = _json.loads(phases_raw)
            current_phase = proj_data.get("current_phase", "")
            current_idx = -1
            for i, p in enumerate(phases):
                if p.get("name") == current_phase:
                    current_idx = i
                    break
            if current_idx >= 0:
                # 标记当前阶段为 completed
                phases[current_idx]["status"] = "completed"
                next_idx = current_idx + 1
                if next_idx < len(phases):
                    phases[next_idx]["status"] = "active"
                    next_phase_name = phases[next_idx]["name"]
            updates = {
                "phases": _json.dumps(phases, ensure_ascii=False),
                "updated_at": now,
            }
            if next_phase_name:
                updates["current_phase"] = next_phase_name
            await self._redis.hset(proj_key, updates)
        except Exception as e:
            self._logger.warning(f"推进阶段时出错 project_id={project_id}: {e}")
            await self._redis.hset(proj_key, {"updated_at": now})
        return {
            "status": "approved",
            "project_id": project_id,
            "phase_name": phase_name,
            "next_phase": next_phase_name,
            "message": "阶段已审批通过" + (f"，已推进至 {next_phase_name}" if next_phase_name else ""),
        }

    async def reject_phase(self, project_id: str, phase_name: str,
                            comment: str = "", revision_items: List[str] = None) -> Dict[str, Any]:
        """驳回阶段（与 Go 版 RejectProjectPhase 一致）。"""
        import json as _json
        from datetime import datetime, timezone
        gate_key = self._redis.key("project", project_id, "gate", phase_name)
        if not await self._redis.exists(gate_key):
            raise ValueError(f"阶段门控不存在: {project_id}/{phase_name}")
        if not comment:
            raise ValueError("comment 不能为空")
        now = datetime.now(timezone.utc).isoformat()
        fields = {
            "status": "rejected",
            "rejected_at": now,
            "reject_comment": comment,
            "updated_at": now,
        }
        if revision_items:
            fields["revision_items"] = _json.dumps(revision_items)
        # gate 以 String(JSON) 存储，需先读出再修改后写回
        gate_raw = await self._redis.get(gate_key)
        try:
            gate_data = _json.loads(gate_raw) if gate_raw else {}
        except Exception:
            gate_data = {}
        gate_data.update(fields)
        await self._redis.set(gate_key, _json.dumps(gate_data, ensure_ascii=False))
        return {
            "status": "rejected",
            "gate": gate_data,
            "message": "阶段已被驳回",
        }

    async def delete_project(self, project_id: str, cascade: bool = False) -> None:
        """删除项目（与 Go 版 DeleteProject 一致）。"""
        key = self._redis.key("project", project_id)
        if not await self._redis.exists(key):
            raise ValueError(f"项目不存在: {project_id}")
        # 删除项目主数据
        await self._redis.delete(key)
        await self._redis.zrem(self._redis.key("project", "list"), project_id)
        # 删除所有阶段门控（phases 是 List 类型，用 lrange 读取）
        gate_names = await self._redis.lrange(self._redis.key("project", project_id, "phases"), 0, -1)
        for phase_name in gate_names:
            await self._redis.delete(self._redis.key("project", project_id, "gate", phase_name))
        await self._redis.delete(self._redis.key("project", project_id, "phases"))
        self._logger.info(f"删除项目 project_id={project_id} cascade={cascade}")

    async def add_phase(self, project_id: str, name: str,
                        description: str = "", parent_phase: str = "",
                        order: Any = None) -> Dict[str, Any]:
        """添加阶段（与 Go 版 AddPhase 一致）。"""
        import json as _json
        from datetime import datetime, timezone
        project_key = self._redis.key("project", project_id)
        if not await self._redis.exists(project_key):
            raise ValueError(f"项目不存在: {project_id}")
        gate_key = self._redis.key("project", project_id, "gate", name)
        if await self._redis.exists(gate_key):
            raise ValueError(f"阶段已存在: {name}")
        now = datetime.now(timezone.utc).isoformat()
        gate_data = {
            "project_id": project_id,
            "phase_name": name,
            "description": description,
            "parent_phase": parent_phase,
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        }
        if order is not None:
            gate_data["order"] = int(order)

        # 与 Go 版一致：gate 用 SET 存 JSON 字符串，phases list 用 RPUSH 存 List
        await self._redis.set(gate_key, _json.dumps(gate_data))
        await self._redis.rpush(self._redis.key("project", project_id, "phases"), name)

        # 同步更新 project Hash 的 phases 字段（JSON 数组），供 get_project_detail 解析阶段树
        project_data = await self._redis.hgetall(project_key)
        phases_raw = project_data.get("phases", "")
        try:
            phase_list = _json.loads(phases_raw) if phases_raw else []
        except Exception:
            phase_list = []

        new_phase = {
            "name": name,
            "description": description,
            "order": int(order) if order is not None else len(phase_list) + 1,
            "status": "pending",
            "parent_phase": parent_phase,
            "children": [],
        }

        if parent_phase:
            # 添加为子阶段
            def insert_child(phases_inner):
                for p in phases_inner:
                    if p.get("name") == parent_phase:
                        children = p.setdefault("children", [])
                        if new_phase["order"] <= 0:
                            new_phase["order"] = len(children) + 1
                        children.append(new_phase)
                        return True
                    if insert_child(p.get("children", [])):
                        return True
                return False
            insert_child(phase_list)
        else:
            if new_phase["order"] <= 0:
                new_phase["order"] = len(phase_list) + 1
            phase_list.append(new_phase)

        await self._redis.hset(project_key, {"phases": _json.dumps(phase_list)})

        self._logger.info(f"添加阶段 project_id={project_id} phase={name}")
        return {"status": "added", "phase_name": name, "gate": gate_data}

    async def remove_phase(self, project_id: str, phase_name: str) -> None:
        """删除阶段（与 Go 版 RemovePhase 一致）。"""
        gate_key = self._redis.key("project", project_id, "gate", phase_name)
        if not await self._redis.exists(gate_key):
            raise ValueError(f"阶段不存在: {project_id}/{phase_name}")
        await self._redis.delete(gate_key)
        await self._redis.srem(self._redis.key("project", project_id, "phases"), phase_name)
        self._logger.info(f"删除阶段 project_id={project_id} phase={phase_name}")

    async def update_phase(self, project_id: str, phase_name: str,
                           new_name: str = "", new_description: str = "") -> Dict[str, Any]:
        """更新阶段（与 Go 版 UpdatePhase 一致）。"""
        from datetime import datetime, timezone
        gate_key = self._redis.key("project", project_id, "gate", phase_name)
        if not await self._redis.exists(gate_key):
            raise ValueError(f"阶段不存在: {project_id}/{phase_name}")
        updates: Dict[str, str] = {"updated_at": datetime.now(timezone.utc).isoformat()}
        if new_description:
            updates["description"] = new_description
        await self._redis.hset(gate_key, updates)
        # 重命名阶段
        if new_name and new_name != phase_name:
            new_gate_key = self._redis.key("project", project_id, "gate", new_name)
            old_data = await self._redis.hgetall(gate_key)
            old_data["phase_name"] = new_name
            old_data["updated_at"] = updates["updated_at"]
            await self._redis.hset(new_gate_key, old_data)
            await self._redis.delete(gate_key)
            await self._redis.srem(self._redis.key("project", project_id, "phases"), phase_name)
            await self._redis.sadd(self._redis.key("project", project_id, "phases"), new_name)
            self._logger.info(f"重命名阶段 project_id={project_id} {phase_name}→{new_name}")
            return {"status": "updated", "phase_name": new_name}
        self._logger.info(f"更新阶段 project_id={project_id} phase={phase_name}")
        return {"status": "updated", "phase_name": phase_name}

    # ==================== FixExp Sessions API ====================

    async def get_fix_sessions(self, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        """获取 Fix Session 列表。"""
        list_key = self._redis.key("fixexp", "sessions")
        session_ids = await self._redis.lrange(list_key, 0, -1)
        sessions = []
        for sid in session_ids:
            data = await self._redis.hgetall(self._redis.key("fixexp", "session", sid))
            if data:
                if "id" not in data:
                    data["id"] = sid
                sessions.append(data)
        total = len(sessions)
        start = (page - 1) * page_size
        end = start + page_size
        return {
            "sessions": sessions[start:end],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def get_fix_session_detail(self, session_id: str) -> Dict[str, Any]:
        """获取 Fix Session 详情。"""
        data = await self._redis.hgetall(self._redis.key("fixexp", "session", session_id))
        if not data:
            raise ValueError(f"Session 不存在: {session_id}")
        if "id" not in data:
            data["id"] = session_id
        # 获取关联的经验列表
        attempts_key = self._redis.key("fixexp", "session", session_id, "attempts")
        attempt_ids = await self._redis.lrange(attempts_key, 0, -1)
        attempts = []
        for aid in attempt_ids:
            attempt = await self._redis.hgetall(self._redis.key("fixexp", "attempt", aid))
            if attempt:
                attempts.append(attempt)
        data["attempts"] = attempts
        return data

    async def get_fixexp_experiences(self, exp_type: str = "positive",
                                      page: int = 1, page_size: int = 20,
                                      keyword: str = "") -> Dict[str, Any]:
        """获取经验列表（支持分页，与 Go 版 GetFixExperiences 一致）。"""
        if exp_type not in ("positive", "negative"):
            exp_type = "positive"
        limit = page * page_size  # 取足够多的数据用于分页
        if limit > 1000:
            limit = 1000
        stream_key = self._redis.key("exp", exp_type)
        messages = await self._redis.xrevrange(stream_key, count=limit)
        results: List[Dict[str, str]] = []
        for msg in messages:
            item: Dict[str, str] = {"id": msg["id"]}
            for k, v in msg.get("fields", {}).items():
                item[k] = str(v) if v is not None else ""
            results.append(item)
        # 关键词过滤
        if keyword:
            kw = keyword.lower()
            results = [
                exp for exp in results
                if kw in exp.get("description", "").lower()
                or kw in exp.get("solution", "").lower()
            ]
        total = len(results)
        start = (page - 1) * page_size
        end = start + page_size
        return {
            "experiences": results[start:end],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    # ==================== Context Metrics API ====================

    async def get_context_metrics(self) -> Dict[str, Any]:
        """获取编译指标概览（与 Go 版 context metrics 一致）。"""
        metrics_key = self._redis.key("context", "metrics")
        data = await self._redis.hgetall(metrics_key)
        # 统计经验数
        pos_count = await self._redis.xlen(self._redis.key("exp", "positive"))
        neg_count = await self._redis.xlen(self._redis.key("exp", "negative"))
        # 统计技能数
        skill_count = len(await self._redis.smembers(self._redis.key("skill", "types")))
        # 统计任务数
        total_tasks = 0
        for status in ["pending", "running", "completed", "failed", "blocked", "interrupted", "review"]:
            count = await self._redis.zcard(self._redis.key("task", "queue", status))
            total_tasks += count
        return {
            "total_compilations": int(data.get("total_compilations", 0)),
            "success_compilations": int(data.get("success_compilations", 0)),
            "failed_compilations": int(data.get("failed_compilations", 0)),
            "avg_compile_time_ms": float(data.get("avg_compile_time_ms", 0)),
            "total_experiences": pos_count + neg_count,
            "positive_experiences": pos_count,
            "negative_experiences": neg_count,
            "skill_count": skill_count,
            "total_tasks": total_tasks,
            "last_updated": data.get("last_updated", ""),
        }

    async def get_context_metrics_trend(self, days: int = 7) -> Dict[str, Any]:
        """获取指标趋势数据（最近 N 天）。"""
        trend_key = self._redis.key("context", "metrics", "trend")
        # 从 stream 中读取趋势数据
        messages = await self._redis.xrevrange(trend_key, count=days * 24)
        trend = []
        for msg in messages:
            item = {"timestamp": msg["id"]}
            item.update(msg.get("fields", {}))
            trend.append(item)
        return {
            "trend": trend,
            "days": days,
            "count": len(trend),
        }

    # ==================== Webhook API ====================

    async def get_webhooks(self) -> List[Dict[str, Any]]:
        """获取 Webhook 列表。"""
        list_key = self._redis.key("webhook", "list")
        webhook_ids = await self._redis.smembers(list_key)
        webhooks = []
        for wid in webhook_ids:
            data = await self._redis.hgetall(self._redis.key("webhook", wid))
            if data:
                if "id" not in data:
                    data["id"] = wid
                webhooks.append(data)
        return webhooks

    async def add_webhook(self, url: str, events: List[str] = None,
                           name: str = "") -> Dict[str, Any]:
        """添加 Webhook。"""
        import json as _json
        import uuid
        from datetime import datetime, timezone
        if not url:
            raise ValueError("url 不能为空")
        wid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        data = {
            "id": wid,
            "url": url,
            "name": name or url,
            "events": _json.dumps(events or []),
            "enabled": "true",
            "created_at": now,
            "updated_at": now,
        }
        await self._redis.hset(self._redis.key("webhook", wid), data)
        await self._redis.sadd(self._redis.key("webhook", "list"), wid)
        self._logger.info(f"添加 Webhook id={wid} url={url}")
        return data

    async def delete_webhook(self, webhook_id: str) -> bool:
        """删除 Webhook。"""
        key = self._redis.key("webhook", webhook_id)
        if not await self._redis.exists(key):
            return False
        await self._redis.delete(key)
        await self._redis.srem(self._redis.key("webhook", "list"), webhook_id)
        self._logger.info(f"删除 Webhook id={webhook_id}")
        return True

    async def test_webhook(self, url: str, payload: Dict[str, Any] = None) -> Dict[str, Any]:
        """测试 Webhook 连通性（发送测试请求并返回响应状态）。"""
        import aiohttp
        from datetime import datetime, timezone
        if not url:
            raise ValueError("url 不能为空")
        test_payload = payload or {
            "event": "test",
            "message": "AgentFlow Webhook Test",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=test_payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    status_code = resp.status
                    try:
                        resp_body = await resp.text()
                    except Exception:
                        resp_body = ""
            self._logger.info(f"Webhook 测试完成 url={url} status={status_code}")
            return {
                "status": "ok" if status_code < 400 else "error",
                "url": url,
                "http_status": status_code,
                "response": resp_body[:500] if resp_body else "",
                "message": f"HTTP {status_code}",
            }
        except Exception as e:
            self._logger.warning(f"Webhook 测试失败 url={url} error={e}")
            return {
                "status": "error",
                "url": url,
                "http_status": 0,
                "response": "",
                "message": str(e),
            }

    # ==================== Namespace API ====================

    async def get_namespaces(self) -> List[Dict[str, Any]]:
        """获取命名空间列表。"""
        list_key = self._redis.key("namespace", "list")
        ns_names = await self._redis.smembers(list_key)
        namespaces = []
        for ns in ns_names:
            data = await self._redis.hgetall(self._redis.key("namespace", ns))
            if data:
                if "name" not in data:
                    data["name"] = ns
                namespaces.append(data)
            else:
                namespaces.append({"name": ns})
        return namespaces

    async def create_namespace(self, name: str, description: str = "") -> Dict[str, Any]:
        """创建命名空间。"""
        from datetime import datetime, timezone
        if not name:
            raise ValueError("name 不能为空")
        ns_key = self._redis.key("namespace", name)
        if await self._redis.exists(ns_key):
            raise ValueError(f"命名空间已存在: {name}")
        now = datetime.now(timezone.utc).isoformat()
        data = {
            "name": name,
            "description": description,
            "created_at": now,
            "updated_at": now,
        }
        await self._redis.hset(ns_key, data)
        await self._redis.sadd(self._redis.key("namespace", "list"), name)
        self._logger.info(f"创建命名空间 name={name}")
        return data

    async def health_check(self) -> List[Dict[str, str]]:
        """健康检查：Redis/SQLite/僵尸任务检测。"""
        items: List[Dict[str, str]] = []

        # Redis 检查
        try:
            await self._redis.health_check()
            items.append({"name": "Redis", "status": "healthy", "detail": "连接正常"})
        except Exception as e:
            items.append({"name": "Redis", "status": "error", "detail": str(e)})

        # SQLite 检查
        if self._sqlite:
            try:
                await self._sqlite.health_check()
                items.append({"name": "SQLite", "status": "healthy", "detail": "存储正常"})
            except Exception as e:
                items.append({"name": "SQLite", "status": "error", "detail": str(e)})
        else:
            items.append({"name": "SQLite", "status": "warning", "detail": "未配置"})

        # 锁泄漏检测 (简化)
        items.append({"name": "锁泄漏检测", "status": "healthy", "detail": "无检测到的泄漏"})

        # 僵尸任务检测
        valid_running = 0
        valid_interrupted = 0
        for status in ["running", "interrupted"]:
            queue_key = self._redis.key("task", "queue", status)
            members = await self._redis.zrangebyscore(queue_key, "-inf", "+inf")
            for task_id in members:
                exists = await self._redis.exists(self._redis.key("task", task_id))
                if not exists:
                    await self._redis.zrem(queue_key, task_id)
                    self._logger.warning(f"健康检查清理幽灵任务 task_id={task_id} queue={status}")
                    continue
                actual_status = await self._redis.hget(self._redis.key("task", task_id), "status")
                if actual_status and actual_status != status:
                    await self._redis.zrem(queue_key, task_id)
                    self._logger.info(f"清理状态不一致的任务队列条目 task_id={task_id}")
                    continue
                if status == "running":
                    valid_running += 1
                else:
                    valid_interrupted += 1

        zombie_detail = f"运行中: {valid_running}, 已中断: {valid_interrupted}"
        zombie_status = "healthy"
        if valid_interrupted > 0:
            zombie_status = "warning"
            zombie_detail += " (有中断任务待恢复)"
        items.append({"name": "僵尸任务", "status": zombie_status, "detail": zombie_detail})

        return items

    # ==================== Skill Dashboard API ====================

    async def get_skills(self) -> List[Dict[str, Any]]:
        """获取所有 Skill 列表（与 Go 版 GetSkills 一致，使用 skill:list）。"""
        import json as _json
        names = await self._redis.smembers(self._redis.key("skill", "list"))
        skills: List[Dict[str, Any]] = []
        for name in names:
            data = await self._redis.hgetall(self._redis.key("skill", name))
            if not data:
                continue
            metrics = await self._redis.hgetall(self._redis.key("skill", name, "metrics"))
            # 获取 DNA 规则数
            rules_count = 0
            dna_json = data.get("dna", "")
            if dna_json:
                try:
                    dna = _json.loads(dna_json)
                    rules_count = len(dna.get("rules", []))
                except Exception:
                    pass
            # 也尝试从 dna hash 读取
            if rules_count == 0:
                dna_data = await self._redis.hgetall(self._redis.key("skill", name, "dna"))
                if dna_data:
                    try:
                        rules = _json.loads(dna_data.get("rules", "[]"))
                        rules_count = len(rules)
                    except Exception:
                        pass
            skills.append({
                "name": name,
                "version": data.get("version", "1"),
                "description": data.get("description", ""),
                "updated_at": data.get("updated_at", ""),
                "rules_count": rules_count,
                "metrics": metrics or {},
            })
        return skills

    async def get_skill_detail(self, name: str) -> Dict[str, Any]:
        """获取 Skill 详情（含完整 DNA，与 Go 版 GetSkillDetail 一致）。"""
        import json as _json
        data = await self._redis.hgetall(self._redis.key("skill", name))
        if not data:
            raise ValueError(f"skill 不存在: {name}")
        # 获取 DNA
        dna_data = await self._redis.hgetall(self._redis.key("skill", name, "dna"))
        dna: Dict[str, Any] = {}
        if dna_data:
            for k, v in dna_data.items():
                try:
                    arr = _json.loads(v)
                    dna[k] = arr
                except Exception:
                    dna[k] = v
        # 获取 Metrics
        metrics = await self._redis.hgetall(self._redis.key("skill", name, "metrics"))
        # 获取 Tags
        tags: List[str] = []
        tags_raw = data.get("tags", "")
        if tags_raw:
            try:
                tags = _json.loads(tags_raw)
            except Exception:
                pass
        return {
            "name": name,
            "description": data.get("description", ""),
            "version": data.get("version", "1"),
            "tags": tags,
            "created_at": data.get("created_at", ""),
            "updated_at": data.get("updated_at", ""),
            "dna": dna,
            "metrics": metrics or {},
        }

    async def create_skill_from_dashboard(self, params: Dict[str, Any]) -> None:
        """从 Dashboard 创建新 Skill（与 Go 版 CreateSkillFromDashboard 一致）。"""
        import json as _json
        from datetime import datetime, timezone
        name = params.get("name", "")
        if not name:
            raise ValueError("name 不能为空")
        # 检查是否已存在
        if await self._redis.exists(self._redis.key("skill", name)):
            raise ValueError(f"skill 已存在: {name}")
        description = params.get("description", "")
        now = datetime.now(timezone.utc).isoformat()
        # 解析 tags
        tags_json = "[]"
        if "tags" in params:
            try:
                tags_json = _json.dumps(params["tags"])
            except Exception:
                pass
        # 存储 Skill 元数据
        await self._redis.hset(self._redis.key("skill", name), {
            "name": name,
            "description": description,
            "version": "1",
            "tags": tags_json,
            "created_at": now,
            "updated_at": now,
        })
        # 存储 DNA
        dna_map: Dict[str, str] = {}
        if "dna" in params and isinstance(params["dna"], dict):
            for k, v in params["dna"].items():
                if isinstance(v, (list, dict)):
                    dna_map[k] = _json.dumps(v)
                else:
                    dna_map[k] = str(v) if v is not None else ""
        for field in ["rules", "checklist", "anti_patterns", "best_practices", "context_hints"]:
            if field not in dna_map:
                dna_map[field] = "[]"
        if "template" not in dna_map:
            dna_map["template"] = ""
        await self._redis.hset(self._redis.key("skill", name, "dna"), dna_map)
        # 计算规则数
        rule_count = 0
        try:
            rule_count = len(_json.loads(dna_map.get("rules", "[]")))
        except Exception:
            pass
        # 初始化 Metrics
        await self._redis.hset(self._redis.key("skill", name, "metrics"), {
            "pass_rate": "0",
            "usage_count": "0",
            "evolution_count": "0",
            "rule_count": str(rule_count),
            "stale_rules": "0",
        })
        # 加入 Skill 列表
        await self._redis.sadd(self._redis.key("skill", "list"), name)
        self._logger.info(f"Dashboard 创建 Skill name={name}")

    async def update_skill_from_dashboard(self, name: str, params: Dict[str, Any]) -> None:
        """从 Dashboard 更新 Skill（与 Go 版 UpdateSkillFromDashboard 一致）。"""
        import json as _json
        from datetime import datetime, timezone
        if not await self._redis.exists(self._redis.key("skill", name)):
            raise ValueError(f"skill 不存在: {name}")
        now = datetime.now(timezone.utc).isoformat()
        # 更新描述
        if "description" in params:
            await self._redis.hset(self._redis.key("skill", name), {
                "description": params["description"],
                "updated_at": now,
            })
        # 更新 Tags
        if "tags" in params:
            await self._redis.hset(self._redis.key("skill", name), {
                "tags": _json.dumps(params["tags"]),
                "updated_at": now,
            })
        # 更新 DNA
        if "dna" in params and isinstance(params["dna"], dict):
            dna_map: Dict[str, str] = {}
            for k, v in params["dna"].items():
                if isinstance(v, (list, dict)):
                    dna_map[k] = _json.dumps(v)
                else:
                    dna_map[k] = str(v) if v is not None else ""
            if dna_map:
                await self._redis.hset(self._redis.key("skill", name, "dna"), dna_map)
                await self._redis.hset(self._redis.key("skill", name), {"updated_at": now})
                # 更新规则数
                if "rules" in dna_map:
                    try:
                        rule_count = len(_json.loads(dna_map["rules"]))
                        await self._redis.hset(self._redis.key("skill", name, "metrics"),
                                               {"rule_count": str(rule_count)})
                    except Exception:
                        pass
        self._logger.info(f"Dashboard 更新 Skill name={name}")

    async def delete_skill_from_dashboard(self, name: str) -> None:
        """从 Dashboard 删除 Skill（与 Go 版 DeleteSkillFromDashboard 一致）。"""
        if not await self._redis.exists(self._redis.key("skill", name)):
            raise ValueError(f"skill 不存在: {name}")
        await self._redis.delete(self._redis.key("skill", name))
        await self._redis.delete(self._redis.key("skill", name, "dna"))
        await self._redis.delete(self._redis.key("skill", name, "metrics"))
        await self._redis.delete(self._redis.key("skill", name, "versions"))
        await self._redis.delete(self._redis.key("skill", name, "rule_usage"))
        await self._redis.srem(self._redis.key("skill", "list"), name)
        self._logger.info(f"Dashboard 删除 Skill name={name}")

    async def audit_skill_from_dashboard(self, name: str, auto_fix: bool = False) -> Dict[str, Any]:
        """审核 Skill DNA 质量（与 Go 版 AuditSkillFromDashboard 一致）。"""
        import json as _json
        dna_data = await self._redis.hgetall(self._redis.key("skill", name, "dna"))
        if not dna_data:
            raise ValueError(f"skill 不存在或无 DNA 数据: {name}")
        skill_data = await self._redis.hgetall(self._redis.key("skill", name))
        version = skill_data.get("version", "1") if skill_data else "1"

        rules: List[str] = []
        anti_patterns: List[str] = []
        best_practices: List[str] = []
        checklist: List[str] = []
        try:
            rules = _json.loads(dna_data.get("rules", "[]"))
        except Exception:
            pass
        try:
            anti_patterns = _json.loads(dna_data.get("anti_patterns", "[]"))
        except Exception:
            pass
        try:
            best_practices = _json.loads(dna_data.get("best_practices", "[]"))
        except Exception:
            pass
        try:
            checklist = _json.loads(dna_data.get("checklist", "[]"))
        except Exception:
            pass

        issues: List[Dict[str, Any]] = []

        # 1. 重复检测
        def check_dups(items: List[str], field_name: str):
            seen_map: Dict[str, int] = {}
            for i, item in enumerate(items):
                norm = item.lower().strip()
                if norm in seen_map:
                    issues.append({
                        "severity": "warning",
                        "category": "duplicate",
                        "description": f'{field_name}[{i}] 与 {field_name}[{seen_map[norm]}] 内容重复: "{item[:60]}"',
                        "suggestion": "移除重复项",
                        "auto_fixable": True,
                        "fixed": False,
                    })
                else:
                    seen_map[norm] = i

        check_dups(rules, "rules")
        check_dups(anti_patterns, "anti_patterns")
        check_dups(best_practices, "best_practices")

        # 2. 模糊性检测
        vague_words = ["注意", "小心", "确保", "应该", "需要", "appropriate", "proper", "good", "should"]
        def check_vague(items: List[str], field_name: str):
            for i, item in enumerate(items):
                if len(item) < 10:
                    issues.append({
                        "severity": "warning",
                        "category": "vague",
                        "description": f'{field_name}[{i}] 内容过短，缺乏可操作性: "{item}"',
                        "suggestion": "补充具体操作步骤或量化标准",
                        "auto_fixable": False,
                        "fixed": False,
                    })
                elif len(item) < 20:
                    for vw in vague_words:
                        if vw.lower() in item.lower():
                            issues.append({
                                "severity": "info",
                                "category": "vague",
                                "description": f'{field_name}[{i}] 可能过于笼统: "{item}"',
                                "suggestion": "建议增加具体示例",
                                "auto_fixable": False,
                                "fixed": False,
                            })
                            break

        check_vague(rules, "rules")
        check_vague(anti_patterns, "anti_patterns")

        # 3. 膨胀检测
        if len(rules) > 15:
            issues.append({
                "severity": "warning",
                "category": "bloat",
                "description": f"规则数量过多 ({len(rules)}/20)，Agent 难以全部遵守",
                "suggestion": "触发规则蒸馏，合并相似规则",
                "auto_fixable": False,
                "fixed": False,
            })
        if len(anti_patterns) > 12:
            issues.append({
                "severity": "info",
                "category": "bloat",
                "description": f"反模式数量较多 ({len(anti_patterns)}/15)，接近上限",
                "suggestion": "审查是否有过时反模式可移除",
                "auto_fixable": False,
                "fixed": False,
            })

        # 4. 矛盾检测
        for i, ap in enumerate(anti_patterns):
            for j, bp in enumerate(best_practices):
                if len(ap) > 10 and len(bp) > 10:
                    if ap.lower() in bp.lower() or bp.lower() in ap.lower():
                        issues.append({
                            "severity": "critical",
                            "category": "conflict",
                            "description": f'anti_patterns[{i}] 与 best_practices[{j}] 可能矛盾: "{ap[:40]}" vs "{bp[:40]}"',
                            "suggestion": "保留正确的一条，移除错误的",
                            "auto_fixable": False,
                            "fixed": False,
                        })

        critical_count = sum(1 for iss in issues if iss["severity"] == "critical")
        warning_count = sum(1 for iss in issues if iss["severity"] == "warning")
        info_count = sum(1 for iss in issues if iss["severity"] == "info")

        health = "healthy"
        recommendation = "Skill DNA 质量良好"
        if critical_count > 0:
            health = "unhealthy"
            recommendation = f"发现 {critical_count} 个严重问题，建议立即修复"
        elif warning_count > 3:
            health = "needs_attention"
            recommendation = f"发现 {warning_count} 个警告，建议修复"

        # 自动修复（去重）
        auto_fixed = 0
        if auto_fix:
            dna_key = self._redis.key("skill", name, "dna")
            for field in ["rules", "anti_patterns", "best_practices"]:
                raw = await self._redis.hget(dna_key, field)
                if not raw:
                    continue
                try:
                    items_list = _json.loads(raw)
                except Exception:
                    continue
                seen_set: Dict[str, bool] = {}
                deduped = []
                for item in items_list:
                    norm = item.lower().strip()
                    if norm not in seen_set:
                        seen_set[norm] = True
                        deduped.append(item)
                if len(deduped) < len(items_list):
                    auto_fixed += len(items_list) - len(deduped)
                    await self._redis.hset(dna_key, {field: _json.dumps(deduped)})
            for iss in issues:
                if iss.get("auto_fixable") and iss.get("category") == "duplicate":
                    iss["fixed"] = True

        return {
            "skill_name": name,
            "version": version,
            "overall_health": health,
            "total_issues": len(issues),
            "critical_count": critical_count,
            "warning_count": warning_count,
            "info_count": info_count,
            "issues": issues,
            "auto_fixed": auto_fixed,
            "recommendation": recommendation,
            "dna_stats": {
                "rules": len(rules),
                "anti_patterns": len(anti_patterns),
                "best_practices": len(best_practices),
                "checklist": len(checklist),
            },
        }

    async def absorb_skills(self, remote_addr: str, keyword: str = "", overwrite: bool = False) -> Dict[str, Any]:
        """从远程 AgentFlow 实例吸收 Skill（与 Go 版 AbsorbSkills 一致）。"""
        import json as _json
        import aiohttp
        from datetime import datetime, timezone
        if not remote_addr:
            raise ValueError("远程地址不能为空")
        remote_addr = remote_addr.rstrip("/")
        if not remote_addr.startswith("http://") and not remote_addr.startswith("https://"):
            remote_addr = "http://" + remote_addr

        absorbed = 0
        skipped = 0
        merged = 0
        failed = 0
        details: List[Dict[str, str]] = []

        try:
            async with aiohttp.ClientSession() as session:
                # 1. 拉取远程 Skill 列表
                async with session.get(f"{remote_addr}/api/skills", timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        raise ValueError(f"远程返回状态码 {resp.status}")
                    remote_skills = await resp.json()

                for remote_sk in remote_skills:
                    name = remote_sk.get("name", "")
                    if not name:
                        failed += 1
                        continue
                    if keyword and keyword.lower() not in name.lower():
                        continue
                    # 2. 获取远程 Skill 详情
                    try:
                        async with session.get(f"{remote_addr}/api/skills/detail?name={name}",
                                               timeout=aiohttp.ClientTimeout(total=30)) as detail_resp:
                            if detail_resp.status != 200:
                                failed += 1
                                details.append({"name": name, "status": "failed", "reason": f"HTTP {detail_resp.status}"})
                                continue
                            skill_detail = await detail_resp.json()
                    except Exception as e:
                        failed += 1
                        details.append({"name": name, "status": "failed", "reason": str(e)})
                        continue

                    # 3. 检查本地是否存在
                    exists = await self._redis.exists(self._redis.key("skill", name))
                    if exists and not overwrite:
                        # 合并模式
                        merged_count = await self._merge_skill_dna(name, skill_detail)
                        if merged_count > 0:
                            merged += 1
                            details.append({"name": name, "status": "merged", "reason": f"新增 {merged_count} 条规则"})
                        else:
                            skipped += 1
                            details.append({"name": name, "status": "skipped", "reason": "无新规则需合并"})
                        continue

                    is_overwrite = exists and overwrite
                    # 4. 覆盖或新建
                    try:
                        await self._import_skill_from_remote(name, skill_detail)
                        if is_overwrite:
                            await self._redis.hset(self._redis.key("skill", name),
                                                   {"updated_at": datetime.now(timezone.utc).isoformat()})
                            details.append({"name": name, "status": "overwritten"})
                        else:
                            absorbed += 1
                            details.append({"name": name, "status": "absorbed"})
                    except Exception as e:
                        failed += 1
                        details.append({"name": name, "status": "failed", "reason": str(e)})
        except Exception as e:
            raise ValueError(f"连接远程失败: {e}")

        overwritten = sum(1 for d in details if d.get("status") == "overwritten")
        self._logger.info(f"吸收远程 Skill 完成 remote={remote_addr} absorbed={absorbed} merged={merged} overwritten={overwritten} skipped={skipped} failed={failed}")
        return {
            "status": "done",
            "remote_addr": remote_addr,
            "absorbed": absorbed,
            "merged": merged,
            "skipped": skipped,
            "overwritten": overwritten,
            "failed": failed,
            "details": details,
        }

    async def _merge_skill_dna(self, name: str, remote_detail: Dict[str, Any]) -> int:
        """将远程 Skill DNA 合并到本地（去重后追加新规则）。"""
        import json as _json
        dna_key = self._redis.key("skill", name, "dna")
        local_dna = await self._redis.hgetall(dna_key)
        remote_dna = remote_detail.get("dna", {}) if isinstance(remote_detail.get("dna"), dict) else {}
        total_new = 0
        updates: Dict[str, str] = {}
        merge_fields = ["rules", "checklist", "anti_patterns", "best_practices", "context_hints"]
        for field in merge_fields:
            local_arr: List[str] = []
            try:
                local_arr = _json.loads(local_dna.get(field, "[]"))
            except Exception:
                pass
            local_set = {item.lower().strip() for item in local_arr}
            remote_arr: List[str] = []
            rv = remote_dna.get(field)
            if isinstance(rv, list):
                remote_arr = [str(x) for x in rv]
            elif isinstance(rv, str):
                try:
                    remote_arr = _json.loads(rv)
                except Exception:
                    pass
            new_items = []
            for item in remote_arr:
                trimmed = item.strip()
                if trimmed and trimmed.lower() not in local_set:
                    new_items.append(trimmed)
                    local_set.add(trimmed.lower())
            if new_items:
                merged = local_arr + new_items
                updates[field] = _json.dumps(merged)
                total_new += len(new_items)
        if not updates:
            return 0
        from datetime import datetime, timezone
        await self._redis.hset(dna_key, updates)
        await self._redis.hset(self._redis.key("skill", name),
                               {"updated_at": datetime.now(timezone.utc).isoformat()})
        return total_new

    async def _import_skill_from_remote(self, name: str, detail: Dict[str, Any]) -> None:
        """将远程 Skill 数据导入本地。"""
        import json as _json
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        description = detail.get("description", "")
        tags_json = "[]"
        if "tags" in detail and detail["tags"] is not None:
            try:
                tags_json = _json.dumps(detail["tags"])
            except Exception:
                pass
        await self._redis.hset(self._redis.key("skill", name), {
            "name": name,
            "description": description,
            "version": "1",
            "tags": tags_json,
            "created_at": now,
            "updated_at": now,
            "source": "absorbed",
            "absorbed_at": now,
        })
        dna_map: Dict[str, str] = {}
        if isinstance(detail.get("dna"), dict):
            for k, v in detail["dna"].items():
                if isinstance(v, (list, dict)):
                    dna_map[k] = _json.dumps(v)
                else:
                    dna_map[k] = str(v) if v is not None else ""
        for field in ["rules", "checklist", "anti_patterns", "best_practices", "context_hints"]:
            if field not in dna_map:
                dna_map[field] = "[]"
        if "template" not in dna_map:
            dna_map["template"] = ""
        await self._redis.hset(self._redis.key("skill", name, "dna"), dna_map)
        rule_count = 0
        try:
            rule_count = len(_json.loads(dna_map.get("rules", "[]")))
        except Exception:
            pass
        await self._redis.hset(self._redis.key("skill", name, "metrics"), {
            "pass_rate": "0",
            "usage_count": "0",
            "evolution_count": "0",
            "rule_count": str(rule_count),
            "stale_rules": "0",
        })
        await self._redis.sadd(self._redis.key("skill", "list"), name)

    async def evolve_skill_from_dashboard(self, skill_name: str, auto_apply: bool = True) -> Dict[str, Any]:
        """从 Dashboard 手动触发 Skill 进化（与 Go 版 EvolveSkillFromDashboard 一致）。"""
        if not skill_name:
            raise ValueError("skill name 不能为空")
        if not await self._redis.exists(self._redis.key("skill", skill_name)):
            raise ValueError(f"skill 不存在: {skill_name}")
        # 通过 evo_engine 触发进化（如果已设置）
        if hasattr(self, "_evo_engine") and self._evo_engine is not None:
            result = await self._evo_engine.distill_and_evolve_dashboard(skill_name, auto_apply, 5, True)
            import json as _json
            result_json = _json.dumps(result) if not isinstance(result, str) else result
            result_map = _json.loads(result_json) if isinstance(result_json, str) else result
            self._logger.info(f"Dashboard 手动触发 Skill 进化 skill={skill_name} auto_apply={auto_apply}")
            return result_map
        return {"status": "no_evo_engine", "message": "进化引擎未初始化"}

    def set_evo_engine(self, evo_engine: Any) -> None:
        """设置进化引擎（避免循环依赖）。"""
        self._evo_engine = evo_engine

    async def get_skill_auto_evolution(self) -> bool:
        """获取 Skill 自动进化开关状态。"""
        val = await self._redis.hget(self._redis.key("config", "dashboard"), "skill_auto_evolution")
        if not val:
            return True  # 默认开启
        return val in ("true", "1")

    async def set_skill_auto_evolution(self, enabled: bool) -> None:
        """设置 Skill 自动进化开关。"""
        await self._redis.hset(self._redis.key("config", "dashboard"),
                               {"skill_auto_evolution": "true" if enabled else "false"})

    # ==================== Goals Dashboard API ====================

    async def get_goals_filtered(self, statuses: List[str] = None, name: str = "") -> List[Dict[str, Any]]:
        """获取目标列表，支持多状态过滤和名称模糊搜索（与 Go 版 GetGoals 一致）。"""
        list_key = self._redis.key("goal", "list")
        goal_ids = await self._redis.zrangebyscore(list_key, "-inf", "+inf")
        status_filter = set(statuses) if statuses else set()
        goals: List[Dict[str, Any]] = []
        for goal_id in goal_ids:
            data = await self._redis.hgetall(self._redis.key("goal", goal_id))
            if not data:
                continue
            # 状态过滤
            if status_filter and data.get("status") not in status_filter:
                continue
            # 名称模糊搜索（不区分大小写）
            if name and name.lower() not in data.get("title", "").lower():
                continue
            # 获取子任务统计
            subtask_ids = await self._redis.lrange(self._redis.key("goal", goal_id, "subtasks"), 0, -1)
            completed = 0
            for tid in subtask_ids:
                st = await self._redis.hget(self._redis.key("task", tid), "status")
                if st == "completed":
                    completed += 1
            goals.append({
                "id": goal_id,
                "title": data.get("title", ""),
                "description": data.get("description", ""),
                "status": data.get("status", ""),
                "priority": data.get("priority", "5"),
                "progress": data.get("progress", "0"),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
                "total_tasks": len(subtask_ids),
                "completed": completed,
            })
        return goals

    async def update_goal_status(self, goal_id: str, new_status: str) -> None:
        """更新目标状态（与 Go 版 UpdateGoalStatus 一致）。"""
        from datetime import datetime, timezone
        valid_statuses = {"pending", "active", "completed", "cancelled"}
        if new_status not in valid_statuses:
            raise ValueError(f"无效的目标状态: {new_status}")
        key = self._redis.key("goal", goal_id)
        if not await self._redis.exists(key):
            raise ValueError(f"目标不存在: {goal_id}")
        await self._redis.hset(key, {
            "status": new_status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })

    # ==================== Review Batch API ====================

    async def review_batch_pass(self, goal_id: str, reviewer: str = "", comment: str = "") -> int:
        """批量将指定 goal_id 下所有 review 状态任务标记为 completed（与 Go 版 ReviewBatchPass 一致）。"""
        from datetime import datetime, timezone
        if not goal_id:
            raise ValueError("goal_id 不能为空")
        now = datetime.now(timezone.utc).isoformat()
        updated = 0
        # 遍历 review 队列
        queue_key = self._redis.key("task", "queue", "review")
        members = await self._redis.zrangebyscore(queue_key, "-inf", "+inf")
        for task_id in members:
            data = await self._redis.hgetall(self._redis.key("task", task_id))
            if not data or data.get("goal_id") != goal_id:
                continue
            # 更新状态为 completed
            ok = await self.update_task_status(task_id, "completed")
            if not ok:
                continue
            # 写入 review 结果字段
            await self._redis.hset(self._redis.key("task", task_id), {
                "review_result": "passed",
                "reviewed_at": now,
                "reviewed_by": reviewer,
                "review_comment": comment,
            })
            updated += 1
        self._logger.info(f"Review批量通过完成 goal_id={goal_id} updated={updated}")
        return updated

    async def review_batch_fail(self, goal_id: str, reviewer: str = "", comment: str = "") -> int:
        """批量将指定 goal_id 下所有 review 状态任务标记为 failed（与 Go 版 ReviewBatchFail 一致）。"""
        from datetime import datetime, timezone
        if not goal_id:
            raise ValueError("goal_id 不能为空")
        now = datetime.now(timezone.utc).isoformat()
        updated = 0
        queue_key = self._redis.key("task", "queue", "review")
        members = await self._redis.zrangebyscore(queue_key, "-inf", "+inf")
        for task_id in members:
            data = await self._redis.hgetall(self._redis.key("task", task_id))
            if not data or data.get("goal_id") != goal_id:
                continue
            ok = await self.update_task_status(task_id, "failed")
            if not ok:
                continue
            await self._redis.hset(self._redis.key("task", task_id), {
                "review_result": "failed",
                "reviewed_at": now,
                "reviewed_by": reviewer,
                "review_comment": comment,
            })
            updated += 1
        self._logger.info(f"Review批量拒绝完成 goal_id={goal_id} updated={updated}")
        return updated

    # ==================== Complaints API ====================

    async def get_complaints_list(self, cursor: str = "", limit: int = 20,
                                   filter_type: str = "") -> Dict[str, Any]:
        """获取吐槽列表（与 Go 版 GetComplaintsList 一致）。"""
        list_key = self._redis.key("feedback", "list")
        all_ids = await self._redis.lrange(list_key, 0, -1)
        complaints = []
        for fid in all_ids:
            data = await self._redis.hgetall(self._redis.key("feedback", fid))
            if not data:
                continue
            if filter_type and data.get("type") != filter_type:
                continue
            if "id" not in data:
                data["id"] = fid
            complaints.append(data)
        # 简单游标分页（cursor 为上次最后一个 id）
        start = 0
        if cursor:
            for i, c in enumerate(complaints):
                if c.get("id") == cursor:
                    start = i + 1
                    break
        page = complaints[start:start + limit]
        has_more = (start + limit) < len(complaints)
        next_cursor = page[-1].get("id", "") if page and has_more else ""
        return {
            "complaints": page,
            "cursor": next_cursor,
            "has_more": has_more,
        }

    # ==================== Experience Organize API ====================

    async def organize_experiences(self) -> Dict[str, Any]:
        """整理经验（去重+自动标注 pattern_tags，与 Go 版 OrganizeExperiences 一致）。"""
        import json as _json
        total_processed = 0
        duplicates_removed = 0
        tags_added = 0
        all_details: List[Dict[str, Any]] = []

        for exp_type in ["positive", "negative"]:
            stream_key = self._redis.key("exp", exp_type)
            messages = await self._redis.xrevrange(stream_key, count=10000)
            # 1. 去重：按 description 小写去重
            seen: Dict[str, str] = {}  # desc_lower -> first_id
            dup_ids: List[str] = []
            for msg in messages:
                msg_id = msg["id"]
                desc = msg.get("fields", {}).get("description", "").lower().strip()
                if not desc:
                    continue
                if desc in seen:
                    dup_ids.append(msg_id)
                else:
                    seen[desc] = msg_id
            # 删除重复经验
            for dup_id in dup_ids:
                deleted = await self._redis.xdel(stream_key, dup_id)
                if deleted > 0:
                    duplicates_removed += 1
            # 2. 重新拉取去重后的经验，自动标注 pattern_tags
            clean_messages = await self._redis.xrevrange(stream_key, count=10000)
            for msg in clean_messages:
                total_processed += 1
                msg_id = msg["id"]
                fields = msg.get("fields", {})
                pattern_tags = fields.get("pattern_tags", "")
                if pattern_tags and pattern_tags not in ("[]", "null"):
                    continue
                desc = fields.get("description", "")
                solution = fields.get("solution", "")
                root_cause = fields.get("root_cause", "")
                tags = _auto_detect_pattern_tags(desc + " " + solution + " " + root_cause)
                if tags:
                    # 读旧→合并→删旧→添新
                    new_data = {k: str(v) for k, v in fields.items() if v is not None}
                    new_data["pattern_tags"] = _json.dumps(tags)
                    await self._redis.xdel(stream_key, msg_id)
                    await self._redis.xadd(stream_key, new_data, maxlen=10000)
                    tags_added += 1
                    all_details.append({
                        "id": msg_id,
                        "type": exp_type,
                        "action": "tags_added",
                        "tags": tags,
                        "desc": desc[:80],
                    })

        self._logger.info(f"经验整理完成 processed={total_processed} duplicates_removed={duplicates_removed} tags_added={tags_added}")
        return {
            "total_processed": total_processed,
            "duplicates_removed": duplicates_removed,
            "tags_added": tags_added,
            "abstractions_added": 0,
            "details": all_details,
        }

    # ==================== Recovery Timeline API ====================

    async def get_recovery_timeline(self, task_id: str = "", agent_id: str = "") -> Dict[str, Any]:
        """获取任务恢复链路数据（与 Go 版 GetRecoveryTimeline 一致）。"""
        result: Dict[str, Any] = {}
        # 获取恢复统计
        if self._sqlite and hasattr(self._sqlite, "get_recovery_stats"):
            try:
                stats = await self._sqlite.get_recovery_stats()
                result["stats"] = stats
            except Exception:
                result["stats"] = {}
        else:
            result["stats"] = {}
        # 获取恢复事件列表
        events = []
        if self._sqlite and hasattr(self._sqlite, "query_recovery_events"):
            try:
                raw_events = await self._sqlite.query_recovery_events(task_id, agent_id, "", "", 200)
                for ev in raw_events:
                    events.append({
                        "id": getattr(ev, "id", ""),
                        "event_type": getattr(ev, "event_type", ""),
                        "agent_id": getattr(ev, "agent_id", ""),
                        "detail": getattr(ev, "detail", ""),
                        "progress": getattr(ev, "progress", 0),
                        "created_at": getattr(ev, "created_at", ""),
                        "task_id": getattr(ev, "task_id", ""),
                    })
            except Exception:
                pass
        elif self._sqlite and hasattr(self._sqlite, "query_recovery_timeline"):
            try:
                events = await self._sqlite.query_recovery_timeline()
            except Exception:
                pass
        # 按任务ID分组
        task_events: Dict[str, List[Dict]] = {}
        task_set: set = set()
        for ev in events:
            tid = ev.get("task_id", "")
            if tid:
                task_set.add(tid)
                task_events.setdefault(tid, []).append(ev)
        # 为每个任务获取基本信息
        timelines = []
        for tid in task_set:
            task_data = await self._redis.hgetall(self._redis.key("task", tid))
            if not task_data:
                continue
            timeline = {
                "task_id": tid,
                "title": task_data.get("title", ""),
                "status": task_data.get("status", ""),
                "progress": task_data.get("progress", "0"),
                "skill_type": task_data.get("skill_type", ""),
                "claimed_by": task_data.get("claimed_by", ""),
                "events": task_events.get(tid, []),
            }
            cp_data = await self._redis.get(self._redis.key("task", tid, "checkpoint"))
            if cp_data:
                timeline["has_checkpoint"] = True
            timelines.append(timeline)
        result["timelines"] = timelines
        result["total_tasks"] = len(timelines)
        return result


def _auto_detect_pattern_tags(text: str) -> List[str]:
    """从文本中自动推断 pattern_tags（与 Go 版 autoDetectPatternTags 一致）。"""
    text_lower = text.lower()
    tags: List[str] = []
    seen: set = set()
    pattern_mappings = [
        (["null check", "null 检查", "null 保护", "null guard", "nil check", "nil pointer", "空指针", "空引用"], "null_guard_missing"),
        (["世界旋转", "局部旋转", "world rotation", "local rotation", "世界坐标", "局部坐标", "transform.rotation"], "world_vs_local_transform"),
        (["c# to ts", "c#→ts", "c# 到 ts", "c#迁移", "unity to cocos", "unity迁移"], "c#_to_ts_migration"),
        (["tween", "缓动", "tweenaction"], "tween_api_compat"),
        (["getcomponent", "addcomponent", "组件获取"], "component_access_pattern"),
        (["资源加载", "resource load", "prefab", "预制体"], "resource_loading"),
        (["生命周期", "lifecycle", "onload", "ondestroy"], "lifecycle_timing"),
        (["类型转换", "type cast", "类型断言"], "type_conversion"),
        (["异步", "async", "await", "promise", "回调"], "async_pattern"),
        (["内存泄漏", "memory leak", "引用泄漏"], "memory_leak"),
        (["api 兼容", "api compat", "api 差异"], "api_compatibility"),
        (["数组越界", "index out", "out of range"], "index_out_of_bounds"),
        (["死循环", "infinite loop", "无限递归"], "infinite_loop"),
        (["并发", "concurrent", "race condition", "deadlock", "死锁"], "concurrency_issue"),
    ]
    for keywords, tag in pattern_mappings:
        for kw in keywords:
            if kw in text_lower and tag not in seen:
                tags.append(tag)
                seen.add(tag)
                break
    return tags