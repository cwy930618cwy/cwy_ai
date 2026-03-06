"""数据导出/导入的数据模型定义。

本模块定义了 AgentFlow 数据移植所需的所有数据结构，包括：
- ExportFormat: 导出格式（JSON/YAML）
- ExportScope: 导出范围控制
- ExportPackage: 导出数据包结构
- ImportParams: 导入参数
- ImportResult: 导入结果
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


class ExportFormat:
    """导出格式常量。"""
    JSON = "json"
    YAML = "yaml"


@dataclass
class ExportScope:
    """导出范围控制，指定要导出的数据类型。"""
    skills: bool = True
    experiences: bool = True
    global_rules: bool = True
    goals: bool = True
    tasks: bool = True

    def to_dict(self) -> Dict[str, bool]:
        return {
            "skills": self.skills,
            "experiences": self.experiences,
            "global_rules": self.global_rules,
            "goals": self.goals,
            "tasks": self.tasks,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "ExportScope":
        return cls(
            skills=d.get("skills", True),
            experiences=d.get("experiences", True),
            global_rules=d.get("global_rules", True),
            goals=d.get("goals", True),
            tasks=d.get("tasks", True),
        )


@dataclass
class ExportStats:
    """导出统计信息。"""
    skill_count: int = 0
    positive_exp_count: int = 0
    negative_exp_count: int = 0
    global_rule_count: int = 0
    goal_count: int = 0
    task_count: int = 0

    def to_dict(self) -> Dict[str, int]:
        return {
            "skill_count": self.skill_count,
            "positive_exp_count": self.positive_exp_count,
            "negative_exp_count": self.negative_exp_count,
            "global_rule_count": self.global_rule_count,
            "goal_count": self.goal_count,
            "task_count": self.task_count,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "ExportStats":
        return cls(
            skill_count=d.get("skill_count", 0),
            positive_exp_count=d.get("positive_exp_count", 0),
            negative_exp_count=d.get("negative_exp_count", 0),
            global_rule_count=d.get("global_rule_count", 0),
            goal_count=d.get("goal_count", 0),
            task_count=d.get("task_count", 0),
        )


@dataclass
class SkillExport:
    """Skill 导出数据，包含 Skill 本身及其 Metrics。"""
    skill: Optional[Dict[str, Any]] = None
    metrics: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill": self.skill,
            "metrics": self.metrics,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "SkillExport":
        return cls(
            skill=d.get("skill"),
            metrics=d.get("metrics"),
        )


@dataclass
class ExpExport:
    """经验导出数据，包含正/负经验列表。"""
    positive: List[Dict[str, str]] = field(default_factory=list)
    negative: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "positive": self.positive,
            "negative": self.negative,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "ExpExport":
        return cls(
            positive=d.get("positive", []),
            negative=d.get("negative", []),
        )


@dataclass
class ExportPackage:
    """导出数据包，包含版本、时间戳、范围、数据和统计信息。"""
    version: str = "1.0"
    exported_at: str = ""
    scope: Optional[ExportScope] = None
    skills: List[SkillExport] = field(default_factory=list)
    experiences: Optional[ExpExport] = None
    global_rules: List[str] = field(default_factory=list)
    goals: List[Dict[str, Any]] = field(default_factory=list)
    tasks: List[Dict[str, Any]] = field(default_factory=list)
    stats: ExportStats = field(default_factory=ExportStats)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "version": self.version,
            "exported_at": self.exported_at,
            "scope": self.scope.to_dict() if self.scope else None,
            "stats": self.stats.to_dict(),
        }
        if self.skills:
            d["skills"] = [s.to_dict() for s in self.skills]
        if self.experiences:
            d["experiences"] = self.experiences.to_dict()
        if self.global_rules:
            d["global_rules"] = self.global_rules
        if self.goals:
            d["goals"] = self.goals
        if self.tasks:
            d["tasks"] = self.tasks
        return d

    @classmethod
    def from_dict(cls, d: Dict) -> "ExportPackage":
        skills = [SkillExport.from_dict(s) for s in d.get("skills", [])]
        experiences = ExpExport.from_dict(d["experiences"]) if d.get("experiences") else None
        return cls(
            version=d.get("version", "1.0"),
            exported_at=d.get("exported_at", ""),
            scope=ExportScope.from_dict(d["scope"]) if d.get("scope") else None,
            skills=skills,
            experiences=experiences,
            global_rules=d.get("global_rules", []),
            goals=d.get("goals", []),
            tasks=d.get("tasks", []),
            stats=ExportStats.from_dict(d.get("stats", {})),
        )


@dataclass
class ExportParams:
    """导出参数。"""
    scope: ExportScope = field(default_factory=ExportScope)
    format: str = ExportFormat.JSON
    since: str = ""  # 增量导出：只导出指定时间之后的数据（RFC3339 格式）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scope": self.scope.to_dict(),
            "format": self.format,
            "since": self.since,
        }


@dataclass
class ImportParams:
    """导入参数。"""
    data: str = ""  # JSON 格式的导出包内容
    conflict_policy: str = "skip"  # skip/overwrite/merge
    scope: Optional[ExportScope] = None  # 导入范围（不填则导入包中所有数据）

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "data": self.data,
            "conflict_policy": self.conflict_policy,
        }
        if self.scope:
            d["scope"] = self.scope.to_dict()
        return d


@dataclass
class ImportResult:
    """导入结果。"""
    skills_imported: int = 0
    skills_skipped: int = 0
    positive_exp_imported: int = 0
    negative_exp_imported: int = 0
    global_rules_imported: int = 0
    goals_imported: int = 0
    tasks_imported: int = 0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "skills_imported": self.skills_imported,
            "skills_skipped": self.skills_skipped,
            "positive_exp_imported": self.positive_exp_imported,
            "negative_exp_imported": self.negative_exp_imported,
            "global_rules_imported": self.global_rules_imported,
            "goals_imported": self.goals_imported,
            "tasks_imported": self.tasks_imported,
        }
        if self.errors:
            d["errors"] = self.errors
        return d
