"""吐槽（Complaint）存储，对齐 Go 版本 internal/feedback/store.go。

补全功能：
- 分页查询吐槽记录（逆序，最新优先）
- 热点统计聚合（按类型/严重程度/工具/Skill）
- 进化提案分析（高频高严重度吐槽 → 生成进化提案）
- 按维度统计数量（用于自动进化触发检测）
"""
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from agentflow.common import generate_feedback_id
from agentflow.storage import RedisClient

# 严重程度排名（用于热点检测）
SEVERITY_RANK = {
    "low": 1,
    "minor": 1,
    "medium": 2,
    "frustrating": 2,
    "high": 3,
    "blocking": 3,
}


class FeedbackStore:
    def __init__(self, redis: RedisClient, logger: logging.Logger):
        self._redis = redis
        self._logger = logger

    def _list_key(self) -> str:
        """吐槽列表 Key"""
        return self._redis.key("feedback", "list")

    def _record_key(self, fb_id: str) -> str:
        """单条吐槽记录 Key"""
        return self._redis.key("feedback", fb_id)

    def _category_key(self, category: str) -> str:
        """按分类索引 Key"""
        return self._redis.key("feedback", "category", category)

    async def report_complaint(self, agent_id: str, category: str,
                                description: str, severity: str = "medium",
                                affected_task_id: str = "",
                                related_tool: str = "",
                                related_skill: str = "",
                                suggestion: str = "") -> Dict:
        """写入吐槽记录。

        Args:
            agent_id: Agent 标识
            category: 吐槽类型（workflow/tool/rule/performance/other）
            description: 吐槽内容
            severity: 严重程度（low/medium/high 或 minor/frustrating/blocking）
            affected_task_id: 关联任务 ID
            related_tool: 关联工具名
            related_skill: 关联 Skill
            suggestion: 改进建议
        """
        fb_id = generate_feedback_id()
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "id": fb_id,
            "agent_id": agent_id,
            "category": category,
            "description": description,
            "severity": severity,
            "affected_task_id": affected_task_id,
            "related_tool": related_tool,
            "related_skill": related_skill,
            "suggestion": suggestion,
            "created_at": now,
        }
        key = self._record_key(fb_id)
        await self._redis.hset(key, record)
        await self._redis.lpush(self._list_key(), fb_id)
        await self._redis.sadd(self._category_key(category), fb_id)
        self._logger.info(f"Agent吐槽已记录 id={fb_id} category={category} severity={severity}")
        return {"status": "recorded", "feedback_id": fb_id}

    async def get_complaints(self, cursor: int = 0, limit: int = 20,
                              filter_category: str = "") -> Tuple[List[Dict], int, bool]:
        """分页查询吐槽记录（逆序，最新优先）。

        对齐 Go 版本 GetComplaints。

        Args:
            cursor: 分页偏移量（从第几条开始）
            limit: 每页数量（最大50）
            filter_category: 按类型过滤（空表示全部）

        Returns:
            (records, next_cursor, has_more)
        """
        if limit <= 0:
            limit = 20
        if limit > 50:
            limit = 50

        # 获取全部 ID（lpush 写入，lrange 读取时已是逆序）
        all_ids = await self._redis.lrange(self._list_key(), 0, -1)

        # 使用 pipeline 批量获取，避免 N+1 Redis 请求
        pipe_ids = all_ids[cursor:cursor + limit * 3 + 10]  # 多取一些以防过滤后不足
        if pipe_ids:
            async with self._redis.pipeline() as pipe:
                for fid in pipe_ids:
                    pipe.hgetall(self._record_key(fid))
                batch_results = await pipe.execute()
        else:
            batch_results = []

        results = []
        idx = cursor
        batch_idx = 0
        for fid in pipe_ids:
            if len(results) >= limit:
                break
            data = batch_results[batch_idx] if batch_idx < len(batch_results) else {}
            batch_idx += 1
            idx += 1
            if not data:
                continue
            if filter_category and data.get("category", "") != filter_category:
                continue
            results.append(data)

        has_more = idx < len(all_ids)
        next_cursor = idx if has_more else 0

        return results, next_cursor, has_more

    async def get_stats(self) -> Dict:
        """获取吐槽统计聚合（含热点检测）。

        对齐 Go 版本 GetComplaintStats，补全热点检测逻辑。
        """
        all_ids = await self._redis.lrange(self._list_key(), 0, -1)

        category_counts: Dict[str, int] = {}
        severity_counts: Dict[str, int] = {}
        tool_counts: Dict[str, int] = {}
        skill_counts: Dict[str, int] = {}
        recent = []

        # 热点检测：dimension:value → {count, max_severity}
        hot_map: Dict[str, Dict] = {}

        # 使用 pipeline 批量获取，避免 N+1 Redis 请求
        if all_ids:
            async with self._redis.pipeline() as pipe:
                for fid in all_ids:
                    pipe.hgetall(self._record_key(fid))
                all_data = await pipe.execute()
        else:
            all_data = []

        for data in all_data:
            if not data:
                continue

            category = data.get("category", "unknown")
            severity = data.get("severity", "medium")
            tool = data.get("related_tool", "")
            skill = data.get("related_skill", "")

            # 统计各维度
            category_counts[category] = category_counts.get(category, 0) + 1
            severity_counts[severity] = severity_counts.get(severity, 0) + 1

            # 更新热点 map
            self._update_hot_map(hot_map, "category", category, severity)

            if tool:
                tool_counts[tool] = tool_counts.get(tool, 0) + 1
                self._update_hot_map(hot_map, "tool", tool, severity)

            if skill:
                skill_counts[skill] = skill_counts.get(skill, 0) + 1
                self._update_hot_map(hot_map, "skill", skill, severity)

            if len(recent) < 10:
                recent.append(data)

        # 提取热点（count >= 3 且严重程度 >= frustrating/high）
        hot_spots = []
        for key, info in hot_map.items():
            if info["count"] >= 3 and SEVERITY_RANK.get(info["max_severity"], 0) >= 2:
                dim, val = key.split(":", 1)
                hot_spots.append({
                    "dimension": dim,
                    "value": val,
                    "count": info["count"],
                    "severity": info["max_severity"],
                })

        # 按数量降序
        hot_spots.sort(key=lambda x: -x["count"])

        return {
            "total": len(all_ids),
            "by_category": category_counts,
            "by_severity": severity_counts,
            "by_tool": tool_counts,
            "by_skill": skill_counts,
            "hot_spots": hot_spots,
            "recent": recent,
        }

    async def count_by_dimension(self, dimension: str, value: str,
                                   min_severity: str = "frustrating") -> int:
        """按维度统计吐槽数量（用于自动进化触发检测）。

        对齐 Go 版本 CountBySeverityAndDimension。

        Args:
            dimension: 维度（category/tool/skill）
            value: 具体值
            min_severity: 最低严重程度（默认 frustrating）

        Returns:
            符合条件的吐槽数量
        """
        min_rank = SEVERITY_RANK.get(min_severity, 2)
        all_ids = await self._redis.lrange(self._list_key(), 0, -1)

        count = 0
        for fid in all_ids:
            data = await self._redis.hgetall(self._record_key(fid))
            if not data:
                continue
            severity = data.get("severity", "medium")
            if SEVERITY_RANK.get(severity, 0) < min_rank:
                continue
            if dimension == "category" and data.get("category") == value:
                count += 1
            elif dimension == "tool" and data.get("related_tool") == value:
                count += 1
            elif dimension == "skill" and data.get("related_skill") == value:
                count += 1

        return count

    async def analyze_complaints(self, threshold: int = 3) -> Dict:
        """分析吐槽并生成进化提案。

        对齐 Go 版本 AnalyzeComplaints。
        扫描吐槽，当同一维度的 frustrating/high/blocking 级别吐槽 >= threshold 次时生成进化提案。

        Args:
            threshold: 触发进化提案的阈值（默认3）

        Returns:
            包含 total_complaints、evolution_proposals、stats 的分析结果
        """
        if threshold <= 0:
            threshold = 3

        stats = await self.get_stats()
        all_ids = await self._redis.lrange(self._list_key(), 0, -1)

        # 按维度聚合高严重度吐槽的建议
        dim_map: Dict[str, Dict] = {}

        for fid in all_ids:
            data = await self._redis.hgetall(self._record_key(fid))
            if not data:
                continue
            severity = data.get("severity", "medium")
            if SEVERITY_RANK.get(severity, 0) < 2:  # 只统计 frustrating 及以上
                continue

            suggestion = data.get("suggestion", "")

            # 按工具维度
            if tool := data.get("related_tool", ""):
                key = "tool:" + tool
                self._update_dim_map(dim_map, key, severity, suggestion)

            # 按 Skill 维度
            if skill := data.get("related_skill", ""):
                key = "skill:" + skill
                self._update_dim_map(dim_map, key, severity, suggestion)

            # 按类型维度
            if category := data.get("category", ""):
                key = "category:" + category
                self._update_dim_map(dim_map, key, severity, suggestion)

        # 筛选达到阈值的维度生成进化提案
        proposals = []
        for key, info in dim_map.items():
            if info["count"] >= threshold:
                dim, val = key.split(":", 1)
                # 去重建议
                unique_suggestions = list(dict.fromkeys(
                    s for s in info["suggestions"] if s
                ))
                proposals.append({
                    "dimension": dim,
                    "value": val,
                    "count": info["count"],
                    "max_severity": info["max_severity"],
                    "suggestions": unique_suggestions,
                })

        # 按数量降序
        proposals.sort(key=lambda x: -x["count"])

        return {
            "total_complaints": stats["total"],
            "evolution_proposals": proposals,
            "stats": stats,
        }

    # ==================== 辅助方法 ====================

    def _update_hot_map(self, hot_map: Dict, dimension: str, value: str, severity: str) -> None:
        """更新热点 map。"""
        key = f"{dimension}:{value}"
        if key not in hot_map:
            hot_map[key] = {"count": 0, "max_severity": ""}
        hot_map[key]["count"] += 1
        if SEVERITY_RANK.get(severity, 0) > SEVERITY_RANK.get(hot_map[key]["max_severity"], 0):
            hot_map[key]["max_severity"] = severity

    def _update_dim_map(self, dim_map: Dict, key: str, severity: str, suggestion: str) -> None:
        """更新维度聚合 map。"""
        if key not in dim_map:
            dim_map[key] = {"count": 0, "max_severity": "", "suggestions": []}
        dim_map[key]["count"] += 1
        if SEVERITY_RANK.get(severity, 0) > SEVERITY_RANK.get(dim_map[key]["max_severity"], 0):
            dim_map[key]["max_severity"] = severity
        if suggestion:
            dim_map[key]["suggestions"].append(suggestion)