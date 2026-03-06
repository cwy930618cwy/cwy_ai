#!/usr/bin/env python3
"""AgentFlow v2 - Python implementation entry point."""
import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path


async def main_async(config_path: str) -> None:
    from agentflow.common import init_logger, get_logger
    from agentflow.config import load_config
    from agentflow.storage import SQLiteKVStore, SQLiteStore
    from agentflow.lock import LockManager
    from agentflow.mcp_server import Registry, MCPServer, SSEServer
    from agentflow.goal import GoalStore
    from agentflow.goal.tools import register_tools as goal_register
    from agentflow.task import TaskStore, Watchdog
    from agentflow.task.tools import register_tools as task_register
    from agentflow.context import ContextCompiler, MemoryManager, MetricsStore, register_metrics_tool
    from agentflow.context.tools import register_tools as context_register
    from agentflow.skill.store import SkillStore
    from agentflow.skill.presets import install_presets
    from agentflow.skill.tools import register_tools as skill_register
    from agentflow.evolution import EvolutionEngine
    from agentflow.evolution.tools import register_tools as evolution_register
    from agentflow.fixexp import FixExpStore, FixExpEngine
    from agentflow.fixexp.tools import register_tools as fixexp_register
    from agentflow.feedback import FeedbackStore
    from agentflow.feedback.tools import register_tools as feedback_register
    from agentflow.safety import SafetyGuard
    from agentflow.safety.tools import register_tools as safety_register
    from agentflow.archiver import Archiver
    from agentflow.dashboard import DashboardService, DashboardHTTPServer, register_tools as dashboard_register
    from agentflow.mcp_server.types import ToolDef, ToolLayer, new_json_result, new_error_result
    from agentflow.mcp_server.roles import get_all_role_infos, get_role_info

    # ── Load config ────────────────────────────────────────────────────────────
    cfg = load_config(config_path)
    init_logger(cfg.server.log_level)
    logger = get_logger("agentflow")
    logger.info(f"AgentFlow v2 启动中... transport={cfg.server.transport}")

    # ── Storage ────────────────────────────────────────────────────────────
    # 使用 SQLiteKVStore 替代 Redis，所有热数据也存储在 SQLite 中
    kv_db_path = cfg.get_sqlite_path().replace(".db", "_kv.db")
    try:
        redis = await SQLiteKVStore.create(cfg.sqlite, kv_db_path, logger)
    except Exception as e:
        logger.error(f"SQLiteKVStore 初始化失败: {e}")
        sys.exit(1)

    try:
        sqlite = await SQLiteStore.create(cfg.sqlite, cfg.get_sqlite_path(), logger)
    except Exception as e:
        logger.error(f"SQLite 初始化失败: {e}")
        await redis.close()
        sys.exit(1)

    # ── Lock manager ───────────────────────────────────────────────────────────
    try:
        lock_mgr = await LockManager.create(redis, logger)
    except Exception as e:
        logger.error(f"锁管理器初始化失败: {e}")
        sys.exit(1)

    # ── MCP Registry ───────────────────────────────────────────────────────────
    registry = Registry(logger)
    if cfg.tools.layer2_enabled:
        registry.enable_layer2()

    # ── 1. Goal module ────────────────────────────────────────────────────────
    goal_store = GoalStore(redis, logger)
    goal_register(registry, goal_store, logger)

    # ── 2. Context module ──────────────────────────────────────────────────────
    compiler = ContextCompiler(redis, sqlite, cfg.context.compile, logger)
    memory = MemoryManager(redis, logger)
    memory.start()
    context_register(registry, compiler, memory, logger)
    # 注册编译指标查询工具（需要 SQLite）
    metrics_store = MetricsStore(sqlite, logger)
    register_metrics_tool(registry, metrics_store, logger)

    # ── 3. Task module (depends on compiler) ──────────────────────────────────
    task_store = TaskStore(redis, lock_mgr, logger, cfg.lock.default_ttl)
    watchdog = Watchdog(redis, sqlite, cfg.watchdog, logger)
    watchdog.start()
    registry.add_call_hook(watchdog.make_implicit_heartbeat_hook())
    task_register(registry, task_store, watchdog, compiler, logger)

    # ── 4. Skill module ────────────────────────────────────────────────────────
    skill_store = SkillStore(redis, cfg.skill, logger)
    await install_presets(skill_store)
    skill_register(registry, skill_store, logger)

    # ── 5. Evolution module ────────────────────────────────────────────────────
    evo_engine = EvolutionEngine(redis, sqlite, cfg.evolution, logger)
    evolution_register(registry, evo_engine, logger)

    # ── 6. FixExp module ───────────────────────────────────────────────────────
    fix_store = FixExpStore(redis, sqlite, logger)
    fix_engine = FixExpEngine(fix_store, redis, sqlite, cfg.fix_experience, logger,
                              semantic_cfg=cfg.semantic_search)
    fixexp_register(registry, fix_engine, fix_store, logger)

    # ── 7. Safety module ──────────────────────────────────────────────────────
    guard = SafetyGuard(redis, sqlite, cfg.safety, logger)
    safety_register(registry, guard, logger)

    # ── 7.5 Feedback module ───────────────────────────────────────────────────
    feedback_store = FeedbackStore(redis, logger)
    feedback_register(registry, feedback_store, logger)

    # ── 7.6 Collab module (Agent Mailbox & Task Comments) ────────────────────
    from agentflow.collab import Mailbox, CommentStore, register_tools as collab_register
    mailbox = Mailbox(redis, logger)
    comment_store = CommentStore(redis, mailbox, logger)
    collab_register(registry, mailbox, comment_store)

    # ── 7.7 Namespace module (多租户隔离) ─────────────────────────────────────
    from agentflow.namespace import NamespaceManager, register_tools as namespace_register
    ns_mgr = await NamespaceManager.create(redis, logger)
    namespace_register(registry, ns_mgr, logger)

    # ── 7.8 Project module (PhaseGate 生命周期管理) ───────────────────────────
    from agentflow.project import ProjectStore, Engine, Generator, register_tools as project_register
    project_store = ProjectStore(redis, logger, ns_mgr)
    project_engine = Engine(project_store, goal_store, logger)
    project_generator = Generator()
    project_register(registry, project_engine, project_store, project_generator, logger)

    # ── 7.9 Plugin module (HTTP 插件系统) ─────────────────────────────────────
    from agentflow.plugin import Manager as PluginManager, register_tools as plugin_register
    plugin_mgr = PluginManager(registry, logger)
    plugin_register(registry, plugin_mgr)

    # ── 7.10 Portability module (数据导入导出) ────────────────────────────────
    from agentflow.portability import Exporter, Importer, register_tools as portability_register
    exporter = Exporter(redis, skill_store, goal_store, task_store, logger)
    importer = Importer(redis, skill_store, goal_store, logger)  # Importer 不需要 task_store
    portability_register(registry, exporter, importer, logger)

    # ── 7.11 Webhook module (事件通知) ────────────────────────────────────────
    from agentflow.webhook import Dispatcher as WebhookDispatcher, register_tools as webhook_register
    webhook_dispatcher = WebhookDispatcher(redis, logger)
    webhook_register(registry, webhook_dispatcher)

    # ── 8. Dashboard tools (MCP) ─────────────────────────────────────────────
    dash_service = DashboardService(redis, sqlite, logger)
    dashboard_register(registry, dash_service, logger)

    # ── 9. Builtin tools ──────────────────────────────────────────────────────
    _register_builtin_tools(registry, cfg, logger)

    # Stats
    total, l1, l2 = registry.stats()
    logger.info(f"工具注册完成 total={total} layer1={l1} layer2={l2}")

    # ── Archiver ───────────────────────────────────────────────────────────────
    arc = Archiver(redis, sqlite, cfg.storage.archive, logger)
    arc.start()

    # ── Dashboard HTTP Server ──────────────────────────────────────────────────
    dashboard_server = None
    if cfg.server.dashboard_addr:
        dashboard_server = DashboardHTTPServer(dash_service, cfg.server.dashboard_addr, logger)
        asyncio.create_task(dashboard_server.serve())

    # ── Signal handler ─────────────────────────────────────────────────────────
    loop = asyncio.get_event_loop()
    shutdown_event = asyncio.Event()

    def _handle_signal():
        logger.info("收到停止信号，正在关闭...")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass

    # ── Start MCP Server ───────────────────────────────────────────────────────
    transport = cfg.server.transport.lower()
    if transport == "stdio":
        server = MCPServer(registry, logger)
    elif transport in ("sse", "http"):
        server = SSEServer(registry, cfg.server.sse_addr, logger)
    else:
        logger.error(f"不支持的传输模式: {transport} (支持: stdio, sse, http)")
        sys.exit(1)

    # Background shutdown watcher
    async def _watch_shutdown():
        await shutdown_event.wait()
        server.stop() if transport == "stdio" else await server.stop()

    asyncio.create_task(_watch_shutdown())

    try:
        await server.serve()
    finally:
        logger.info("正在关闭各模块...")
        await arc.stop()
        await watchdog.stop()
        await memory.stop()
        if dashboard_server:
            await dashboard_server.stop()
        await redis.close()
        await sqlite.close()

    logger.info("AgentFlow v2 已关闭（SQLite 模式）")



def _register_builtin_tools(registry, cfg, logger: logging.Logger) -> None:
    from agentflow.mcp_server.types import ToolDef, ToolLayer, new_json_result, new_error_result
    from agentflow.mcp_server.roles import get_all_role_infos, get_role_info

    async def get_role_tools_handler(params: dict):
        role = params.get("role", "")
        if not role:
            infos = get_all_role_infos()
            overview = [{
                "role": info.role,
                "name": info.name,
                "description": info.description,
                "core_tools_count": len(info.core_tools),
                "extra_tools_count": len(info.extra_tools),
                "workflow": info.workflow,
            } for info in infos]
            return new_json_result({
                "message": "以下为所有可用角色。传入 role 参数获取具体角色的工具列表。",
                "roles": overview,
            })
        info = get_role_info(role)
        if not info:
            return new_error_result(f"不支持的角色: {role}（支持: executor, auditor, operator）")
        core_tools, extra_tools = registry.list_tools_by_role(role)

        def build_items(defs):
            return [{"name": d.name, "description": d.description[:120]} for d in defs]

        return new_json_result({
            "role": info.role,
            "name": info.name,
            "description": info.description,
            "workflow": info.workflow,
            "core_tools": build_items(core_tools),
            "extra_tools": build_items(extra_tools),
            "tip": "core_tools 为该角色必须掌握的工具，extra_tools 为按需使用的辅助工具。",
        })

    registry.register(
        ToolDef(
            name="get_role_tools",
            description="获取指定角色的推荐工具子集和使用指南。支持角色：executor/auditor/operator。",
            input_schema={
                "type": "object",
                "properties": {
                    "role": {"type": "string", "enum": ["executor", "auditor", "operator"]},
                },
            },
            layer=ToolLayer.LAYER1,
        ),
        get_role_tools_handler,
    )

    logger.debug("内置工具注册完成")


def main():
    parser = argparse.ArgumentParser(description="AgentFlow v2 - Multi-Agent Task Orchestration")
    parser.add_argument(
        "--config",
        default="configs/config.yaml",
        help="配置文件路径 (默认: configs/config.yaml)",
    )
    args = parser.parse_args()

    # Resolve config path relative to script location if not absolute
    config_path = args.config
    if not Path(config_path).is_absolute():
        script_dir = Path(__file__).parent
        candidate = script_dir / config_path
        if candidate.exists():
            config_path = str(candidate)

    try:
        asyncio.run(main_async(config_path))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()