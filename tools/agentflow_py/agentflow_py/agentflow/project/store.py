"""项目存储层 - 移植自 Go 的 internal/project/store.go"""
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

from agentflow.storage import RedisClient
from agentflow.namespace import NamespaceManager
from agentflow.common.errors import NotFoundError, InvalidParamError
from agentflow.common.id_gen import (
    generate_project_id,
    generate_phase_gate_id,
    generate_phase_history_id,
)
from agentflow.project.model import (
    Project,
    PhaseGate,
    PhaseGoalLink,
    PhaseHistory,
    PhaseProgress,
    PhaseOverview,
    GoalWithTasks,
    TaskWithStatus,
    PhaseInfo,
    EntryCondition,
    ExitCondition,
    Deliverable,
    HumanFeedback,
    ProjectStatus,
    PhaseGateStatus,
    PhaseGoalLinkStatus,
    PhaseStatus,
    LinkType,
)


class ProjectStore:
    """项目存储类"""

    def __init__(self, redis: RedisClient, logger: logging.Logger, ns_mgr: NamespaceManager,
                 task_store: Optional[Any] = None):
        self._redis = redis
        self._logger = logger
        self._ns_mgr = ns_mgr
        self._task_store = task_store  # 可选注入，用于 _calculate_phase_progress 获取真实任务状态

    def _key(self, *parts: str, namespace: str = "") -> str:
        """生成带命名空间的 Redis key"""
        return self._redis.key(*parts, namespace=namespace)

    # ---- Project CRUD ----

    async def create_project(
        self,
        title: str,
        description: str = "",
        vision: str = "",
        template: str = "standard",
        priority: int = 5,
        tags: Optional[List[str]] = None,
    ) -> Project:
        """创建项目"""
        if not title:
            raise InvalidParamError("title 不能为空")
        
        if priority < 1 or priority > 10:
            priority = 5

        now = datetime.now().isoformat()
        project = Project(
            id=generate_project_id(),
            title=title,
            description=description,
            vision=vision,
            status=ProjectStatus.DRAFT,
            tags=tags or [],
            priority=priority,
            created_at=now,
            updated_at=now,
        )

        # 初始化阶段
        project.phases = self._init_phases_from_template(template)

        key = self._key("project", project.id)
        data = self._project_to_map(project)

        # 使用 pipeline 保证原子性
        pipe = self._redis.pipeline()
        pipe.hset(key, data)
        pipe.zadd(
            self._key("project", "list"),
            {project.id: project.priority}
        )
        await pipe.execute()

        # 创建各阶段的 PhaseGate
        for phase in project.phases:
            await self._create_phase_gate_internal(project.id, phase.name)

        self._logger.info(f"项目已创建 id={project.id} title={project.title}")
        return project

    async def get_project(self, project_id: str) -> Project:
        """获取项目详情"""
        key = self._key("project", project_id)
        data = await self._redis.hgetall(key)
        
        if not data:
            raise NotFoundError(f"project {project_id} 不存在")
        
        return self._map_to_project(data)

    async def update_project(self, project_id: str, fields: Dict[str, Any]) -> Project:
        """更新项目"""
        key = self._key("project", project_id)
        
        exists = await self._redis.exists(key)
        if not exists:
            raise NotFoundError(f"project {project_id} 不存在")

        updates = {}
        for k, v in fields.items():
            if k in ("title", "description", "vision", "status", "current_phase", "owner_agent_id"):
                updates[k] = v
            elif k == "priority":
                updates[k] = str(v)
                # 更新优先级排序
                await self._redis.zadd(
                    self._key("project", "list"),
                    {project_id: v}
                )
            elif k == "tags":
                if isinstance(v, list):
                    updates[k] = json.dumps(v, ensure_ascii=False)
            elif k == "risk_list":
                if isinstance(v, list):
                    updates[k] = json.dumps(v, ensure_ascii=False)
            elif k == "tech_stack":
                if isinstance(v, list):
                    updates[k] = json.dumps(v, ensure_ascii=False)
            elif k == "phases":
                if isinstance(v, list):
                    updates[k] = json.dumps([p.to_dict() if hasattr(p, 'to_dict') else p for p in v], ensure_ascii=False)
        
        updates["updated_at"] = datetime.now().isoformat()

        if updates:
            await self._redis.hset(key, updates)

        return await self.get_project(project_id)

    async def delete_project(self, project_id: str, cascade: bool = False) -> None:
        """删除项目"""
        key = self._key("project", project_id)
        
        exists = await self._redis.exists(key)
        if not exists:
            raise NotFoundError(f"project {project_id} 不存在")

        pipe = self._redis.pipeline()
        pipe.delete(key)
        pipe.delete(self._key("project", project_id, "goals"))
        pipe.delete(self._key("project", project_id, "history"))
        pipe.zrem(self._key("project", "list"), project_id)

        # 删除所有 PhaseGate 和相关数据
        gates = await self.list_phase_gates(project_id)
        for gate in gates:
            pipe.delete(self._key("project", project_id, "gate", gate.phase_name))
            pipe.delete(self._key("project", project_id, "phase", gate.phase_name, "goal_links"))
            pipe.delete(self._key("project", project_id, "phase", gate.phase_name, "tasks"))
        
        pipe.delete(self._key("project", project_id, "phases"))

        await pipe.execute()
        self._logger.info(f"项目已删除 id={project_id} cascade={cascade}")

    async def list_projects(
        self,
        status: str = "",
        tags: Optional[List[str]] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[Project], int]:
        """项目列表查询"""
        if page < 1:
            page = 1
        if page_size < 1 or page_size > 100:
            page_size = 20

        list_key = self._key("project", "list")
        total = await self._redis.zcard(list_key)

        has_filter = bool(status) or bool(tags)
        
        if has_filter:
            # 需要过滤时获取全部
            members = await self._redis.zrange_withscores(list_key, 0, -1)
        else:
            start = (page - 1) * page_size
            stop = start + page_size - 1
            members = await self._redis.zrevrange_withscores(list_key, start, stop)

        all_filtered = []
        for member, score in members:
            project_id = member
            try:
                project = await self.get_project(project_id)
            except NotFoundError:
                continue

            # 状态过滤
            if status and project.status != status:
                continue

            # 标签过滤
            if tags:
                matched = False
                for filter_tag in tags:
                    for project_tag in project.tags:
                        if filter_tag.lower() == project_tag.lower():
                            matched = True
                            break
                    if matched:
                        break
                if not matched:
                    continue

            all_filtered.append(project)

        filtered_total = len(all_filtered)
        
        if has_filter:
            # 过滤后分页
            start = (page - 1) * page_size
            end = start + page_size
            if start >= len(all_filtered):
                return [], filtered_total
            return all_filtered[start:end], filtered_total

        return all_filtered, total

    # ---- PhaseGate CRUD ----

    async def _create_phase_gate_internal(
        self,
        project_id: str,
        phase_name: str,
        entry_conditions: Optional[List[EntryCondition]] = None,
        exit_conditions: Optional[List[ExitCondition]] = None,
    ) -> PhaseGate:
        """内部方法：创建阶段门控"""
        gate = PhaseGate(
            id=generate_phase_gate_id(),
            project_id=project_id,
            phase_name=phase_name,
            status=PhaseGateStatus.PENDING,
            entry_conditions=entry_conditions or [],
            exit_conditions=exit_conditions or [],
            created_at=datetime.now().isoformat(),
        )

        gate_json = json.dumps(gate.to_dict(), ensure_ascii=False)

        pipe = self._redis.pipeline()
        pipe.set(self._key("project", project_id, "gate", phase_name), gate_json)
        pipe.rpush(self._key("project", project_id, "phases"), phase_name)
        await pipe.execute()

        self._logger.info(f"PhaseGate已创建 project_id={project_id} phase={phase_name}")
        return gate

    async def save_phase_gate(self, gate: PhaseGate) -> PhaseGate:
        """保存阶段门控（创建或更新）"""
        gate_json = json.dumps(gate.to_dict(), ensure_ascii=False)
        await self._redis.set(
            self._key("project", gate.project_id, "gate", gate.phase_name),
            gate_json
        )
        return gate

    async def get_phase_gate(self, project_id: str, phase_name: str) -> PhaseGate:
        """获取阶段门控"""
        key = self._key("project", project_id, "gate", phase_name)
        val = await self._redis.get(key)
        
        if not val:
            raise NotFoundError(f"gate {project_id}/{phase_name} 不存在")

        data = json.loads(val)
        return self._dict_to_phase_gate(data)

    async def list_phase_gates(self, project_id: str) -> List[PhaseGate]:
        """获取项目所有阶段门控"""
        phase_names = await self._redis.lrange(
            self._key("project", project_id, "phases"), 0, -1
        )

        gates = []
        for phase_name in phase_names:
            try:
                gate = await self.get_phase_gate(project_id, phase_name)
                gates.append(gate)
            except NotFoundError:
                self._logger.warning(f"获取PhaseGate失败 project_id={project_id} phase={phase_name}")
                continue

        return gates

    async def get_goal_phase_links(self, goal_id: str) -> List[Dict[str, str]]:
        """查找某个 Goal 关联的所有 (project_id, phase_name) 对。
        
        通过扫描 project_list 中的所有项目，找到 linked_goal_ids 包含该 goal_id 的 PhaseGate。
        返回 [{"project_id": ..., "phase_name": ...}, ...]
        """
        result = []
        try:
            project_ids = await self._redis.zrangebyscore(
                self._key("project", "list"), "-inf", "+inf"
            )
            for project_id in project_ids:
                gates = await self.list_phase_gates(project_id)
                for gate in gates:
                    if goal_id in gate.linked_goal_ids:
                        result.append({
                            "project_id": project_id,
                            "phase_name": gate.phase_name,
                            "gate": gate,
                        })
        except Exception as e:
            self._logger.warning(f"get_goal_phase_links 扫描失败 goal_id={goal_id}: {e}")
        return result

    # ---- Phase 管理 ----

    async def create_phase(
        self,
        project_id: str,
        name: str,
        description: str = "",
        parent_phase: str = "",
    ) -> PhaseInfo:
        """创建阶段"""
        project = await self.get_project(project_id)
        
        # 计算 order
        max_order = max([p.order for p in project.phases], default=-1)
        
        phase = PhaseInfo(
            name=name,
            description=description,
            order=max_order + 1,
            status=PhaseStatus.PENDING,
            parent_phase=parent_phase,
        )

        project.phases.append(phase)
        
        # 更新项目
        await self.update_project(project_id, {"phases": project.phases})
        
        # 创建 PhaseGate
        await self._create_phase_gate_internal(project_id, name)

        return phase

    async def remove_phase(self, project_id: str, phase_name: str) -> None:
        """移除阶段"""
        project = await self.get_project(project_id)
        
        # 从项目 phases 中移除
        project.phases = [p for p in project.phases if p.name != phase_name]
        await self.update_project(project_id, {"phases": project.phases})

        # 删除 PhaseGate 及相关数据
        pipe = self._redis.pipeline()
        pipe.delete(self._key("project", project_id, "gate", phase_name))
        pipe.delete(self._key("project", project_id, "phase", phase_name, "goal_links"))
        pipe.delete(self._key("project", project_id, "phase", phase_name, "tasks"))
        pipe.lrem(self._key("project", project_id, "phases"), 0, phase_name)
        await pipe.execute()

        self._logger.info(f"阶段已移除 project_id={project_id} phase={phase_name}")

    async def update_phase(
        self,
        project_id: str,
        phase_name: str,
        fields: Dict[str, Any],
    ) -> PhaseInfo:
        """更新阶段"""
        project = await self.get_project(project_id)
        
        for phase in project.phases:
            if phase.name == phase_name:
                for k, v in fields.items():
                    if hasattr(phase, k):
                        setattr(phase, k, v)
                break
        else:
            raise NotFoundError(f"phase {phase_name} 不存在")

        await self.update_project(project_id, {"phases": project.phases})
        
        # 返回更新后的 phase
        for phase in project.phases:
            if phase.name == phase_name:
                return phase
        
        raise NotFoundError(f"phase {phase_name} 不存在")

    # ---- Goal/Task 关联 ----

    async def link_goal_to_phase(
        self,
        project_id: str,
        phase_name: str,
        goal_id: str,
        link_type: str = LinkType.MANUAL_LINKED,
    ) -> PhaseGoalLink:
        """关联 Goal 到 Phase"""
        link = PhaseGoalLink(
            project_id=project_id,
            phase_name=phase_name,
            goal_id=goal_id,
            link_type=link_type,
            status=PhaseGoalLinkStatus.PENDING,
            linked_at=datetime.now().isoformat(),
        )

        link_json = json.dumps(link.to_dict(), ensure_ascii=False)
        key = self._key("project", project_id, "phase", phase_name, "goal_links")
        await self._redis.rpush(key, link_json)

        # 同时更新 PhaseGate 的 LinkedGoalIDs
        try:
            gate = await self.get_phase_gate(project_id, phase_name)
            if goal_id not in gate.linked_goal_ids:
                gate.linked_goal_ids.append(goal_id)
                await self.save_phase_gate(gate)
        except NotFoundError:
            pass

        self._logger.info(f"Goal已关联到Phase project_id={project_id} phase={phase_name} goal_id={goal_id}")
        return link

    async def unlink_goal_from_phase(
        self,
        project_id: str,
        phase_name: str,
        goal_id: str,
    ) -> None:
        """取消 Goal 与 Phase 的关联"""
        links = await self._get_phase_goal_links(project_id, phase_name)
        
        key = self._key("project", project_id, "phase", phase_name, "goal_links")
        await self._redis.delete(key)

        for link in links:
            if link.goal_id == goal_id:
                continue  # 跳过要删除的
            link_json = json.dumps(link.to_dict(), ensure_ascii=False)
            await self._redis.rpush(key, link_json)

        # 更新 PhaseGate 的 LinkedGoalIDs
        try:
            gate = await self.get_phase_gate(project_id, phase_name)
            gate.linked_goal_ids = [id for id in gate.linked_goal_ids if id != goal_id]
            await self.save_phase_gate(gate)
        except NotFoundError:
            pass

    async def link_task_to_phase(
        self,
        project_id: str,
        phase_name: str,
        goal_id: str,
        task_id: str,
    ) -> None:
        """关联 Task 到 Phase"""
        # 更新 goal_links 中对应 Goal 的 TaskIDs
        links = await self._get_phase_goal_links(project_id, phase_name)

        key = self._key("project", project_id, "phase", phase_name, "goal_links")
        await self._redis.delete(key)

        for link in links:
            if link.goal_id == goal_id:
                if task_id not in link.task_ids:
                    link.task_ids.append(task_id)
            link_json = json.dumps(link.to_dict(), ensure_ascii=False)
            await self._redis.rpush(key, link_json)

        # 同时更新 Phase 的 tasks 列表
        tasks_key = self._key("project", project_id, "phase", phase_name, "tasks")
        await self._redis.rpush(tasks_key, task_id)

        # 更新 PhaseGate 的 LinkedTaskIDs
        try:
            gate = await self.get_phase_gate(project_id, phase_name)
            if task_id not in gate.linked_task_ids:
                gate.linked_task_ids.append(task_id)
                await self.save_phase_gate(gate)
        except NotFoundError:
            pass

    async def unlink_task_from_phase(
        self,
        project_id: str,
        phase_name: str,
        task_id: str,
    ) -> None:
        """取消 Task 与 Phase 的关联"""
        # 从 goal_links 中移除该 taskID
        links = await self._get_phase_goal_links(project_id, phase_name)

        key = self._key("project", project_id, "phase", phase_name, "goal_links")
        # 使用 pipeline 保证 delete + rpush 的原子性，避免并发风险
        async with self._redis.pipeline() as pipe:
            pipe.delete(key)
            for link in links:
                link.task_ids = [tid for tid in link.task_ids if tid != task_id]
                link_json = json.dumps(link.to_dict(), ensure_ascii=False)
                pipe.rpush(key, link_json)
            await pipe.execute()

        # 从 Phase tasks 列表中移除
        tasks_key = self._key("project", project_id, "phase", phase_name, "tasks")
        task_ids = await self._get_phase_task_ids(project_id, phase_name)
        async with self._redis.pipeline() as pipe:
            pipe.delete(tasks_key)
            for tid in task_ids:
                if tid != task_id:
                    pipe.rpush(tasks_key, tid)
            await pipe.execute()

        # 更新 PhaseGate 的 LinkedTaskIDs
        try:
            gate = await self.get_phase_gate(project_id, phase_name)
            gate.linked_task_ids = [id for id in gate.linked_task_ids if id != task_id]
            await self.save_phase_gate(gate)
        except NotFoundError:
            pass

    async def bind_condition_to_task(
        self,
        project_id: str,
        phase_name: str,
        condition_index: int,
        task_id: str = "",
        goal_id: str = "",
        auto_check: bool = True,
    ) -> None:
        """绑定准出条件到 Task 或 Goal"""
        gate = await self.get_phase_gate(project_id, phase_name)

        if condition_index < 0 or condition_index >= len(gate.exit_conditions):
            raise InvalidParamError(f"condition index {condition_index} 超出范围")

        if task_id:
            gate.exit_conditions[condition_index].bound_task_id = task_id
        if goal_id:
            gate.exit_conditions[condition_index].bound_goal_id = goal_id
        gate.exit_conditions[condition_index].auto_check = auto_check

        await self.save_phase_gate(gate)

    # ---- Phase 概览和进度 ----

    async def get_phase_overview(
        self,
        project_id: str,
        phase_name: str,
        goal_provider: Optional[Any] = None,
        task_provider: Optional[Any] = None,
    ) -> PhaseOverview:
        """获取 Phase 概览（包含关联的 Goal/Task 完整信息）"""
        links = await self._get_phase_goal_links(project_id, phase_name)
        
        goals = []
        for link in links:
            goal_with_tasks = GoalWithTasks(
                goal_id=link.goal_id,
                title="",  # 需要外部提供
                status="pending",
                progress=0.0,
            )
            
            # 获取 Task 列表
            for task_id in link.task_ids:
                task = TaskWithStatus(
                    task_id=task_id,
                    status="pending",
                    progress=0.0,
                )
                goal_with_tasks.tasks.append(task)
            
            goal_with_tasks.total_tasks = len(goal_with_tasks.tasks)
            goals.append(goal_with_tasks)

        # 计算进度
        progress = await self._calculate_phase_progress(project_id, phase_name, links)

        return PhaseOverview(
            project_id=project_id,
            phase_name=phase_name,
            goals=goals,
            progress=progress,
        )

    async def generate_phase_summary(self, project_id: str, phase_name: str) -> str:
        """生成阶段总结"""
        overview = await self.get_phase_overview(project_id, phase_name)
        
        lines = [
            f"## Phase 总结: {phase_name}",
            f"",
            f"**进度**: {overview.progress.percentage:.1f}%",
            f"**Goals**: {overview.progress.completed_goals}/{overview.progress.total_goals} 完成",
            f"**Tasks**: {overview.progress.completed_tasks}/{overview.progress.total_tasks} 完成",
            f"",
            f"### 关联 Goals",
        ]
        
        for goal in overview.goals:
            lines.append(f"- {goal.goal_id}: {goal.title or '(未命名)'} ({goal.status})")
            for task in goal.tasks:
                lines.append(f"  - {task.task_id}: {task.title or '(未命名)'} ({task.status})")
        
        return "\n".join(lines)

    # ---- 历史记录 ----

    async def add_phase_history(self, entry: PhaseHistory) -> None:
        """添加阶段历史记录"""
        if not entry.id:
            entry.id = generate_phase_history_id()
        if not entry.created_at:
            entry.created_at = datetime.now().isoformat()
            
        entry_json = json.dumps(entry.to_dict(), ensure_ascii=False)
        await self._redis.rpush(
            self._key("project", entry.project_id, "history"),
            entry_json
        )

    async def get_phase_history(self, project_id: str) -> List[PhaseHistory]:
        """获取阶段历史记录"""
        items = await self._redis.lrange(
            self._key("project", project_id, "history"), 0, -1
        )

        history = []
        for item in items:
            try:
                data = json.loads(item)
                history.append(self._dict_to_phase_history(data))
            except json.JSONDecodeError as e:
                self._logger.warning(f"反序列化历史记录失败 error={e}")
                continue

        return history

    # ---- 内部辅助方法 ----

    def _init_phases_from_template(self, template: str) -> List[PhaseInfo]:
        """从模板初始化阶段"""
        templates = {
            "standard": [
                ("idea", "想法阶段", 0),
                ("macro", "宏观补充", 1),
                ("research", "调研阶段", 2),
                ("mvp", "MVP阶段", 3),
                ("p1", "P1阶段", 4),
                ("p2", "P2阶段", 5),
            ],
            "simple": [
                ("plan", "规划阶段", 0),
                ("execute", "执行阶段", 1),
                ("review", "评审阶段", 2),
            ],
        }
        
        phase_defs = templates.get(template, templates["standard"])
        
        return [
            PhaseInfo(
                name=name,
                description=desc,
                order=order,
                status=PhaseStatus.PENDING,
            )
            for name, desc, order in phase_defs
        ]

    def _project_to_map(self, project: Project) -> Dict[str, str]:
        """Project 转 Dict（用于 Redis Hash 存储）"""
        return {
            "id": project.id,
            "title": project.title,
            "description": project.description,
            "vision": project.vision,
            "status": project.status,
            "current_phase": project.current_phase,
            "owner_agent_id": project.owner_agent_id,
            "priority": str(project.priority),
            "tags": json.dumps(project.tags, ensure_ascii=False),
            "risk_list": json.dumps(project.risk_list, ensure_ascii=False),
            "tech_stack": json.dumps(project.tech_stack, ensure_ascii=False),
            "phases": json.dumps([p.to_dict() for p in project.phases], ensure_ascii=False),
            "created_at": project.created_at,
            "updated_at": project.updated_at,
        }

    def _map_to_project(self, data: Dict[str, str]) -> Project:
        """Dict 转 Project"""
        project = Project(
            id=data.get("id", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            vision=data.get("vision", ""),
            status=data.get("status", ProjectStatus.DRAFT),
            current_phase=data.get("current_phase", ""),
            owner_agent_id=data.get("owner_agent_id", ""),
        )

        # 解析 priority
        try:
            project.priority = int(data.get("priority", "5"))
        except ValueError:
            project.priority = 5

        # 解析时间
        project.created_at = data.get("created_at", "")
        project.updated_at = data.get("updated_at", "")

        # 解析 JSON 字段
        try:
            project.tags = json.loads(data.get("tags", "[]"))
        except json.JSONDecodeError:
            project.tags = []

        try:
            project.risk_list = json.loads(data.get("risk_list", "[]"))
        except json.JSONDecodeError:
            project.risk_list = []

        try:
            project.tech_stack = json.loads(data.get("tech_stack", "[]"))
        except json.JSONDecodeError:
            project.tech_stack = []

        try:
            phases_data = json.loads(data.get("phases", "[]"))
            project.phases = [self._dict_to_phase_info(p) for p in phases_data]
        except json.JSONDecodeError:
            project.phases = []

        return project

    def _dict_to_phase_info(self, data: Dict) -> PhaseInfo:
        """Dict 转 PhaseInfo"""
        phase = PhaseInfo(
            name=data.get("name", ""),
            description=data.get("description", ""),
            order=data.get("order", 0),
            status=data.get("status", PhaseStatus.PENDING),
            parent_phase=data.get("parent_phase", ""),
        )
        
        if "children" in data:
            phase.children = [self._dict_to_phase_info(c) for c in data["children"]]
        
        return phase

    def _dict_to_phase_gate(self, data: Dict) -> PhaseGate:
        """Dict 转 PhaseGate"""
        gate = PhaseGate(
            id=data.get("id", ""),
            project_id=data.get("project_id", ""),
            phase_name=data.get("phase_name", ""),
            status=data.get("status", PhaseGateStatus.PENDING),
            reviewer_comment=data.get("reviewer_comment", ""),
            approved_by=data.get("approved_by", ""),
            approved_at=data.get("approved_at", ""),
            created_at=data.get("created_at", ""),
        )

        # 解析 entry_conditions
        gate.entry_conditions = [
            EntryCondition(
                description=c.get("description", ""),
                is_met=c.get("is_met", False),
            )
            for c in data.get("entry_conditions", [])
        ]

        # 解析 exit_conditions
        gate.exit_conditions = [
            ExitCondition(
                description=c.get("description", ""),
                is_met=c.get("is_met", False),
                bound_goal_id=c.get("bound_goal_id", ""),
                bound_task_id=c.get("bound_task_id", ""),
                auto_check=c.get("auto_check", False),
            )
            for c in data.get("exit_conditions", [])
        ]

        # 解析 deliverables
        gate.deliverables = [
            Deliverable(
                name=d.get("name", ""),
                description=d.get("description", ""),
                content=d.get("content", ""),
                is_completed=d.get("is_completed", False),
            )
            for d in data.get("deliverables", [])
        ]

        # 解析 human_feedback
        if "human_feedback" in data and data["human_feedback"]:
            fb = data["human_feedback"]
            gate.human_feedback = HumanFeedback(
                comment=fb.get("comment", ""),
                revision_items=fb.get("revision_items", []),
                metadata=fb.get("metadata", {}),
                submitted_at=fb.get("submitted_at", ""),
            )

        gate.linked_goal_ids = data.get("linked_goal_ids", [])
        gate.linked_task_ids = data.get("linked_task_ids", [])

        return gate

    def _dict_to_phase_history(self, data: Dict) -> PhaseHistory:
        """Dict 转 PhaseHistory"""
        return PhaseHistory(
            id=data.get("id", ""),
            project_id=data.get("project_id", ""),
            phase_name=data.get("phase_name", ""),
            action=data.get("action", ""),
            actor=data.get("actor", ""),
            comment=data.get("comment", ""),
            details=data.get("details", {}),
            created_at=data.get("created_at", ""),
        )

    async def _get_phase_goal_links(self, project_id: str, phase_name: str) -> List[PhaseGoalLink]:
        """获取 Phase 关联的所有 Goal 链接"""
        key = self._key("project", project_id, "phase", phase_name, "goal_links")
        items = await self._redis.lrange(key, 0, -1)

        links = []
        for item in items:
            try:
                data = json.loads(item)
                link = PhaseGoalLink(
                    project_id=data.get("project_id", ""),
                    phase_name=data.get("phase_name", ""),
                    goal_id=data.get("goal_id", ""),
                    task_ids=data.get("task_ids", []),
                    link_type=data.get("link_type", LinkType.AUTO_GENERATED),
                    linked_condition_index=data.get("linked_condition_index", -1),
                    linked_deliverable_index=data.get("linked_deliverable_index", -1),
                    status=data.get("status", PhaseGoalLinkStatus.PENDING),
                    linked_at=data.get("linked_at", ""),
                )
                links.append(link)
            except json.JSONDecodeError as e:
                self._logger.warning(f"反序列化 PhaseGoalLink 失败 error={e}")
                continue

        return links

    async def _get_phase_task_ids(self, project_id: str, phase_name: str) -> List[str]:
        """获取 Phase 下所有 Task ID"""
        key = self._key("project", project_id, "phase", phase_name, "tasks")
        return await self._redis.lrange(key, 0, -1)

    async def _calculate_phase_progress(
        self,
        project_id: str,
        phase_name: str,
        links: List[PhaseGoalLink],
    ) -> PhaseProgress:
        """计算 Phase 完成进度"""
        progress = PhaseProgress(
            project_id=project_id,
            phase_name=phase_name,
        )

        for link in links:
            progress.total_goals += 1
            if link.status == PhaseGoalLinkStatus.COMPLETED:
                progress.completed_goals += 1
            
            progress.total_tasks += len(link.task_ids)

            # 如果 task_store 可用，获取真实任务状态
            if self._task_store is not None:
                for task_id in link.task_ids:
                    try:
                        task = await self._task_store.get(task_id)
                        if task and getattr(task, 'status', '') == 'completed':
                            progress.completed_tasks += 1
                    except Exception:
                        pass  # 任务不存在时跳过
            # TODO: 未注入 task_store 时无法获取真实任务状态，请在初始化 ProjectStore 时注入 task_store

        if progress.total_tasks > 0:
            progress.percentage = (progress.completed_tasks / progress.total_tasks) * 100
        elif progress.total_goals > 0:
            progress.percentage = (progress.completed_goals / progress.total_goals) * 100

        return progress

    # ---- 额外的便捷方法 ----

    async def update_phase_gate_status(
        self,
        project_id: str,
        phase_name: str,
        status: str,
    ) -> PhaseGate:
        """更新 PhaseGate 状态"""
        gate = await self.get_phase_gate(project_id, phase_name)
        gate.status = status
        return await self.save_phase_gate(gate)

    async def add_deliverable(
        self,
        project_id: str,
        phase_name: str,
        deliverable: Deliverable,
    ) -> PhaseGate:
        """添加产出物到 PhaseGate"""
        gate = await self.get_phase_gate(project_id, phase_name)
        gate.deliverables.append(deliverable)
        return await self.save_phase_gate(gate)

    async def update_exit_condition(
        self,
        project_id: str,
        phase_name: str,
        condition_index: int,
        is_met: bool,
    ) -> PhaseGate:
        """更新准出条件状态"""
        gate = await self.get_phase_gate(project_id, phase_name)
        
        if 0 <= condition_index < len(gate.exit_conditions):
            gate.exit_conditions[condition_index].is_met = is_met
            
        return await self.save_phase_gate(gate)

    async def rename_phase_gate(
        self,
        project_id: str,
        old_name: str,
        new_name: str,
    ) -> None:
        """重命名阶段（迁移 PhaseGate 数据到新名称）"""
        # 获取旧 gate
        gate = await self.get_phase_gate(project_id, old_name)

        # 更新名称
        gate.phase_name = new_name
        gate_json = json.dumps(gate.to_dict(), ensure_ascii=False)

        pipe = self._redis.pipeline()
        # 写入新 key
        pipe.set(self._key("project", project_id, "gate", new_name), gate_json)
        # 删除旧 key
        pipe.delete(self._key("project", project_id, "gate", old_name))
        await pipe.execute()

        # 迁移 goal_links（重写到新 key）
        old_links_key = self._key("project", project_id, "phase", old_name, "goal_links")
        new_links_key = self._key("project", project_id, "phase", new_name, "goal_links")
        items = await self._redis.lrange(old_links_key, 0, -1)
        if items:
            pipe2 = self._redis.pipeline()
            pipe2.delete(new_links_key)
            for item in items:
                pipe2.rpush(new_links_key, item)
            pipe2.delete(old_links_key)
            await pipe2.execute()

        # 迁移 tasks（重写到新 key）
        old_tasks_key = self._key("project", project_id, "phase", old_name, "tasks")
        new_tasks_key = self._key("project", project_id, "phase", new_name, "tasks")
        task_ids = await self._redis.lrange(old_tasks_key, 0, -1)
        if task_ids:
            pipe3 = self._redis.pipeline()
            pipe3.delete(new_tasks_key)
            for tid in task_ids:
                pipe3.rpush(new_tasks_key, tid)
            pipe3.delete(old_tasks_key)
            await pipe3.execute()

        # 更新 phases 列表中的名称
        await self._redis.lrem(self._key("project", project_id, "phases"), 0, old_name)
        await self._redis.rpush(self._key("project", project_id, "phases"), new_name)

        self._logger.info(f"PhaseGate已重命名 project_id={project_id} old={old_name} new={new_name}")

    async def update_phase_goal_link_status(
        self,
        project_id: str,
        phase_name: str,
        goal_id: str,
        status: str,
    ) -> None:
        """更新 PhaseGoalLink 状态"""
        links = await self._get_phase_goal_links(project_id, phase_name)

        key = self._key("project", project_id, "phase", phase_name, "goal_links")
        await self._redis.delete(key)

        for link in links:
            if link.goal_id == goal_id:
                link.status = status
            link_json = json.dumps(link.to_dict(), ensure_ascii=False)
            await self._redis.rpush(key, link_json)

    async def get_phase_progress_with_statuses(
        self,
        project_id: str,
        phase_name: str,
        goal_statuses: Dict[str, str],
        task_statuses: Dict[str, str],
    ) -> PhaseProgress:
        """获取 Phase 完成进度（带外部注入的 Goal/Task 状态）"""
        links = await self._get_phase_goal_links(project_id, phase_name)

        progress = PhaseProgress(
            project_id=project_id,
            phase_name=phase_name,
        )

        for link in links:
            progress.total_goals += 1
            if goal_statuses.get(link.goal_id) == "completed":
                progress.completed_goals += 1
            for task_id in link.task_ids:
                progress.total_tasks += 1
                if task_statuses.get(task_id) == "completed":
                    progress.completed_tasks += 1

        if progress.total_tasks > 0:
            progress.percentage = (progress.completed_tasks / progress.total_tasks) * 100
        elif progress.total_goals > 0:
            progress.percentage = (progress.completed_goals / progress.total_goals) * 100

        return progress

    async def link_goal_to_project(
        self,
        project_id: str,
        goal_id: str,
        phase: str = "",
    ) -> None:
        """关联 Goal 到项目（记录 goal_id:phase 映射）"""
        key = self._key("project", project_id, "goals")
        entry = f"{goal_id}:{phase}" if phase else goal_id
        await self._redis.rpush(key, entry)

    async def get_project_goals(self, project_id: str) -> List[str]:
        """获取项目关联的 Goal 列表（返回 goal_id:phase 格式）"""
        return await self._redis.lrange(
            self._key("project", project_id, "goals"), 0, -1
        )

    async def delete_phase_gate(self, project_id: str, phase_name: str) -> None:
        """删除阶段门控及相关数据"""
        pipe = self._redis.pipeline()
        pipe.delete(self._key("project", project_id, "gate", phase_name))
        pipe.delete(self._key("project", project_id, "phase", phase_name, "goal_links"))
        pipe.delete(self._key("project", project_id, "phase", phase_name, "tasks"))
        # 从 phases 列表中移除
        pipe.lrem(self._key("project", project_id, "phases"), 0, phase_name)
        await pipe.execute()

        self._logger.info(f"PhaseGate已删除 project_id={project_id} phase={phase_name}")
