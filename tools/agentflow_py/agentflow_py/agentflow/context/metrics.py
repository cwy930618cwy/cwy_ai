"""
上下文编译指标统计模块

移植自 Go 工程 internal/context/metrics.go

提供以下功能:
- CompilationStats: 编译指标数据类
- MetricsStore: 指标持久化和查询（基于 SQLite）
- 支持 overview/trend/layers/recent 四种查询模式
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional


@dataclass
class LayerStat:
    """单层编译统计"""
    name: str           # 层级名称，如 L1_global_rules
    budget: int = 0     # 分配的预算
    tokens: int = 0     # 实际使用的 Token
    hit: bool = False   # 是否命中（有内容注入）
    truncated: bool = False  # 是否因预算不足被截断
    skipped: bool = False    # 是否因 detail_level 被跳过

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "budget": self.budget,
            "tokens": self.tokens,
            "hit": self.hit,
            "truncated": self.truncated,
            "skipped": self.skipped,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "LayerStat":
        return cls(
            name=d.get("name", ""),
            budget=d.get("budget", 0),
            tokens=d.get("tokens", 0),
            hit=d.get("hit", False),
            truncated=d.get("truncated", False),
            skipped=d.get("skipped", False),
        )


@dataclass
class CompilationStats:
    """编译指标统计（7层管线 + L8恢复层）"""
    task_id: str = ""
    skill_type: str = ""
    detail_level: str = ""
    budget: int = 0
    total_tokens: int = 0
    layers: List[LayerStat] = field(default_factory=list)
    hit_count: int = 0          # 命中层数
    total_layers: int = 0       # 总参与层数（不含跳过的）
    hit_rate: float = 0.0       # 命中率 = hit_count / total_layers
    truncate_count: int = 0     # 截断层数
    truncate_rate: float = 0.0  # 截断率 = truncate_count / total_layers
    budget_usage: float = 0.0   # 预算使用率 = total_tokens / budget
    compiled_at: str = ""

    def compute_stats(self) -> None:
        """从 layers 重新计算统计指标"""
        self.hit_count = 0
        self.truncate_count = 0
        self.total_layers = 0
        for l in self.layers:
            if not l.skipped:
                self.total_layers += 1
                if l.hit:
                    self.hit_count += 1
                if l.truncated:
                    self.truncate_count += 1
        if self.total_layers > 0:
            self.hit_rate = self.hit_count / self.total_layers
            self.truncate_rate = self.truncate_count / self.total_layers
        if self.budget > 0:
            self.budget_usage = self.total_tokens / self.budget

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "skill_type": self.skill_type,
            "detail_level": self.detail_level,
            "budget": self.budget,
            "total_tokens": self.total_tokens,
            "layers": [l.to_dict() for l in self.layers],
            "hit_count": self.hit_count,
            "total_layers": self.total_layers,
            "hit_rate": self.hit_rate,
            "truncate_count": self.truncate_count,
            "truncate_rate": self.truncate_rate,
            "budget_usage": self.budget_usage,
            "compiled_at": self.compiled_at,
        }


@dataclass
class MetricsQuery:
    """查询参数"""
    skill_type: str = ""
    detail_level: str = ""
    start_time: str = ""   # RFC3339 格式
    end_time: str = ""     # RFC3339 格式
    limit: int = 0


@dataclass
class MetricsTrend:
    """趋势聚合结果"""
    period: str = ""              # 聚合的时间段（日期）
    compile_count: int = 0        # 编译次数
    avg_hit_rate: float = 0.0     # 平均命中率
    avg_truncate_rate: float = 0.0  # 平均截断率
    avg_budget_usage: float = 0.0   # 平均预算使用率
    avg_budget: float = 0.0       # 平均预算
    avg_tokens: float = 0.0       # 平均 Token 消耗
    sufficient_rate: float = 0.0  # 上下文充分率

    def to_dict(self) -> Dict[str, Any]:
        return {
            "period": self.period,
            "compile_count": self.compile_count,
            "avg_hit_rate": round(self.avg_hit_rate, 4),
            "avg_truncate_rate": round(self.avg_truncate_rate, 4),
            "avg_budget_usage": round(self.avg_budget_usage, 4),
            "avg_budget": round(self.avg_budget, 1),
            "avg_tokens": round(self.avg_tokens, 1),
            "sufficient_rate": round(self.sufficient_rate, 4),
        }


@dataclass
class LayerTrend:
    """单层趋势聚合"""
    layer_name: str = ""
    hit_count: int = 0
    total_count: int = 0
    hit_rate: float = 0.0
    trunc_count: int = 0
    trunc_rate: float = 0.0
    avg_tokens: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layer_name": self.layer_name,
            "hit_count": self.hit_count,
            "total_count": self.total_count,
            "hit_rate": round(self.hit_rate, 4),
            "trunc_count": self.trunc_count,
            "trunc_rate": round(self.trunc_rate, 4),
            "avg_tokens": round(self.avg_tokens, 1),
        }


# 层级顺序（用于排序）
LAYER_ORDER = [
    "L1_global_rules", "L2_project_config", "L3_task_description",
    "L4_skill_dna", "L5_dependencies", "L6_experiences",
    "L7_evolution_log", "L8_recovery_context",
]


class MetricsStore:
    """编译指标持久化和查询（基于 SQLite）"""

    def __init__(self, sqlite_store=None, logger: Optional[logging.Logger] = None):
        """
        初始化指标存储

        Args:
            sqlite_store: SQLite 存储实例（可选，为 None 时静默跳过持久化）
            logger: 日志记录器
        """
        self._sqlite = sqlite_store
        self._logger = logger or logging.getLogger("agentflow.context.metrics")

    def _get_db(self):
        """获取 SQLite 数据库连接，不可用时返回 None"""
        if self._sqlite is None:
            return None
        try:
            return self._sqlite.db()
        except Exception:
            return None

    def save(self, stats: CompilationStats) -> None:
        """持久化一次编译的指标"""
        db = self._get_db()
        if db is None:
            return  # SQLite 未初始化时静默跳过

        try:
            layer_json = json.dumps([l.to_dict() for l in stats.layers], ensure_ascii=False)

            # 收集截断层名称
            truncated_names = [l.name for l in stats.layers if l.truncated]
            truncated_json = json.dumps(truncated_names, ensure_ascii=False)

            sufficient = 0 if stats.truncate_count > 0 else 1

            db.execute(
                """INSERT INTO compilation_metrics
                   (task_id, skill_type, detail_level, budget, total_tokens,
                    layer_stats, truncated_layers, context_sufficient, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    stats.task_id,
                    stats.skill_type,
                    stats.detail_level,
                    stats.budget,
                    stats.total_tokens,
                    layer_json,
                    truncated_json,
                    sufficient,
                    stats.compiled_at or datetime.now(timezone.utc).isoformat(),
                ),
            )
            db.commit()
            self._logger.debug(
                "编译指标已保存 task=%s hit_rate=%.1f%% truncate_rate=%.1f%% budget_usage=%.1f%%",
                stats.task_id,
                stats.hit_rate * 100,
                stats.truncate_rate * 100,
                stats.budget_usage * 100,
            )
        except Exception as e:
            self._logger.warning("保存编译指标失败: %s task=%s", e, stats.task_id)

    def query_trend(self, query: MetricsQuery) -> List[MetricsTrend]:
        """按时间维度聚合查询编译指标趋势"""
        db = self._get_db()
        if db is None:
            return []

        try:
            sql = """SELECT
                date(created_at) as period,
                COUNT(*) as compile_count,
                AVG(CAST(total_tokens AS REAL) / CASE WHEN budget > 0 THEN budget ELSE 1 END) as avg_budget_usage,
                AVG(budget) as avg_budget,
                AVG(total_tokens) as avg_tokens,
                AVG(context_sufficient) as sufficient_rate
            FROM compilation_metrics WHERE 1=1"""
            args = []

            if query.skill_type:
                sql += " AND skill_type = ?"
                args.append(query.skill_type)
            if query.detail_level:
                sql += " AND detail_level = ?"
                args.append(query.detail_level)
            if query.start_time:
                sql += " AND created_at >= ?"
                args.append(query.start_time)
            if query.end_time:
                sql += " AND created_at <= ?"
                args.append(query.end_time)

            sql += " GROUP BY date(created_at) ORDER BY period DESC"

            limit = query.limit if query.limit > 0 else 30
            sql += " LIMIT ?"
            args.append(limit)

            cursor = db.execute(sql, args)
            rows = cursor.fetchall()

            trends = []
            for row in rows:
                t = MetricsTrend(
                    period=row[0] or "",
                    compile_count=row[1] or 0,
                    avg_budget_usage=row[2] or 0.0,
                    avg_budget=row[3] or 0.0,
                    avg_tokens=row[4] or 0.0,
                    sufficient_rate=row[5] or 0.0,
                )
                self._enrich_trend_with_layer_stats(t, query, db)
                trends.append(t)

            return trends
        except Exception as e:
            self._logger.warning("查询编译指标趋势失败: %s", e)
            return []

    def _enrich_trend_with_layer_stats(
        self, trend: MetricsTrend, query: MetricsQuery, db
    ) -> None:
        """从 layer_stats JSON 中聚合层级命中率和截断率"""
        try:
            sql = "SELECT layer_stats FROM compilation_metrics WHERE date(created_at) = ?"
            args = [trend.period]

            if query.skill_type:
                sql += " AND skill_type = ?"
                args.append(query.skill_type)
            if query.detail_level:
                sql += " AND detail_level = ?"
                args.append(query.detail_level)

            cursor = db.execute(sql, args)
            rows = cursor.fetchall()

            total_hit = total_trunc = total_layers = 0
            for row in rows:
                try:
                    layers = json.loads(row[0] or "[]")
                    for l in layers:
                        if not l.get("skipped", False):
                            total_layers += 1
                            if l.get("hit", False):
                                total_hit += 1
                            if l.get("truncated", False):
                                total_trunc += 1
                except Exception:
                    continue

            if total_layers > 0:
                trend.avg_hit_rate = total_hit / total_layers
                trend.avg_truncate_rate = total_trunc / total_layers
        except Exception as e:
            self._logger.debug("enrichTrendWithLayerStats 失败: %s", e)

    def query_layer_trend(self, query: MetricsQuery) -> List[LayerTrend]:
        """按层级维度聚合查询（哪些层级经常命中/截断）"""
        db = self._get_db()
        if db is None:
            return []

        try:
            sql = "SELECT layer_stats FROM compilation_metrics WHERE 1=1"
            args = []

            if query.skill_type:
                sql += " AND skill_type = ?"
                args.append(query.skill_type)
            if query.detail_level:
                sql += " AND detail_level = ?"
                args.append(query.detail_level)
            if query.start_time:
                sql += " AND created_at >= ?"
                args.append(query.start_time)
            if query.end_time:
                sql += " AND created_at <= ?"
                args.append(query.end_time)

            cursor = db.execute(sql, args)
            rows = cursor.fetchall()

            # 按层级名称聚合
            layer_map: Dict[str, LayerTrend] = {}
            for row in rows:
                try:
                    layers = json.loads(row[0] or "[]")
                    for l in layers:
                        if l.get("skipped", False):
                            continue
                        name = l.get("name", "")
                        if name not in layer_map:
                            layer_map[name] = LayerTrend(layer_name=name)
                        lt = layer_map[name]
                        lt.total_count += 1
                        if l.get("hit", False):
                            lt.hit_count += 1
                        if l.get("truncated", False):
                            lt.trunc_count += 1
                        lt.avg_tokens += l.get("tokens", 0)
                except Exception:
                    continue

            # 计算比率，按层级顺序排列
            result = []
            for name in LAYER_ORDER:
                if name in layer_map:
                    lt = layer_map[name]
                    if lt.total_count > 0:
                        lt.hit_rate = lt.hit_count / lt.total_count
                        lt.trunc_rate = lt.trunc_count / lt.total_count
                        lt.avg_tokens = lt.avg_tokens / lt.total_count
                    result.append(lt)

            return result
        except Exception as e:
            self._logger.warning("查询层级趋势失败: %s", e)
            return []

    def query_recent(self, limit: int = 10) -> List[CompilationStats]:
        """查询最近的编译记录"""
        db = self._get_db()
        if db is None:
            return []

        if limit <= 0:
            limit = 10

        try:
            cursor = db.execute(
                """SELECT task_id, skill_type, detail_level, budget, total_tokens,
                          layer_stats, context_sufficient, created_at
                   FROM compilation_metrics
                   ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            )
            rows = cursor.fetchall()

            results = []
            for row in rows:
                cs = CompilationStats(
                    task_id=row[0] or "",
                    skill_type=row[1] or "",
                    detail_level=row[2] or "",
                    budget=row[3] or 0,
                    total_tokens=row[4] or 0,
                    compiled_at=row[7] or "",
                )
                try:
                    layer_dicts = json.loads(row[5] or "[]")
                    cs.layers = [LayerStat.from_dict(l) for l in layer_dicts]
                except Exception:
                    cs.layers = []
                cs.compute_stats()
                results.append(cs)

            return results
        except Exception as e:
            self._logger.warning("查询最近编译记录失败: %s", e)
            return []

    def get_overview(self) -> Dict[str, Any]:
        """获取编译指标概览"""
        db = self._get_db()
        if db is None:
            return {"status": "sqlite_not_available"}

        overview: Dict[str, Any] = {}

        try:
            # 总编译次数
            row = db.execute("SELECT COUNT(*) FROM compilation_metrics").fetchone()
            overview["total_compilations"] = row[0] if row else 0

            # 平均预算使用率
            row = db.execute(
                "SELECT AVG(CAST(total_tokens AS REAL) / CASE WHEN budget > 0 THEN budget ELSE 1 END) FROM compilation_metrics"
            ).fetchone()
            if row and row[0] is not None:
                overview["avg_budget_usage"] = f"{row[0] * 100:.1f}%"

            # 上下文充分率
            row = db.execute(
                "SELECT AVG(CAST(context_sufficient AS REAL)) FROM compilation_metrics"
            ).fetchone()
            if row and row[0] is not None:
                overview["sufficient_rate"] = f"{row[0] * 100:.1f}%"

            # 最近24小时编译次数
            yesterday = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            row = db.execute(
                "SELECT COUNT(*) FROM compilation_metrics WHERE created_at >= ?",
                (yesterday,),
            ).fetchone()
            overview["recent_24h_count"] = row[0] if row else 0

            # 按 skill_type 分组统计
            cursor = db.execute(
                "SELECT skill_type, COUNT(*), AVG(total_tokens) FROM compilation_metrics GROUP BY skill_type"
            )
            by_skill = []
            for row in cursor.fetchall():
                by_skill.append({
                    "skill_type": row[0] or "",
                    "compile_count": row[1] or 0,
                    "avg_tokens": int(row[2] or 0),
                })
            overview["by_skill_type"] = by_skill

        except Exception as e:
            self._logger.warning("获取编译指标概览失败: %s", e)
            overview["error"] = str(e)

        return overview
