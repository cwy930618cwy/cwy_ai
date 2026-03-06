"""Portability MCP 工具注册。

提供两个 MCP 工具：
- export_data: 导出 AgentFlow 数据为 JSON 格式
- import_data: 从 JSON 导入数据到 AgentFlow

这两个工具属于 Layer 2 扩展工具。
"""
import json
import logging
from typing import Dict, Any

from agentflow.mcp_server import Registry, ToolDef, ToolLayer, ToolResult
from agentflow.mcp_server.types import new_error_result, new_json_result
from .exporter import Exporter
from .importer import Importer
from .model import ExportParams, ExportScope, ImportParams, ExportPackage


def register_tools(
    registry: Registry,
    exporter: Exporter,
    importer: Importer,
    logger: logging.Logger,
) -> None:
    """注册导出/导入 MCP 工具。

    Args:
        registry: MCP 工具注册器。
        exporter: 数据导出器。
        importer: 数据导入器。
        logger: 日志记录器。
    """

    # Tool: export_data [Layer 2]
    async def handle_export_data(params: Dict) -> ToolResult:
        """处理 export_data 工具调用。"""
        # 解析 scope 参数
        scope_data = params.get("scope", {})
        if scope_data:
            scope = ExportScope(
                skills=scope_data.get("skills", True),
                experiences=scope_data.get("experiences", True),
                global_rules=scope_data.get("global_rules", True),
                goals=scope_data.get("goals", True),
                tasks=scope_data.get("tasks", True),
            )
        else:
            # 默认全量导出
            scope = ExportScope()

        since = params.get("since", "")

        try:
            pkg = await exporter.export(ExportParams(
                scope=scope,
                format="json",
                since=since,
            ))
        except Exception as e:
            return new_error_result(f"导出失败: {e}")

        # 序列化为 JSON 字符串
        try:
            data = json.dumps(pkg.to_dict(), ensure_ascii=False)
        except Exception as e:
            return new_error_result(f"序列化失败: {e}")

        return new_json_result({
            "data": data,
            "stats": pkg.stats.to_dict(),
            "exported_at": pkg.exported_at,
            "version": pkg.version,
            "hint": "将 data 字段内容保存为 JSON 文件，使用 import_data 工具导入到其他实例。",
        })

    registry.register(
        ToolDef(
            name="export_data",
            description=(
                "导出 AgentFlow 数据（Skills/Experiences/GlobalRules/Goals/Tasks）为 JSON 格式，"
                "支持全量或增量导出。可用于团队间共享 Skill 和经验库，或迁移到新实例。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "object",
                        "description": "导出范围（不填则全量导出）",
                        "properties": {
                            "skills": {"type": "boolean", "description": "导出 Skills（含 DNA）"},
                            "experiences": {"type": "boolean", "description": "导出经验库（正/负经验）"},
                            "global_rules": {"type": "boolean", "description": "导出全局规则"},
                            "goals": {"type": "boolean", "description": "导出目标列表"},
                            "tasks": {"type": "boolean", "description": "导出任务列表"},
                        },
                    },
                    "since": {
                        "type": "string",
                        "description": (
                            "增量导出：只导出此时间之后的经验（RFC3339 格式，如 2024-01-01T00:00:00Z）。"
                            "不填则全量导出。"
                        ),
                    },
                },
            },
            layer=ToolLayer.LAYER2,
        ),
        handle_export_data,
    )

    # Tool: import_data [Layer 2]
    async def handle_import_data(params: Dict) -> ToolResult:
        """处理 import_data 工具调用。"""
        data = params.get("data", "")
        if not data:
            return new_error_result("data 参数不能为空")

        conflict_policy = params.get("conflict_policy", "skip")
        if conflict_policy not in ("skip", "overwrite", "merge"):
            return new_error_result("conflict_policy 必须为 skip/overwrite/merge")

        # 解析 scope
        scope_data = params.get("scope")
        scope = None
        if scope_data:
            scope = ExportScope(
                skills=scope_data.get("skills", True),
                experiences=scope_data.get("experiences", True),
                global_rules=scope_data.get("global_rules", True),
                goals=scope_data.get("goals", True),
                tasks=scope_data.get("tasks", True),
            )

        # 解析导出包
        try:
            pkg_dict = json.loads(data)
            pkg = ExportPackage.from_dict(pkg_dict)
        except Exception as e:
            return new_error_result(f"解析导出数据失败: {e}")

        try:
            result = await importer.import_data(pkg, ImportParams(
                data=data,
                conflict_policy=conflict_policy,
                scope=scope,
            ))
        except Exception as e:
            return new_error_result(f"导入失败: {e}")

        resp: Dict[str, Any] = {
            "skills_imported": result.skills_imported,
            "skills_skipped": result.skills_skipped,
            "positive_exp_imported": result.positive_exp_imported,
            "negative_exp_imported": result.negative_exp_imported,
            "global_rules_imported": result.global_rules_imported,
            "goals_imported": result.goals_imported,
            "tasks_imported": result.tasks_imported,
            "conflict_policy": conflict_policy,
        }
        if result.errors:
            resp["errors"] = result.errors
            resp["message"] = f"导入完成，但有 {len(result.errors)} 个错误，请检查 errors 字段"
        else:
            resp["message"] = "导入成功"

        return new_json_result(resp)

    registry.register(
        ToolDef(
            name="import_data",
            description=(
                "从 export_data 导出的 JSON 数据中导入 AgentFlow 数据。"
                "支持 skip（跳过已存在）、overwrite（覆盖）、merge（合并 Skill DNA）三种冲突策略。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "data": {
                        "type": "string",
                        "description": "export_data 导出的 JSON 字符串（必填）",
                    },
                    "conflict_policy": {
                        "type": "string",
                        "enum": ["skip", "overwrite", "merge"],
                        "description": (
                            "冲突策略：skip=跳过已存在的数据（默认）；"
                            "overwrite=覆盖已存在的数据；"
                            "merge=合并（仅对 Skill DNA 有效，追加规则/反模式/最佳实践）"
                        ),
                    },
                    "scope": {
                        "type": "object",
                        "description": "导入范围（不填则导入包中所有数据）",
                        "properties": {
                            "skills": {"type": "boolean"},
                            "experiences": {"type": "boolean"},
                            "global_rules": {"type": "boolean"},
                            "goals": {"type": "boolean"},
                            "tasks": {"type": "boolean"},
                        },
                    },
                },
                "required": ["data"],
            },
            layer=ToolLayer.LAYER2,
        ),
        handle_import_data,
    )

    logger.debug("Portability 模块工具注册完成 count=2")
