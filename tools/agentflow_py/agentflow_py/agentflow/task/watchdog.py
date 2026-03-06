"""Watchdog: zombie task detection and auto-recovery."""
import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from agentflow.storage import RedisClient, SQLiteStore
from agentflow.config import WatchdogConfig
from .model import Task, TaskStatus, Checkpoint, AutoCheckpoint


class Watchdog:
    def __init__(self, redis: RedisClient, sqlite: SQLiteStore,
                 cfg: WatchdogConfig, logger: logging.Logger,
                 namespaces: Optional[List[str]] = None):
        self._redis = redis
        self._sqlite = sqlite
        self._cfg = cfg
        self._logger = logger
        self._task: Optional[asyncio.Task] = None
        self._running = False
        # 多 namespace 支持：扫描时覆盖所有 namespace
        self._namespaces: List[str] = namespaces or [""]
        # In-memory heartbeat tracking: agent_id -> last_ts
        self._heartbeats: Dict[str, float] = {}
        # Tool call tracking: (task_id, agent_id) -> list of records
        self._tool_calls: Dict[str, List[Dict]] = {}

    def start(self) -> None:
        if not self._cfg.enabled:
            return
        self._running = True
        self._task = asyncio.create_task(self._scan_loop())
        self._logger.info(
            f"Watchdog 已启动 scan_interval={self._cfg.scan_interval}s "
            f"soft_timeout={self._cfg.soft_timeout}s "
            f"heartbeat_timeout={self._cfg.heartbeat_timeout}s"
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _scan_loop(self) -> None:
        # 启动时立即扫描一次（处理 MCP Server 重启前的僵尸任务）
        try:
            await self._scan_and_recover()
        except Exception as e:
            self._logger.error(f"Watchdog首次扫描异常: {e}")

        while self._running:
            await asyncio.sleep(self._cfg.scan_interval)
            try:
                await self._scan_and_recover()
            except Exception as e:
                self._logger.error(f"Watchdog扫描异常: {e}")

    async def _scan_and_recover(self) -> None:
        """扫描所有 namespace 的 running 队列，检测并处理僵尸任务。"""
        zombie_count = 0
        soft_timeout_count = 0

        for ns in self._namespaces:
            # 通过 RedisClient.key 的 namespace 参数构建多租户队列 key
            running_queue = self._redis.key(
                "task", "queue", TaskStatus.RUNNING, namespace=ns
            )
            members = await self._redis.zrangebyscore(running_queue, "-inf", "+inf")
            if not members:
                continue

            for task_id in members:
                data = await self._redis.hgetall(self._redis.key("task", task_id, namespace=ns))
                if not data:
                    await self._redis.zrem(running_queue, task_id)
                    continue
                agent_id = data.get("claimed_by", "")
                if not agent_id:
                    # 没有认领者但在 running 队列 → 异常状态，视为僵尸
                    await self._handle_zombie(task_id, "unknown", data, namespace=ns)
                    zombie_count += 1
                    continue

                silent = await self._get_agent_silent_duration(agent_id, data)
                if silent < self._cfg.soft_timeout:
                    continue
                elif silent < self._cfg.heartbeat_timeout:
                    await self._handle_soft_timeout(task_id, agent_id, data)
                    soft_timeout_count += 1
                else:
                    await self._handle_zombie(task_id, agent_id, data, namespace=ns)
                    zombie_count += 1

        if zombie_count > 0:
            self._logger.warning(f"检测到僵尸任务 count={zombie_count}")
        if soft_timeout_count > 0:
            self._logger.warning(
                f"检测到软超时任务（预警）count={soft_timeout_count} "
                f"soft_timeout={self._cfg.soft_timeout}s "
                f"hard_timeout={self._cfg.heartbeat_timeout}s"
            )

    async def _get_agent_silent_duration(self, agent_id: str,
                                          task_data: Optional[Dict] = None) -> float:
        """获取 Agent 的静默时长（优先内存心跳 → Redis心跳 → updated_at）。"""
        # 1. 优先检查内存中的心跳记录
        last_ts = self._heartbeats.get(agent_id, 0)
        if last_ts > 0:
            return time.time() - last_ts

        # 2. 检查 Redis 中的心跳（多实例部署场景）
        hb_key = self._redis.key("lock", "heartbeat", agent_id)
        try:
            hb_val = await self._redis.get(hb_key)
            if hb_val:
                return 0  # Redis 心跳仍然活跃
        except Exception:
            pass

        # 3. 最后检查任务 updated_at 时间
        if task_data:
            updated_at = task_data.get("updated_at", "")
            if updated_at:
                try:
                    t = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                    return (datetime.now(timezone.utc) - t).total_seconds()
                except Exception:
                    pass

        # 无法判断 → 返回超大值，让上层逻辑判断为僵尸
        return float(self._cfg.heartbeat_timeout) + 60.0

    async def _handle_soft_timeout(self, task_id: str, agent_id: str,
                                    data: Dict) -> None:
        """处理软超时任务：记录警告日志 + SQLite 事件，不中断任务。"""
        remaining = self._cfg.heartbeat_timeout - self._cfg.soft_timeout
        self._logger.warning(
            f"任务心跳软超时预警：Agent 可能处于长时间思考中，"
            f"建议定期调用 update_task_progress 或 save_checkpoint 续期心跳 "
            f"task={task_id} agent={agent_id} "
            f"title={data.get('title', '')} progress={data.get('progress', 0)} "
            f"remaining_before_interrupt={remaining}s"
        )
        # 记录软超时预警事件到 SQLite
        if self._sqlite:
            try:
                progress = float(data.get("progress", 0))
                detail = (
                    f"Agent {agent_id} 心跳软超时预警，"
                    f"距硬超时中断还有 {remaining}s"
                )
                await self._sqlite.record_recovery_event(
                    task_id, agent_id, "soft_timeout", detail, progress
                )
            except Exception:
                pass

    async def _handle_zombie(self, task_id: str, agent_id: str, data: Dict,
                              namespace: str = "") -> None:
        """处理僵尸任务：保存中断快照 → 标记 interrupted → 移动队列 → 释放锁。"""
        self._logger.warning(
            f"检测到僵尸任务，标记为 interrupted "
            f"task={task_id} agent={agent_id} "
            f"progress={data.get('progress', 0)} title={data.get('title', '')}"
        )
        now = datetime.now(timezone.utc).isoformat()
        progress = float(data.get("progress", 0))

        # 保存中断快照（保留当前所有信息以便恢复）
        snapshot = {
            "task_id": task_id,
            "agent_id": agent_id,
            "progress": data.get("progress", 0),
            "status_before": data.get("status", ""),
            "interrupted_at": now,
            "summary": data.get("summary", ""),
        }
        snapshot_key = self._redis.key("task", task_id, "interrupt_snapshot", namespace=namespace)
        try:
            await self._redis.set(snapshot_key, json.dumps(snapshot))
        except Exception:
            pass

        # Auto-save checkpoint from tool call tracker
        await self._auto_save_checkpoint_on_interrupt(task_id, agent_id)

        # Mark interrupted
        await self._redis.hset(self._redis.key("task", task_id, namespace=namespace), {
            "status": TaskStatus.INTERRUPTED,
            "interrupted_at": now,
            "updated_at": now,
        })
        await self._redis.zrem(
            self._redis.key("task", "queue", TaskStatus.RUNNING, namespace=namespace), task_id
        )
        await self._redis.zadd(
            self._redis.key("task", "queue", TaskStatus.INTERRUPTED, namespace=namespace),
            {task_id: float(time.time())},
        )
        # Release lock
        lock_key = self._redis.key("lock", "task", task_id, namespace=namespace)
        await self._redis.delete(lock_key)

        # 清理内存中的心跳记录
        if agent_id and agent_id in self._heartbeats:
            del self._heartbeats[agent_id]

        # Record recovery event in SQLite
        if self._sqlite:
            try:
                detail = (
                    f"Agent {agent_id} 心跳超时，任务被看门狗标记为 interrupted"
                    f"（进度 {progress:.1f}%）"
                )
                await self._sqlite.record_recovery_event(
                    task_id, agent_id, "interrupted", detail, progress
                )
            except Exception:
                pass

    # ── Heartbeat / Hook ───────────────────────────────────────────────────────

    def touch_heartbeat(self, agent_id: str) -> None:
        """更新 Agent 的隐式心跳（由 MCP 工具调用钩子触发）。"""
        if not agent_id:
            return
        self._heartbeats[agent_id] = time.time()
        # 同时异步更新 Redis 中的心跳（用于多实例部署场景）
        asyncio.create_task(self._update_redis_heartbeat(agent_id))

    async def _update_redis_heartbeat(self, agent_id: str) -> None:
        """将心跳写入 Redis，TTL = heartbeat_timeout。"""
        try:
            hb_key = self._redis.key("lock", "heartbeat", agent_id)
            await self._redis.set(hb_key, "1", ex=self._cfg.heartbeat_timeout)
        except Exception:
            pass

    def get_agent_last_heartbeat(self, agent_id: str) -> Optional[float]:
        """获取 Agent 最后心跳时间戳（Unix 时间）。"""
        return self._heartbeats.get(agent_id)

    def make_implicit_heartbeat_hook(self):
        """Returns a call hook that auto-updates heartbeat from params."""
        watchdog = self

        def hook(tool_name: str, params: Dict) -> None:
            agent_id = (
                params.get("agent_id") or
                params.get("agentId") or ""
            )
            if agent_id:
                watchdog.touch_heartbeat(agent_id)
            # Track tool calls
            task_id = params.get("task_id") or params.get("taskId") or ""
            if agent_id and task_id:
                watchdog._record_tool_call(tool_name, params, agent_id, task_id)

        return hook

    def make_tool_call_tracker_hook(self):
        """
        创建工具调用追踪钩子（对应 Go 的 MakeToolCallTrackerHook）。
        在每次工具调用时，自动记录工具名+关键参数，提取 modified_files / read_files。
        中断后可通过 get_auto_checkpoint_async 恢复追踪数据。
        """
        watchdog = self

        def hook(tool_name: str, params: Dict) -> None:
            # 解析 agent_id（优先从参数，再从 task_id 反查）
            agent_id = (
                params.get("agent_id") or
                params.get("agentId") or ""
            )
            task_id = params.get("task_id") or params.get("taskId") or ""

            if agent_id:
                # 更新心跳
                watchdog.touch_heartbeat(agent_id)
                if task_id:
                    watchdog._record_tool_call(tool_name, params, agent_id, task_id)

        return hook

    def _record_tool_call(self, tool_name: str, params: Dict,
                           agent_id: str, task_id: str) -> None:
        key = f"{task_id}:{agent_id}"
        if key not in self._tool_calls:
            self._tool_calls[key] = []
        # 限制最多保留最近 200 条记录
        if len(self._tool_calls[key]) >= 200:
            self._tool_calls[key] = self._tool_calls[key][-150:]

        file_path = (
            params.get("path") or params.get("file_path") or
            params.get("target_file") or ""
        )
        action = self._infer_action(tool_name)
        record = {
            "tool_name": tool_name,
            "file_path": file_path,
            "action": action,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "brief": f"{action} {file_path}" if file_path else tool_name,
        }
        self._tool_calls[key].append(record)
        # Persist every 10 calls
        if len(self._tool_calls[key]) % 10 == 0:
            asyncio.create_task(self._persist_tool_call_logs(task_id, agent_id))

    def _infer_action(self, tool_name: str) -> str:
        name = tool_name.lower()
        if any(w in name for w in ("write", "edit", "create", "modify", "replace", "insert")):
            return "write"
        if any(w in name for w in ("read", "view", "open", "cat")):
            return "read"
        if any(w in name for w in ("search", "grep", "find", "glob")):
            return "search"
        if any(w in name for w in ("run", "exec", "bash", "shell", "command")):
            return "execute"
        return "other"

    async def _persist_tool_call_logs(self, task_id: str, agent_id: str) -> None:
        key = f"{task_id}:{agent_id}"
        records = self._tool_calls.get(key, [])
        if not records:
            return
        redis_key = self._redis.key("task", task_id, "tool_call_logs")
        try:
            await self._redis.set(redis_key, json.dumps({"agent_id": agent_id, "logs": records}))
        except Exception:
            pass

    async def find_running_task_for_agent(self, agent_id: str) -> str:
        """查找 Agent 当前正在运行的任务 ID。"""
        running_queue = self._redis.key("task", "queue", TaskStatus.RUNNING)
        try:
            members = await self._redis.zrangebyscore(running_queue, "-inf", "+inf")
        except Exception:
            return ""
        for task_id in members:
            try:
                data = await self._redis.hgetall(self._redis.key("task", task_id))
                if data and data.get("claimed_by") == agent_id:
                    return task_id
            except Exception:
                continue
        return ""

    async def is_zombie_task(self, task_id: str, namespace: str = "") -> bool:
        """
        判断任务是否为僵尸任务（硬超时）。
        对应 Go 的 isZombieTask。
        """
        data = await self._redis.hgetall(self._redis.key("task", task_id, namespace=namespace))
        if not data:
            return False
        agent_id = data.get("claimed_by", "")
        if not agent_id:
            # 没有认领者但在 running 队列，视为僵尸
            return True
        silent = await self._get_agent_silent_duration(agent_id, data)
        return silent >= self._cfg.heartbeat_timeout

    async def release_task(
        self, task_id: str, agent_id: str = "", reason: str = "手动释放"
    ) -> bool:
        """
        将超时或异常的任务归还到 pending 队列（任务自动释放）。
        对应 Go 版本的任务自动释放机制。
        只有当前认领者才能释放，或由看门狗强制释放（agent_id 为空）。
        返回 True 表示释放成功。
        """
        key = self._redis.key("task", task_id)
        data = await self._redis.hgetall(key)
        if not data:
            return False

        claimed_by = data.get("claimed_by", "")
        # 验证认领者（强制释放时 agent_id 为空，跳过验证）
        if agent_id and claimed_by and claimed_by != agent_id:
            self._logger.warning(
                f"释放任务失败：认领者不匹配 task={task_id} "
                f"claimed_by={claimed_by} requester={agent_id}"
            )
            return False

        now = datetime.now(timezone.utc).isoformat()
        # 更新任务状态为 pending，清除认领信息
        await self._redis.hset(key, {
            "status": TaskStatus.PENDING,
            "claimed_by": "",
            "updated_at": now,
        })
        # 移动队列: running → pending
        await self._redis.zrem(
            self._redis.key("task", "queue", TaskStatus.RUNNING), task_id
        )
        await self._redis.zadd(
            self._redis.key("task", "queue", TaskStatus.PENDING),
            {task_id: float(time.time())},
        )
        # 释放锁
        lock_key = self._redis.key("lock", "task", task_id)
        await self._redis.delete(lock_key)

        # 清理内存心跳
        if claimed_by and claimed_by in self._heartbeats:
            del self._heartbeats[claimed_by]

        self._logger.info(
            f"任务已释放回 pending 队列 task={task_id} "
            f"agent={claimed_by} reason={reason}"
        )

        # 记录释放事件到 SQLite
        if self._sqlite:
            try:
                progress = float(data.get("progress", 0))
                await self._sqlite.record_recovery_event(
                    task_id, claimed_by or agent_id, "released",
                    f"任务被释放回 pending 队列，原因：{reason}（进度 {progress:.1f}%）",
                    progress,
                )
            except Exception:
                pass
        return True

    # ── Checkpoint ────────────────────────────────────────────────────────────

    async def save_checkpoint(self, task_id: str, agent_id: str,
                               completed_items: Optional[List[str]] = None,
                               pending_items: Optional[List[str]] = None,
                               modified_files: Optional[List[str]] = None,
                               notes: str = "") -> None:
        data = await self._redis.hgetall(self._redis.key("task", task_id))
        progress = float(data.get("progress", 0)) if data else 0.0
        cp = Checkpoint(
            task_id=task_id,
            agent_id=agent_id,
            progress=progress,
            completed_items=completed_items or [],
            pending_items=pending_items or [],
            modified_files=modified_files or [],
            notes=notes,
            saved_at=datetime.now(timezone.utc).isoformat(),
        )
        cp_key = self._redis.key("task", task_id, "checkpoint")
        await self._redis.set(cp_key, json.dumps(cp.to_dict()), ex=86400 * 7)
        self._logger.info(f"检查点已保存 task={task_id} agent={agent_id}")

    def get_checkpoint(self, task_id: str) -> Optional[Checkpoint]:
        """Sync wrapper - returns None, use async version instead."""
        return None

    async def get_checkpoint_async(self, task_id: str) -> Optional[Checkpoint]:
        cp_key = self._redis.key("task", task_id, "checkpoint")
        val = await self._redis.get(cp_key)
        if not val:
            return None
        try:
            d = json.loads(val)
            return Checkpoint(**d)
        except Exception:
            return None

    def get_auto_checkpoint(self, task_id: str, agent_id: str = "") -> Optional[AutoCheckpoint]:
        """Sync wrapper - returns None, use async version instead."""
        return None

    async def get_auto_checkpoint_async(self, task_id: str, agent_id: str = "") -> Optional[AutoCheckpoint]:
        """从工具调用追踪数据自动生成检查点（对应 Go 的 GetAutoCheckpoint）。"""
        # 优先从内存获取
        key = f"{task_id}:{agent_id}"
        mem_logs = self._tool_calls.get(key, [])

        # 如果内存没有，从 Redis 加载
        logs = mem_logs
        if not logs:
            redis_key = self._redis.key("task", task_id, "tool_call_logs")
            try:
                raw = await self._redis.get(redis_key)
                if raw:
                    d = json.loads(raw)
                    logs = d.get("logs", []) if isinstance(d, dict) else []
            except Exception:
                pass

        if not logs:
            # 尝试旧 key 格式（auto_checkpoint）
            cp_key = self._redis.key("task", task_id, "auto_checkpoint")
            val = await self._redis.get(cp_key)
            if not val:
                return None
            try:
                d = json.loads(val)
                return AutoCheckpoint(**d)
            except Exception:
                return None

        # 从追踪记录中提取 modified_files 和 read_files（去重）
        modified_set: Dict[str, bool] = {}
        read_set: Dict[str, bool] = {}
        last_tool = ""

        for r in logs:
            fp = r.get("file_path", "")
            action = r.get("action", "")
            if fp:
                if action in ("write", "edit"):
                    modified_set[fp] = True
                elif action == "read":
                    read_set[fp] = True
            last_tool = r.get("brief", r.get("tool_name", ""))

        return AutoCheckpoint(
            task_id=task_id,
            agent_id=agent_id,
            modified_files=list(modified_set.keys()),
            read_files=list(read_set.keys()),
            tool_call_count=len(logs),
            last_tool_call=last_tool,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    async def _auto_save_checkpoint(self, task_id: str, agent_id: str) -> None:
        """从工具调用追踪数据自动保存检查点（中断时调用）。"""
        key = f"{task_id}:{agent_id}"
        records = self._tool_calls.get(key, [])
        modified_files = []
        read_files = []
        for r in records:
            action = r.get("action", "")
            fp = r.get("file_path", "")
            if not fp:
                continue
            if action in ("write", "edit"):
                if fp not in modified_files:
                    modified_files.append(fp)
            elif action == "read":
                if fp not in read_files:
                    read_files.append(fp)

        cp = AutoCheckpoint(
            task_id=task_id,
            agent_id=agent_id,
            modified_files=modified_files,
            read_files=read_files,
            tool_call_count=len(records),
            last_tool_call=records[-1].get("tool_name", "") if records else "",
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        cp_key = self._redis.key("task", task_id, "auto_checkpoint")
        try:
            await self._redis.set(cp_key, json.dumps(cp.to_dict()), ex=86400 * 7)
        except Exception:
            pass

    async def _auto_save_checkpoint_on_interrupt(self, task_id: str, agent_id: str) -> None:
        """
        中断时自动从工具调用追踪数据生成检查点并保存。
        对应 Go 的 autoSaveCheckpointOnInterrupt。
        如果已有手动检查点，则合并 modified_files。
        """
        key = f"{task_id}:{agent_id}"
        records = self._tool_calls.get(key, [])

        auto_modified = []
        auto_read = []
        for r in records:
            action = r.get("action", "")
            fp = r.get("file_path", "")
            if not fp:
                continue
            if action in ("write", "edit") and fp not in auto_modified:
                auto_modified.append(fp)
            elif action == "read" and fp not in auto_read:
                auto_read.append(fp)

        if not records and not auto_modified:
            return

        # 检查是否已有手动保存的检查点（手动优先，不覆盖）
        existing_cp = await self.get_checkpoint_async(task_id)
        if existing_cp and existing_cp.modified_files:
            # 合并 modified_files
            merged = list({f for f in existing_cp.modified_files + auto_modified})
            existing_cp.modified_files = merged
            existing_cp.notes = (
                f"{existing_cp.notes} "
                f"[自动追踪补充: {len(records)}次工具调用, "
                f"最后操作: {records[-1].get('brief', '') if records else ''}]"
            )
            cp_key = self._redis.key("task", task_id, "checkpoint")
            try:
                await self._redis.set(cp_key, json.dumps(existing_cp.to_dict()), ex=86400 * 7)
                self._logger.info(f"中断时自动合并追踪数据到检查点 task={task_id}")
            except Exception:
                pass
            return

        # 没有手动检查点，创建自动检查点
        data = await self._redis.hgetall(self._redis.key("task", task_id))
        progress = float(data.get("progress", 0)) if data else 0.0
        last_brief = records[-1].get("brief", "") if records else ""

        cp = Checkpoint(
            task_id=task_id,
            agent_id=agent_id,
            progress=progress,
            completed_items=[],
            pending_items=[],
            modified_files=auto_modified,
            notes=(
                f"[自动追踪生成] {len(records)}次工具调用, "
                f"读取{len(auto_read)}个文件, "
                f"修改{len(auto_modified)}个文件, "
                f"最后操作: {last_brief}"
            ),
            saved_at=datetime.now(timezone.utc).isoformat(),
        )
        cp_key = self._redis.key("task", task_id, "checkpoint")
        try:
            await self._redis.set(cp_key, json.dumps(cp.to_dict()), ex=86400 * 7)
        except Exception:
            pass

        # 同时保存完整的自动检查点
        auto_cp = AutoCheckpoint(
            task_id=task_id,
            agent_id=agent_id,
            modified_files=auto_modified,
            read_files=auto_read,
            tool_call_count=len(records),
            last_tool_call=last_brief,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        auto_key = self._redis.key("task", task_id, "auto_checkpoint")
        try:
            await self._redis.set(auto_key, json.dumps(auto_cp.to_dict()), ex=86400 * 7)
        except Exception:
            pass

        self._logger.info(
            f"中断时自动生成检查点 task={task_id} "
            f"tool_calls={len(records)} "
            f"modified_files={len(auto_modified)} "
            f"read_files={len(auto_read)}"
        )

    # ── Recovery ──────────────────────────────────────────────────────────────

    async def recover_interrupted_tasks(self, agent_id: str, skill_type: str = "",
                                         goal_id: str = "") -> Tuple[Optional[Task], Optional[Checkpoint]]:
        """
        查找最近的中断任务。
        优先恢复同一 Agent 之前中断的任务，其次是同一 goal 下的任务。
        对应 Go 的 RecoverInterruptedTasks。
        """
        queue = self._redis.key("task", "queue", TaskStatus.INTERRUPTED)
        members = await self._redis.zrangebyscore(queue, "-inf", "+inf")

        # 第一轮：同一 Agent
        for task_id in members:
            data = await self._redis.hgetall(self._redis.key("task", task_id))
            if not data:
                continue
            if data.get("claimed_by") != agent_id:
                continue
            if skill_type and data.get("skill_type") != skill_type:
                continue
            t = self._map_to_task(data)
            cp = await self.get_checkpoint_async(task_id)
            return t, cp

        # 第二轮：同一 goal
        if goal_id:
            for task_id in members:
                data = await self._redis.hgetall(self._redis.key("task", task_id))
                if not data:
                    continue
                if data.get("goal_id") != goal_id:
                    continue
                t = self._map_to_task(data)
                cp = await self.get_checkpoint_async(task_id)
                return t, cp

        return None, None

    async def resume_interrupted_task(self, task_id: str, agent_id: str) -> Task:
        now = datetime.now(timezone.utc).isoformat()
        await self._redis.hset(self._redis.key("task", task_id), {
            "status": TaskStatus.RUNNING,
            "claimed_by": agent_id,
            "updated_at": now,
        })
        await self._redis.zrem(self._redis.key("task", "queue", TaskStatus.INTERRUPTED), task_id)
        await self._redis.zadd(
            self._redis.key("task", "queue", TaskStatus.RUNNING),
            {task_id: float(time.time())},
        )
        # Re-acquire lock
        lock_key = self._redis.key("lock", "task", task_id)
        await self._redis.set(lock_key, agent_id, ex=self._cfg.heartbeat_timeout)
        self.touch_heartbeat(agent_id)
        # Record event
        if self._sqlite:
            data = await self._redis.hgetall(self._redis.key("task", task_id))
            progress = float(data.get("progress", 0)) if data else 0.0
            try:
                await self._sqlite.record_recovery_event(
                    task_id, agent_id, "resumed",
                    f"Agent {agent_id} 恢复执行中断任务（从进度 {progress:.1f}% 继续）",
                    progress
                )
            except Exception:
                pass
        data = await self._redis.hgetall(self._redis.key("task", task_id))
        return self._map_to_task(data) if data else Task(id=task_id)

    # ── Tool call audit ───────────────────────────────────────────────────────

    async def archive_and_clear_tool_call_logs(self, agent_id: str, task_id: str) -> None:
        """先归档工具调用日志到 SQLite，然后清理 Redis 中的日志。"""
        key = f"{task_id}:{agent_id}"
        records = self._tool_calls.pop(key, [])

        # 从 Redis 补充（可能有比内存更完整的记录）
        redis_key = self._redis.key("task", task_id, "tool_call_logs")
        if not records and self._sqlite:
            try:
                raw = await self._redis.get(redis_key)
                if raw:
                    d = json.loads(raw)
                    redis_logs = d.get("logs", []) if isinstance(d, dict) else []
                    if len(redis_logs) > len(records):
                        records = redis_logs
            except Exception:
                pass

        if records and self._sqlite:
            rows = [{"task_id": task_id, "agent_id": agent_id, **r} for r in records]
            try:
                await self._sqlite.archive_tool_call_logs(rows)
            except Exception as e:
                self._logger.error(f"归档工具调用日志失败: {e}")
        try:
            await self._redis.delete(redis_key)
            await self._redis.delete(self._redis.key("task", task_id, "auto_checkpoint"))
        except Exception:
            pass

    def clear_tool_call_logs(self, agent_id: str, task_id: str) -> None:
        key = f"{task_id}:{agent_id}"
        self._tool_calls.pop(key, None)

    async def record_task_completion_event(self, task_id: str, agent_id: str,
                                            status: str, summary: str) -> None:
        """记录任务完成/失败事件（仅当任务曾经被中断过时才记录）。"""
        if not self._sqlite:
            return
        # 检查该任务是否有中断历史
        snapshot_key = self._redis.key("task", task_id, "interrupt_snapshot")
        try:
            snapshot_exists = await self._redis.get(snapshot_key)
            if not snapshot_exists:
                # 也查询 SQLite 中是否有恢复事件记录
                events = await self._sqlite.query_recovery_events(
                    task_id=task_id, limit=1
                ) if hasattr(self._sqlite, "query_recovery_events") else []
                if not events:
                    return  # 该任务没有经历过中断，不需要记录
        except Exception:
            pass

        try:
            data = await self._redis.hgetall(self._redis.key("task", task_id))
            progress = float(data.get("progress", 0)) if data else 0.0
            if status == TaskStatus.COMPLETED:
                event_type = "completed"
                detail = f"Agent {agent_id} 完成任务（进度 {progress:.1f}%）：{summary[:200]}"
            elif status == "failed":
                event_type = "failed"
                detail = f"Agent {agent_id} 任务失败（进度 {progress:.1f}%）：{summary[:200]}"
            else:
                event_type = f"ended_{status}"
                detail = f"Agent {agent_id} 任务结束 status={status}（进度 {progress:.1f}%）：{summary[:200]}"
            await self._sqlite.record_recovery_event(
                task_id, agent_id, event_type, detail, progress
            )
        except Exception:
            pass

    def _map_to_task(self, data: Dict) -> Task:
        from .model import Task, TaskStatus
        deps = []
        if d := data.get("dependencies"):
            try:
                deps = json.loads(d)
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
            claimed_by=data.get("claimed_by", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            interrupted_at=data.get("interrupted_at", ""),
        )
