"""经验反馈存储与可信度计算引擎。

对齐 Go 版本 internal/fixexp/feedback.go 的核心功能：
- 8种负面词标签（not_applicable/misleading/outdated/too_vague/wrong_root_cause/partial_match/duplicate_effort/context_mismatch）
- 基于标签权重的有效可信度衰减计算
- misleading 累计≥3次触发拉黑机制
- 信号级别分类（clean/minor_issues/questionable/unreliable/blacklisted）
- 自动推断反馈（权重×0.5）
- 批量为经验列表附加反馈信息
"""
import json
import logging
from typing import Dict, List, Optional

from agentflow.config import FixFeedbackConfig
from agentflow.storage import RedisClient

# ==================== 负面词标签常量 ====================

# 负面词标签定义（对齐 Go NegativeTag）
TAG_NOT_APPLICABLE   = "not_applicable"    # 不适用
TAG_MISLEADING       = "misleading"        # 误导性
TAG_OUTDATED         = "outdated"          # 已过时
TAG_TOO_VAGUE        = "too_vague"         # 过于模糊
TAG_WRONG_ROOT_CAUSE = "wrong_root_cause"  # 根因错误
TAG_PARTIAL_MATCH    = "partial_match"     # 部分匹配
TAG_DUPLICATE_EFFORT = "duplicate_effort"  # 重复劳动
TAG_CONTEXT_MISMATCH = "context_mismatch"  # 上下文不匹配

# 所有合法的负面词标签
ALL_NEGATIVE_TAGS = [
    TAG_NOT_APPLICABLE,
    TAG_MISLEADING,
    TAG_OUTDATED,
    TAG_TOO_VAGUE,
    TAG_WRONG_ROOT_CAUSE,
    TAG_PARTIAL_MATCH,
    TAG_DUPLICATE_EFFORT,
    TAG_CONTEXT_MISMATCH,
]

# 负面词标签默认权重（对齐 Go NegativeTagWeights）
DEFAULT_TAG_WEIGHTS: Dict[str, float] = {
    TAG_NOT_APPLICABLE:   0.15,
    TAG_MISLEADING:       0.30,
    TAG_OUTDATED:         0.20,
    TAG_TOO_VAGUE:        0.10,
    TAG_WRONG_ROOT_CAUSE: 0.35,
    TAG_PARTIAL_MATCH:    0.05,
    TAG_DUPLICATE_EFFORT: 0.15,
    TAG_CONTEXT_MISMATCH: 0.20,
}

# ==================== 信号级别常量 ====================

SIGNAL_CLEAN        = "clean"        # 无负面反馈
SIGNAL_MINOR_ISSUES = "minor_issues"  # 少量负面反馈
SIGNAL_QUESTIONABLE = "questionable"  # 存疑
SIGNAL_UNRELIABLE   = "unreliable"   # 不可靠
SIGNAL_BLACKLISTED  = "blacklisted"  # 已拉黑

# ==================== 反馈类型常量 ====================

FEEDBACK_HELPFUL    = "helpful"
FEEDBACK_NEGATIVE   = "negative"
FEEDBACK_MISLEADING = "misleading"
FEEDBACK_IRRELEVANT = "irrelevant"
FEEDBACK_OUTDATED   = "outdated"


class ExperienceFeedback:
    """经验反馈存储与可信度计算引擎。

    对齐 Go 版本 FeedbackStore，支持：
    - 多种负面词标签及权重体系
    - 基于标签权重的衰减因子计算
    - misleading 累计≥3次触发拉黑
    - 信号级别分类与警告文本生成
    """

    def __init__(self, redis: RedisClient, cfg: FixFeedbackConfig, logger: logging.Logger):
        self._redis = redis
        self._cfg = cfg
        self._logger = logger
        # 标签权重（可通过配置覆盖，默认使用内置权重）
        self._tag_weights: Dict[str, float] = dict(DEFAULT_TAG_WEIGHTS)

    # ==================== Key 生成 ====================

    def _stats_key(self, exp_id: str) -> str:
        """经验反馈汇总 Hash: af:fix:feedback:{exp_id}"""
        return self._redis.key("fixexp", "feedback", exp_id)

    def _detail_key(self, exp_id: str) -> str:
        """经验反馈详情 List: af:fix:feedback:{exp_id}:detail"""
        return self._redis.key("fixexp", "feedback", exp_id, "detail")

    def _blacklist_key(self) -> str:
        """黑名单 Set: af:fix:feedback:blacklist"""
        return self._redis.key("fixexp", "blacklist")

    # ==================== 核心反馈接口 ====================

    async def submit_feedback(self, exp_id: str, session_id: str,
                               feedback_type: str,
                               negative_tags: Optional[List[str]] = None,
                               reason: str = "",
                               note: str = "") -> Dict:
        """提交经验反馈。

        Args:
            exp_id: 被反馈的经验 ID
            session_id: 反馈时所在的 Fix Session ID
            feedback_type: 反馈类型（helpful/negative/misleading/irrelevant/outdated）
            negative_tags: 负面词标签列表（多选，仅负面反馈时有效）
            reason: 反馈原因说明
            note: 备注（兼容旧接口）

        Returns:
            包含 decay_factor、blacklisted、signal_level 的反馈结果
        """
        # 兼容旧接口：label=good/bad/misleading → 转换为新的 feedback_type
        if feedback_type == "good":
            feedback_type = FEEDBACK_HELPFUL
        elif feedback_type == "bad":
            feedback_type = FEEDBACK_NEGATIVE
        # misleading 保持不变

        stats_key = self._stats_key(exp_id)

        # 获取当前统计
        existing = await self._redis.hgetall(stats_key)
        misleading_count = int(existing.get("tag:" + TAG_MISLEADING, 0))

        if feedback_type == FEEDBACK_HELPFUL:
            # 正向反馈：增加 positive_count
            await self._redis.hset(stats_key, {
                "positive_count": str(int(existing.get("positive_count", 0)) + 1),
                "last_feedback_type": feedback_type,
            })
        else:
            # 负面反馈：增加 total_negative 和各标签计数
            total_negative = int(existing.get("total_negative", 0)) + 1
            updates = {
                "total_negative": str(total_negative),
                "last_feedback_type": feedback_type,
            }

            # 处理负面词标签
            tags_to_apply = negative_tags or []

            # 兼容旧接口：misleading 类型自动添加 misleading 标签
            if feedback_type == FEEDBACK_MISLEADING and TAG_MISLEADING not in tags_to_apply:
                tags_to_apply = [TAG_MISLEADING] + tags_to_apply
            # outdated 类型自动添加 outdated 标签
            if feedback_type == FEEDBACK_OUTDATED and TAG_OUTDATED not in tags_to_apply:
                tags_to_apply = [TAG_OUTDATED] + tags_to_apply
            # irrelevant 类型自动添加 not_applicable 标签
            if feedback_type == FEEDBACK_IRRELEVANT and TAG_NOT_APPLICABLE not in tags_to_apply:
                tags_to_apply = [TAG_NOT_APPLICABLE] + tags_to_apply

            # 更新非 misleading 标签计数（批量 hset）
            non_misleading_updates = {k: v for k, v in updates.items()}
            for tag in tags_to_apply:
                if tag in ALL_NEGATIVE_TAGS and tag != TAG_MISLEADING:
                    key_name = "tag:" + tag
                    non_misleading_updates[key_name] = str(int(existing.get(key_name, 0)) + 1)

            await self._redis.hset(stats_key, non_misleading_updates)

            # misleading 标签使用 hincrby 原子自增，直接获取返回值，避免竞态窗口
            new_misleading_count = misleading_count  # 默认不变
            if TAG_MISLEADING in tags_to_apply:
                new_misleading_count = await self._redis.hincrby(
                    stats_key, "tag:" + TAG_MISLEADING, 1
                )

            # 检查 misleading 是否达到拉黑阈值
            if new_misleading_count >= self._cfg.blacklist_misleading_threshold:
                await self._redis.sadd(self._blacklist_key(), exp_id)
                self._logger.warning(
                    f"经验已加入黑名单 exp_id={exp_id} misleading_count={new_misleading_count}"
                )

        # 记录详情（JSON）
        detail = {
            "exp_id": exp_id,
            "session_id": session_id,
            "feedback_type": feedback_type,
            "negative_tags": negative_tags or [],
            "reason": reason or note,
        }
        await self._redis.rpush(self._detail_key(exp_id), json.dumps(detail))

        # 计算最新衰减因子
        new_stats = await self.get_feedback_stats(exp_id)
        decay_factor = self.calculate_decay_factor(new_stats)
        blacklisted = await self.is_blacklisted(exp_id)
        signal_level = self._classify_signal(decay_factor, blacklisted)

        self._logger.info(
            f"反馈已记录 exp_id={exp_id} type={feedback_type} "
            f"decay_factor={decay_factor:.3f} signal={signal_level}"
        )

        return {
            "status": "feedback_recorded",
            "exp_id": exp_id,
            "feedback_type": feedback_type,
            "negative_tags": negative_tags or [],
            "decay_factor": round(decay_factor, 3),
            "blacklisted": blacklisted,
            "signal_level": signal_level,
        }

    async def record_auto_feedback(self, exp_id: str, tag: str, reason: str = "") -> None:
        """记录自动推断的反馈（权重×0.5，存储在 tag_auto: 前缀下）。

        自动推断的反馈权重减半，不触发拉黑机制。
        """
        if tag not in ALL_NEGATIVE_TAGS:
            return

        stats_key = self._stats_key(exp_id)
        existing = await self._redis.hgetall(stats_key)
        auto_key = "tag_auto:" + tag
        total_auto_key = "total_negative_auto"

        await self._redis.hset(stats_key, {
            auto_key: str(int(existing.get(auto_key, 0)) + 1),
            total_auto_key: str(int(existing.get(total_auto_key, 0)) + 1),
        })

        self._logger.debug(f"自动反馈已记录 exp_id={exp_id} tag={tag} reason={reason}")

    # ==================== 统计查询 ====================

    async def get_feedback_stats(self, exp_id: str) -> Dict:
        """获取经验的反馈统计数据。"""
        stats_key = self._stats_key(exp_id)
        data = await self._redis.hgetall(stats_key)

        total_negative = int(data.get("total_negative", 0))
        total_positive = int(data.get("positive_count", 0))

        # 解析各标签计数（手动 + 自动×0.5）
        tag_counts: Dict[str, int] = {}
        for tag in ALL_NEGATIVE_TAGS:
            count = int(data.get("tag:" + tag, 0))
            # 自动推断的计数按 0.5 权重（四舍五入）
            auto_count = int(data.get("tag_auto:" + tag, 0))
            effective_count = count + round(auto_count * 0.5)
            if effective_count > 0:
                tag_counts[tag] = effective_count

        # 获取 Top 标签（按计数降序，最多3个）
        top_tags = sorted(tag_counts.items(), key=lambda x: -x[1])[:3]
        top_tag_names = [t for t, _ in top_tags]

        return {
            "exp_id": exp_id,
            "total_negative": total_negative,
            "total_positive": total_positive,
            "tag_counts": tag_counts,
            "top_tags": top_tag_names,
        }

    async def is_blacklisted(self, exp_id: str) -> bool:
        """检查经验是否在黑名单中。"""
        return await self._redis.sismember(self._blacklist_key(), exp_id)

    async def get_decay_factor(self, exp_id: str) -> float:
        """获取经验的衰减因子。"""
        stats = await self.get_feedback_stats(exp_id)
        return self.calculate_decay_factor(stats)

    # ==================== 可信度衰减计算 ====================

    def calculate_decay_factor(self, stats: Dict) -> float:
        """计算衰减因子。

        公式：decay_factor = max(min_decay, 1.0 - Σ(tag_weight × count) + positive_count × recovery)

        对齐 Go 版本 CalculateDecayFactor。
        """
        total_negative = stats.get("total_negative", 0)
        total_positive = stats.get("total_positive", 0)

        if total_negative == 0 and total_positive == 0:
            return 1.0

        # 计算负面衰减总量（按标签权重加权）
        tag_counts: Dict[str, int] = stats.get("tag_counts", {})
        total_decay = 0.0
        for tag, count in tag_counts.items():
            weight = self._tag_weights.get(tag, 0.10)  # 未知标签默认权重 0.10
            total_decay += weight * count

        # 正向反馈恢复
        recovery = total_positive * self._cfg.positive_feedback_recovery

        # 计算衰减因子，限制在 [min_decay, 1.0]
        decay_factor = 1.0 - total_decay + recovery
        return max(self._cfg.min_decay_factor, min(1.0, decay_factor))

    def calculate_effective_confidence(self, original_confidence: float, stats: Dict) -> float:
        """计算有效可信度 = 原始可信度 × 衰减因子。"""
        return original_confidence * self.calculate_decay_factor(stats)

    # ==================== 查询结果标注 ====================

    async def enrich_experience_with_feedback(self, exp: Dict) -> Dict:
        """为单条经验附加反馈信息（signal_level、feedback_warning、effective_confidence）。

        对齐 Go 版本 EnrichExperienceWithFeedback。
        """
        exp_id = exp.get("experience_id") or exp.get("session_id", "")
        if not exp_id:
            return exp

        # 检查黑名单
        if await self.is_blacklisted(exp_id):
            exp["feedback_signal"] = SIGNAL_BLACKLISTED
            exp["feedback_warning"] = "🚫 此经验已被标记为不可靠（多次被标记为误导性），建议跳过"
            exp["effective_confidence"] = exp.get("confidence", 1.0) * self._cfg.min_decay_factor
            return exp

        stats = await self.get_feedback_stats(exp_id)
        total_negative = stats.get("total_negative", 0)

        if total_negative == 0:
            exp["feedback_signal"] = SIGNAL_CLEAN
            return exp

        # 计算有效可信度
        decay_factor = self.calculate_decay_factor(stats)
        exp["effective_confidence"] = exp.get("confidence", 1.0) * decay_factor

        # 分级标注
        top_tags_str = ", ".join(stats.get("top_tags", []))
        signal = self._classify_signal(decay_factor, False)
        exp["feedback_signal"] = signal

        if signal == SIGNAL_UNRELIABLE:
            exp["feedback_warning"] = (
                f"⚠️ 此经验已被 {total_negative} 次标记为无效（{top_tags_str}），请谨慎参考或跳过"
            )
        elif signal == SIGNAL_QUESTIONABLE:
            exp["feedback_warning"] = (
                f"⚡ 此经验有 {total_negative} 条负面反馈（{top_tags_str}），建议结合实际情况判断"
            )
        else:
            exp["feedback_warning"] = (
                f"ℹ️ 此经验有 {total_negative} 条反馈提示（{top_tags_str}）"
            )

        return exp

    async def enrich_experiences_with_feedback(self, exps: List[Dict]) -> List[Dict]:
        """批量为经验列表附加反馈信息。

        对齐 Go 版本 EnrichExperiencesWithFeedback。
        """
        for exp in exps:
            await self.enrich_experience_with_feedback(exp)
        return exps

    # ==================== 辅助方法 ====================

    def _classify_signal(self, decay_factor: float, blacklisted: bool) -> str:
        """根据衰减因子分类信号级别。"""
        if blacklisted:
            return SIGNAL_BLACKLISTED
        if decay_factor <= 0.3:
            return SIGNAL_UNRELIABLE
        if decay_factor <= 0.6:
            return SIGNAL_QUESTIONABLE
        if decay_factor < 1.0:
            return SIGNAL_MINOR_ISSUES
        return SIGNAL_CLEAN