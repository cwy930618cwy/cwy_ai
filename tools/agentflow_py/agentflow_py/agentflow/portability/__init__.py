"""Portability 模块 - 数据导入/导出功能。

提供 AgentFlow 数据的可移植性支持，包括：
- 数据导出：将 Skills/Experiences/Goals/Tasks 导出为 JSON 格式
- 数据导入：从 JSON 导入数据，支持 skip/overwrite/merge 三种冲突策略
- MCP 工具：export_data 和 import_data

使用示例:
    from agentflow.portability import Exporter, Importer, register_tools

    # 创建导出器
    exporter = Exporter(redis, skill_store, goal_store, task_store, logger)

    # 导出数据
    pkg = await exporter.export(ExportParams(
        scope=ExportScope(skills=True, experiences=True),
    ))

    # 创建导入器
    importer = Importer(redis, skill_store, goal_store, logger)

    # 导入数据
    result = await importer.import_data(pkg, ImportParams(
        conflict_policy="merge",
    ))

    # 注册 MCP 工具
    register_tools(registry, exporter, importer, logger)
"""
from .model import (
    ExportFormat,
    ExportScope,
    ExportStats,
    ExportPackage,
    ExportParams,
    ImportParams,
    ImportResult,
    SkillExport,
    ExpExport,
)
from .exporter import Exporter
from .importer import Importer
from .tools import register_tools

__all__ = [
    # 数据模型
    "ExportFormat",
    "ExportScope",
    "ExportStats",
    "ExportPackage",
    "ExportParams",
    "ImportParams",
    "ImportResult",
    "SkillExport",
    "ExpExport",
    # 导出器/导入器
    "Exporter",
    "Importer",
    # 工具注册
    "register_tools",
]
