import logging
from typing import Any, Dict

from agentflow.mcp_server import Registry, ToolDef, ToolLayer, new_json_result, new_error_result
from .compiler import ContextCompiler
from .memory import MemoryManager
from .metrics import MetricsStore, MetricsQuery


def register_tools(registry: Registry, compiler: ContextCompiler,
                   memory: MemoryManager, logger: logging.Logger) -> None:

    registry.register(
        ToolDef(
            name="get_task_context",
            description="为指定任务编译精准上下文（8层管线）。通常由 claim_task 自动调用，只有特殊场景才需要手动调用。",
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "budget": {"type": "integer", "description": "Token预算,默认2000"},
                    "detail_level": {
                        "type": "string",
                        "enum": ["minimal", "standard", "full"],
                        "default": "standard",
                    },
                },
                "required": ["task_id"],
            },
            layer=ToolLayer.LAYER1,
        ),
        _make_get_context_handler(compiler),
    )

    registry.register(
        ToolDef(
            name="get_global_rules",
            description="获取全局规则列表。",
            input_schema={
                "type": "object",
                "properties": {
                    "skill_type": {"type": "string", "description": "按skill类型过滤"},
                },
            },
            layer=ToolLayer.LAYER1,
        ),
        _make_get_global_rules_handler(compiler),
    )

    registry.register(
        ToolDef(
            name="get_artifact",
            description="获取任务产出物（代码/接口签名/摘要）。mode: full/interfaces_only/summary。",
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "mode": {
                        "type": "string",
                        "enum": ["full", "interfaces_only", "summary"],
                        "default": "summary",
                    },
                },
                "required": ["task_id"],
            },
            layer=ToolLayer.LAYER1,
        ),
        _make_get_artifact_handler(compiler),
    )

    registry.register(
        ToolDef(
            name="search_context",
            description="在全局规则/经验/Skill DNA中搜索关键词。",
            input_schema={
                "type": "object",
                "properties": {
                    "keyword": {"type": "string"},
                    "scope": {
                        "type": "string",
                        "enum": ["all", "rules", "experiences", "skills"],
                        "default": "all",
                    },
                },
                "required": ["keyword"],
            },
            layer=ToolLayer.LAYER1,
        ),
        _make_search_context_handler(compiler),
    )

    registry.register(
        ToolDef(
            name="get_memory_status",
            description="获取记忆系统状态（总量/容量/衰减因子）。",
            input_schema={"type": "object", "properties": {}},
            layer=ToolLayer.LAYER2,
        ),
        _make_get_memory_handler(memory),
    )

    logger.debug("Context 模块工具注册完成")


def _make_get_context_handler(compiler: ContextCompiler):
    async def handler(params: Dict):
        try:
            result = await compiler.compile(
                params["task_id"],
                budget=params.get("budget", 0),
                detail_level=params.get("detail_level", "standard"),
            )
            return new_json_result(result)
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_get_global_rules_handler(compiler: ContextCompiler):
    async def handler(params: Dict):
        try:
            skill_type = params.get("skill_type", "")
            rules = await compiler._redis.lrange(compiler._redis.key("ctx", "global_rules"), 0, -1)
            return new_json_result({"rules": rules, "count": len(rules)})
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_get_artifact_handler(compiler: ContextCompiler):
    async def handler(params: Dict):
        try:
            task_data = await compiler._redis.hgetall(
                compiler._redis.key("task", params["task_id"])
            )
            if not task_data:
                return new_error_result(f"task {params['task_id']} 不存在")
            mode = params.get("mode", "summary")
            summary = task_data.get("summary", "")
            artifacts = task_data.get("artifacts", "[]")
            return new_json_result({
                "task_id": params["task_id"],
                "mode": mode,
                "summary": summary,
                "artifacts": artifacts,
                "title": task_data.get("title", ""),
                "status": task_data.get("status", ""),
            })
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_search_context_handler(compiler: ContextCompiler):
    async def handler(params: Dict):
        keyword = params.get("keyword", "").lower()
        scope = params.get("scope", "all")
        results = []

        if scope in ("all", "rules"):
            rules = await compiler._redis.lrange(compiler._redis.key("ctx", "global_rules"), 0, -1)
            for r in rules:
                if keyword in r.lower():
                    results.append({"source": "global_rules", "content": r})

        if scope in ("all", "experiences"):
            for stream_key_suffix in ("exp:positive", "exp:negative"):
                msgs = await compiler._redis.xrevrange(
                    compiler._redis.key(*stream_key_suffix.split(":")), count=20
                )
                for msg in msgs:
                    desc = msg.get("fields", {}).get("description", "")
                    if keyword in desc.lower():
                        results.append({"source": stream_key_suffix, "content": desc})

        return new_json_result({"results": results[:20], "keyword": keyword, "scope": scope})
    return handler


def _make_get_memory_handler(memory: MemoryManager):
    async def handler(params: Dict):
        try:
            stats = await memory.get_stats()
            return new_json_result(stats)
        except Exception as e:
            return new_error_result(str(e))
    return handler


def register_metrics_tool(
    registry: Registry,
    metrics_store: MetricsStore,
    logger: logging.Logger,
) -> None:
    """注册编译指标查询工具（在 SQLite 初始化后调用）"""

    registry.register(
        ToolDef(
            name="get_context_metrics",
            description=(
                "查询上下文编译指标趋势。支持按时间/技能/详细度维度聚合,"
                "展示层级命中率/截断率/预算使用率长期趋势。"
                "mode: overview(概览)/trend(时间趋势)/layers(层级分析)/recent(最近记录)。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["overview", "trend", "layers", "recent"],
                        "description": "查询模式: overview(概览)/trend(时间趋势)/layers(层级分析)/recent(最近记录)",
                    },
                    "skill_type": {"type": "string", "description": "按技能类型过滤"},
                    "detail_level": {
                        "type": "string",
                        "enum": ["minimal", "standard", "full"],
                        "description": "按详细度过滤",
                    },
                    "start_time": {"type": "string", "description": "开始时间(RFC3339格式)"},
                    "end_time": {"type": "string", "description": "结束时间(RFC3339格式)"},
                    "limit": {"type": "integer", "description": "返回数量限制,默认30"},
                },
            },
            layer=ToolLayer.LAYER1,
        ),
        _make_get_context_metrics_handler(metrics_store),
    )

    logger.debug("编译指标查询工具注册完成 tool=get_context_metrics")


def _make_get_context_metrics_handler(metrics_store: MetricsStore):
    async def handler(params: Dict):
        mode = params.get("mode", "overview")
        query = MetricsQuery(
            skill_type=params.get("skill_type", ""),
            detail_level=params.get("detail_level", ""),
            start_time=params.get("start_time", ""),
            end_time=params.get("end_time", ""),
            limit=params.get("limit", 0),
        )

        try:
            if mode == "overview":
                overview = metrics_store.get_overview()
                return new_json_result(overview)

            elif mode == "trend":
                trends = metrics_store.query_trend(query)
                return new_json_result({
                    "trends": [t.to_dict() for t in trends],
                    "count": len(trends),
                    "query": {
                        "skill_type": query.skill_type,
                        "detail_level": query.detail_level,
                        "start_time": query.start_time,
                        "end_time": query.end_time,
                        "limit": query.limit,
                    },
                })

            elif mode == "layers":
                layer_trends = metrics_store.query_layer_trend(query)
                return new_json_result({
                    "layer_trends": [lt.to_dict() for lt in layer_trends],
                    "count": len(layer_trends),
                    "query": {
                        "skill_type": query.skill_type,
                        "detail_level": query.detail_level,
                    },
                })

            elif mode == "recent":
                limit = query.limit if query.limit > 0 else 10
                records = metrics_store.query_recent(limit)
                return new_json_result({
                    "records": [r.to_dict() for r in records],
                    "count": len(records),
                })

            else:
                return new_error_result(
                    f"不支持的查询模式: {mode}（支持: overview/trend/layers/recent）"
                )
        except Exception as e:
            return new_error_result(str(e))

    return handler
