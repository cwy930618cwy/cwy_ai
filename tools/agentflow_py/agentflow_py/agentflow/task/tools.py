import logging
from typing import Any, Dict, Optional, Protocol

from agentflow.mcp_server import Registry, ToolDef, ToolLayer, new_json_result, new_error_result
from .store import TaskStore
from .watchdog import Watchdog


class ContextCompiler(Protocol):
    async def compile_for_claim(self, task_id: str, budget: int) -> tuple[str, int]: ...


def register_tools(registry: Registry, store: TaskStore, watchdog: Optional[Watchdog],
                   compiler: Optional[Any], logger: logging.Logger) -> None:

    registry.register(
        ToolDef(
            name="create_tasks",
            description="根据目标创建任务列表。每个任务可指定skill_type、依赖、预估Token和测试设计。",
            input_schema={
                "type": "object",
                "properties": {
                    "goal_id": {"type": "string"},
                    "tasks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "description": {"type": "string"},
                                "skill_type": {"type": "string"},
                                "phase": {"type": "string"},
                                "dependencies": {"type": "array", "items": {"type": "string"}},
                                "prerequisites": {"type": "array", "items": {"type": "string"}},
                                "estimated_tokens": {"type": "integer"},
                                "difficulty": {"type": "integer", "minimum": 1, "maximum": 10},
                                "test_design": {"type": "object"},
                            },
                            "required": ["title", "description"],
                        },
                    },
                },
                "required": ["goal_id", "tasks"],
            },
            layer=ToolLayer.LAYER1,
        ),
        _make_create_tasks_handler(store),
    )

    registry.register(
        ToolDef(
            name="claim_task",
            description=(
                "原子认领任务。task_id可选(不填则智能派发)。"
                "claim成功时自动编译并返回精准上下文(compiled_context字段)。"
                "智能派发优先级: interrupted > blocked > failed > pending。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string"},
                    "task_id": {"type": "string"},
                    "skill_types": {"type": "array", "items": {"type": "string"}},
                    "affinity_skills": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Agent 历史擅长的 skill_type 列表，命中时综合得分 +5（亲和性调度）",
                    },
                    "max_difficulty": {"type": "integer", "minimum": 0, "maximum": 10},
                    "strict_skill": {"type": "boolean", "default": False},
                },
                "required": ["agent_id"],
            },
            layer=ToolLayer.LAYER1,
        ),
        _make_claim_handler(store, watchdog, compiler, logger),
    )

    registry.register(
        ToolDef(
            name="report_task_result",
            description=(
                "汇报任务结果。返回中包含experience_hint字段引导经验上报。"
                "⚠️ 仅在发现通用性的坑/陷阱/高效模式时才需上报经验。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "agent_id": {"type": "string"},
                    "status": {"type": "string", "enum": ["completed", "failed", "blocked"]},
                    "summary": {"type": "string"},
                    "key_decisions": {"type": "array", "items": {"type": "string"}},
                    "tokens_used": {"type": "integer"},
                    "self_reflection": {"type": "string"},
                },
                "required": ["task_id", "agent_id", "status", "summary"],
            },
            layer=ToolLayer.LAYER1,
        ),
        _make_report_result_handler(store, watchdog),
    )

    registry.register(
        ToolDef(
            name="release_task",
            description="释放任务，归还到pending队列。",
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "agent_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["task_id", "agent_id", "reason"],
            },
            layer=ToolLayer.LAYER1,
        ),
        _make_release_handler(store, watchdog),
    )

    registry.register(
        ToolDef(
            name="get_task_detail",
            description="获取任务详情，包含测试设计、产出物和执行历史。",
            input_schema={
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
            },
            layer=ToolLayer.LAYER1,
        ),
        _make_get_detail_handler(store),
    )

    registry.register(
        ToolDef(
            name="update_task",
            description="修改/编辑任务信息。支持title/description/priority/skill_type/phase/status/dependencies等字段。",
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "fields": {"type": "object"},
                },
                "required": ["task_id", "fields"],
            },
            layer=ToolLayer.LAYER1,
        ),
        _make_update_handler(store),
    )

    registry.register(
        ToolDef(
            name="list_tasks",
            description="查询任务列表。支持按goal_id/status/statuses/skill_type/keyword等过滤，group_by聚合，分页。",
            input_schema={
                "type": "object",
                "properties": {
                    "goal_id": {"type": "string"},
                    "parent_task_id": {"type": "string"},
                    "status": {"type": "string"},
                    "statuses": {"type": "array", "items": {"type": "string"}},
                    "exclude_status": {"type": "array", "items": {"type": "string"}},
                    "skill_type": {"type": "string"},
                    "claimed_by": {"type": "string"},
                    "min_difficulty": {"type": "integer"},
                    "max_difficulty": {"type": "integer"},
                    "keyword": {"type": "string"},
                    "group_by": {"type": "string", "enum": ["skill_type", "status", "phase"]},
                    "page": {"type": "integer"},
                    "page_size": {"type": "integer"},
                },
            },
            layer=ToolLayer.LAYER1,
        ),
        _make_list_handler(store),
    )

    registry.register(
        ToolDef(
            name="update_task_progress",
            description="更新任务执行进度(0-100)。隐式续期心跳。",
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "agent_id": {"type": "string"},
                    "progress": {"type": "number", "minimum": 0, "maximum": 100},
                    "message": {"type": "string"},
                },
                "required": ["task_id", "agent_id", "progress"],
            },
            layer=ToolLayer.LAYER1,
        ),
        _make_update_progress_handler(store),
    )

    if watchdog:
        registry.register(
            ToolDef(
                name="save_checkpoint",
                description="保存任务执行检查点。Agent意外终止时下次claim_task会自动恢复。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "agent_id": {"type": "string"},
                        "completed_items": {"type": "array", "items": {"type": "string"}},
                        "pending_items": {"type": "array", "items": {"type": "string"}},
                        "modified_files": {"type": "array", "items": {"type": "string"}},
                        "notes": {"type": "string"},
                    },
                    "required": ["task_id", "agent_id"],
                },
                layer=ToolLayer.LAYER1,
            ),
            _make_save_checkpoint_handler(watchdog),
        )

    registry.register(
        ToolDef(
            name="split_task",
            description="将当前领取的任务拆分为多个子任务。所有子任务完成后父任务自动完成。",
            input_schema={
                "type": "object",
                "properties": {
                    "parent_task_id": {"type": "string"},
                    "agent_id": {"type": "string"},
                    "subtasks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "description": {"type": "string"},
                                "skill_type": {"type": "string"},
                                "phase": {"type": "string"},
                                "dependencies": {"type": "array", "items": {"type": "string"}},
                                "difficulty": {"type": "integer"},
                            },
                            "required": ["title", "description"],
                        },
                    },
                },
                "required": ["parent_task_id", "agent_id", "subtasks"],
            },
            layer=ToolLayer.LAYER1,
        ),
        _make_split_handler(store),
    )

    logger.debug("Task 模块工具注册完成")


def _make_create_tasks_handler(store: TaskStore):
    async def handler(params: Dict):
        try:
            tasks = await store.create_batch(
                params.get("goal_id", ""),
                params.get("tasks", []),
            )
            return new_json_result({
                "task_ids": [t.id for t in tasks],
                "count": len(tasks),
            })
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_claim_handler(store: TaskStore, watchdog: Optional[Watchdog],
                         compiler: Optional[Any], logger: logging.Logger):
    async def handler(params: Dict):
        agent_id = params.get("agent_id", "")
        task_id = params.get("task_id", "")

        # Recovery check
        if watchdog and not task_id:
            interrupted_task, cp = await watchdog.recover_interrupted_tasks(agent_id)
            if interrupted_task:
                resumed = await watchdog.resume_interrupted_task(interrupted_task.id, agent_id)
                result_data: Dict[str, Any] = {
                    "result": "success",
                    "task": resumed.to_dict(),
                    "resumed": True,
                    "resume_info": {
                        "message": "检测到之前中断的任务,已自动恢复",
                        "previous_progress": interrupted_task.progress,
                    },
                    "heartbeat_hint": {
                        "soft_timeout_seconds": 1500,
                        "hard_timeout_seconds": 1800,
                        "message": "⚠️ 此任务曾因心跳超时被中断。请务必定期调用 update_task_progress 或 save_checkpoint。",
                    },
                }
                if cp:
                    result_data["checkpoint"] = cp.to_dict()
                # Auto checkpoint
                auto_cp = await watchdog.get_auto_checkpoint_async(interrupted_task.id, agent_id)
                if auto_cp:
                    result_data["auto_checkpoint"] = auto_cp.to_dict()
                # Compile context
                if compiler:
                    try:
                        ctx_text, ctx_tokens = await compiler.compile_for_claim(interrupted_task.id, 2000)
                        if ctx_text:
                            result_data["compiled_context"] = ctx_text
                            result_data["context_tokens"] = ctx_tokens
                    except Exception as e:
                        logger.warning(f"上下文编译失败: {e}")
                return new_json_result(result_data)

        try:
            result = await store.claim(
                agent_id=agent_id,
                task_id=task_id,
                skill_types=params.get("skill_types"),
                affinity_skills=params.get("affinity_skills"),
                max_difficulty=params.get("max_difficulty", 0),
                strict_skill=params.get("strict_skill", False),
            )
        except Exception as e:
            return new_error_result(str(e))

        wrapped: Dict[str, Any] = {
            "result": result,
            "heartbeat_hint": {
                "soft_timeout_seconds": 1500,
                "hard_timeout_seconds": 1800,
                "message": "⚠️ 任务执行期间请定期调用 update_task_progress 或 save_checkpoint（建议每5-10分钟一次）。",
            },
        }

        if isinstance(result, dict) and result.get("result") == "success" and compiler:
            claimed_task = result.get("task")
            claimed_tid = claimed_task.get("id") if isinstance(claimed_task, dict) else ""
            if claimed_tid:
                try:
                    ctx_text, ctx_tokens = await compiler.compile_for_claim(claimed_tid, 2000)
                    if ctx_text:
                        wrapped["compiled_context"] = ctx_text
                        wrapped["context_tokens"] = ctx_tokens
                        logger.info(f"claim_task 自动编译上下文完成 task_id={claimed_tid} tokens={ctx_tokens}")
                except Exception as e:
                    logger.warning(f"claim_task 自动编译上下文失败: {e}")

        return new_json_result(wrapped)
    return handler


def _make_report_result_handler(store: TaskStore, watchdog: Optional[Watchdog]):
    async def handler(params: Dict):
        try:
            result = await store.report_result(
                task_id=params["task_id"],
                agent_id=params["agent_id"],
                status=params["status"],
                summary=params.get("summary", ""),
                tokens_used=params.get("tokens_used", 0),
                key_decisions=params.get("key_decisions"),
                self_reflection=params.get("self_reflection", ""),
            )
            if watchdog:
                await watchdog.archive_and_clear_tool_call_logs(
                    params["agent_id"], params["task_id"]
                )
                await watchdog.record_task_completion_event(
                    params["task_id"], params["agent_id"],
                    params["status"], params.get("summary", ""),
                )
            result["experience_hint"] = _generate_experience_hint(
                params["status"], params.get("self_reflection", "")
            )
            return new_json_result(result)
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_release_handler(store: TaskStore, watchdog: Optional[Watchdog]):
    async def handler(params: Dict):
        try:
            await store.release(params["task_id"], params["agent_id"], params.get("reason", ""))
            if watchdog:
                watchdog.clear_tool_call_logs(params["agent_id"], params["task_id"])
            return new_json_result({"status": "released", "task_id": params["task_id"]})
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_get_detail_handler(store: TaskStore):
    async def handler(params: Dict):
        try:
            task = await store.get(params["task_id"])
            return new_json_result(task.to_dict())
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_update_handler(store: TaskStore):
    async def handler(params: Dict):
        try:
            task = await store.update(params["task_id"], params.get("fields", {}))
            return new_json_result({"status": "updated", "task_id": task.id, "task": task.to_dict()})
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_list_handler(store: TaskStore):
    async def handler(params: Dict):
        try:
            result, total = await store.list(
                goal_id=params.get("goal_id", ""),
                parent_task_id=params.get("parent_task_id", ""),
                status=params.get("status", ""),
                statuses=params.get("statuses"),
                exclude_status=params.get("exclude_status"),
                skill_type=params.get("skill_type", ""),
                claimed_by=params.get("claimed_by", ""),
                min_difficulty=params.get("min_difficulty", 0),
                max_difficulty=params.get("max_difficulty", 0),
                keyword=params.get("keyword", ""),
                group_by=params.get("group_by", ""),
                page=params.get("page", 1),
                page_size=params.get("page_size", 20),
            )
            if params.get("group_by"):
                return new_json_result(result)
            return new_json_result({"tasks": result, "total": total, "page": params.get("page", 1)})
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_update_progress_handler(store: TaskStore):
    async def handler(params: Dict):
        try:
            task = await store.update_progress(
                params["task_id"], params["agent_id"], params["progress"], params.get("message", "")
            )
            return new_json_result({"task_id": task.id, "progress": task.progress, "status": task.status})
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_save_checkpoint_handler(watchdog: Watchdog):
    async def handler(params: Dict):
        try:
            await watchdog.save_checkpoint(
                task_id=params["task_id"],
                agent_id=params["agent_id"],
                completed_items=params.get("completed_items"),
                pending_items=params.get("pending_items"),
                modified_files=params.get("modified_files"),
                notes=params.get("notes", ""),
            )
            return new_json_result({
                "status": "saved",
                "task_id": params["task_id"],
                "completed_count": len(params.get("completed_items", [])),
                "pending_count": len(params.get("pending_items", [])),
                "modified_files": len(params.get("modified_files", [])),
            })
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_split_handler(store: TaskStore):
    async def handler(params: Dict):
        try:
            tasks = await store.split_task(
                params["parent_task_id"], params["agent_id"], params.get("subtasks", [])
            )
            return new_json_result({
                "status": "split_success",
                "parent_task_id": params["parent_task_id"],
                "subtask_ids": [t.id for t in tasks],
                "subtask_count": len(tasks),
                "subtasks": [{"id": t.id, "title": t.title} for t in tasks],
                "auto_complete": "当所有子任务完成后,父任务将自动标记为completed",
            })
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _generate_experience_hint(status: str, self_reflection: str) -> str:
    from agentflow.task.model import TaskStatus
    if status == TaskStatus.FAILED:
        return (
            "⚠️ 任务失败！请调用 report_experience 上报负经验(type=negative)，务必包含：\n"
            "- root_cause: 失败的根本原因\n"
            "- solution: 建议的解决方案\n"
            "- category: bug/design_flaw/performance 等\n"
            "这将帮助后续 Agent 避免同样的问题。"
        )
    elif status == TaskStatus.BLOCKED:
        return (
            "🚧 任务被阻塞。如果阻塞原因涉及通用性问题（如依赖缺失、API不兼容等），"
            "建议调用 report_experience(type=negative, category=architecture) 记录此问题。"
        )
    elif status == TaskStatus.COMPLETED:
        if self_reflection:
            return (
                "✅ 任务完成。如果在执行过程中发现了以下情况，建议调用 report_experience 上报：\n"
                "- 发现了某个通用的坑/陷阱 → type=negative, category=bug\n"
                "- 找到了高效的解决模式 → type=positive, category=pattern/technique\n"
                "⏩ 如果本次任务没有特殊发现，无需上报，直接继续下一个任务。"
            )
        return (
            "✅ 任务完成。仅在发现通用性的坑、陷阱或高效模式时才需要调用 report_experience，"
            "普通的文件修改和常规操作无需上报。"
        )
    return ""
