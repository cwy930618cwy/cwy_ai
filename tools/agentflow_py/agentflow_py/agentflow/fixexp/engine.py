"""FixExp Engine: session management and anti-loop integration."""
import logging
from typing import Dict, List, Optional, Tuple

from agentflow.config import FixExperienceConfig, SemanticSearchConfig
from agentflow.storage import RedisClient, SQLiteStore
from .model import FixSession, FixAttempt, FixStatus
from .store import FixExpStore
from .antiloop import AntiLoopDetector
from .feedback import ExperienceFeedback
from .embedding import EmbeddingClient
from .vector_store import VectorStore


class FixExpEngine:
    def __init__(self, store: FixExpStore, redis: RedisClient,
                 sqlite: Optional[SQLiteStore], cfg: FixExperienceConfig,
                 logger: logging.Logger,
                 semantic_cfg: Optional[SemanticSearchConfig] = None):
        self._store = store
        self._redis = redis
        self._sqlite = sqlite
        self._cfg = cfg
        self._logger = logger
        self._antiloop = AntiLoopDetector(
            warn_threshold=cfg.anti_loop.similarity_warn_threshold,
            block_threshold=cfg.anti_loop.similarity_block_threshold,
            max_same_approach=cfg.anti_loop.max_same_approach_attempts,
        )
        self._feedback = ExperienceFeedback(redis, cfg.feedback, logger)
        # 语义搜索（可选，disabled 时降级为关键词匹配）
        if semantic_cfg and semantic_cfg.enabled:
            self._embedding = EmbeddingClient(semantic_cfg, redis, logger)
            self._vector_store = VectorStore(redis, logger)
            self._semantic_weight = semantic_cfg.semantic_weight
        else:
            self._embedding = None
            self._vector_store = None
            self._semantic_weight = 0.6

    async def query_fix_experience(self, task_id: str, agent_id: str,
                                    error_type: str, problem: str,
                                    create_if_missing: bool = True) -> Dict:
        # Find or create current session
        current_session = await self._find_active_session(task_id, agent_id)
        if not current_session and create_if_missing:
            current_session = await self._store.create_session(
                task_id=task_id,
                agent_id=agent_id,
                problem=problem,
                error_type=error_type,
            )

        # 语义搜索（当 embedding 可用时）
        semantic_scores: Dict[str, float] = {}
        if self._embedding and self._embedding.is_available() and self._vector_store:
            query_vec = await self._embedding.embed(problem)
            if query_vec:
                sem_results = await self._vector_store.search_top_k(
                    query_vec, k=10, source_type="fix_session"
                )
                for r in sem_results:
                    semantic_scores[r.source_id] = r.similarity

        # 关键词匹配（始终执行，用于兜底和混合排序）
        kw_results = await self._store.query_experiences(
            error_type=error_type, keyword=problem[:50], limit=10
        )

        # 合并结果：语义分数 + 关键词分数混合排序
        merged: Dict[str, Tuple[float, FixSession, List[FixAttempt]]] = {}
        for kw_score, session, attempts in kw_results:
            merged[session.id] = (kw_score, session, attempts)

        # 将语义搜索命中但关键词未命中的 session 补充进来
        if semantic_scores:
            for sid in semantic_scores:
                if sid not in merged:
                    session = await self._store.get_session(sid)
                    if session and session.status == FixStatus.RESOLVED:
                        attempts = await self._store.get_attempts(sid)
                        merged[sid] = (0.0, session, attempts)

        # 计算最终分数（语义 * weight + 关键词 * (1-weight)）
        scored: List[Tuple[float, FixSession, List[FixAttempt]]] = []
        for sid, (kw_score, session, attempts) in merged.items():
            sem_score = semantic_scores.get(sid, 0.0)
            if semantic_scores:
                # 混合模式
                final_score = sem_score * self._semantic_weight + kw_score * (1 - self._semantic_weight)
            else:
                # 纯关键词模式
                final_score = kw_score
            scored.append((final_score, session, attempts))

        scored.sort(key=lambda x: -x[0])
        results = scored[:5]

        relevant_experiences = []
        for score, session, attempts in results:
            blacklisted = await self._feedback.is_blacklisted(session.id)
            if blacklisted:
                continue
            decay = await self._feedback.get_decay_factor(session.id)
            good_attempts = [a.to_dict() for a in attempts if a.result in ("success", "partial")]
            if good_attempts:
                relevant_experiences.append({
                    "session_id": session.id,
                    "problem": session.problem,
                    "resolution": session.resolution,
                    "final_experience": session.final_experience,
                    "relevant_attempts": good_attempts[:3],
                    "relevance_score": round(score * decay, 3),
                })

        return {
            "current_session_id": current_session.id if current_session else None,
            "relevant_experiences": relevant_experiences,
            "count": len(relevant_experiences),
        }

    async def report_fix_attempt(self, session_id: str, agent_id: str,
                                  approach: str, reasoning: str,
                                  result: str, result_detail: str = "",
                                  modified_files: Optional[List[str]] = None,
                                  code_changes: str = "",
                                  confidence: float = 0.5) -> Dict:
        # Anti-loop check
        existing_attempts = await self._store.get_attempts(session_id)
        previous_approaches = [a.approach for a in existing_attempts]

        level, message = self._antiloop.check(approach, previous_approaches)
        if level == "block":
            return {
                "status": "blocked",
                "reason": message,
                "attempt_id": None,
            }

        attempt = await self._store.add_attempt(
            session_id=session_id,
            approach=approach,
            reasoning=reasoning,
            result=result,
            result_detail=result_detail,
            modified_files=modified_files,
            code_changes=code_changes,
            confidence=confidence,
        )

        response: Dict = {
            "status": "recorded",
            "attempt_id": attempt.id,
            "result": result,
        }
        if level == "warn":
            response["warning"] = message

        cfg_session = self._cfg.session
        if len(existing_attempts) + 1 >= cfg_session.max_attempts_per_session:
            response["max_attempts_warning"] = (
                f"⚠️ 本次修复会话已尝试 {cfg_session.max_attempts_per_session} 次，"
                "建议请求人工介入或放弃当前方案。"
            )

        return response

    async def _find_active_session(self, task_id: str, agent_id: str) -> Optional[FixSession]:
        session_ids = await self._redis.smembers(
            self._redis.key("fixexp", "agent", agent_id, "sessions")
        )
        for sid in session_ids:
            session = await self._store.get_session(sid)
            if session and session.task_id == task_id and session.status == FixStatus.ACTIVE:
                return session
        return None

    async def feedback_experience(self, exp_id: str, session_id: str,
                                   label: str = "",
                                   feedback_type: str = "",
                                   negative_tags: Optional[List[str]] = None,
                                   reason: str = "",
                                   note: str = "") -> Dict:
        """提交经验反馈，支持负面词标签体系。

        Args:
            exp_id: 被反馈的经验 ID
            session_id: 反馈时所在的 Fix Session ID
            label: 旧接口兼容（good/bad/misleading），优先使用 feedback_type
            feedback_type: 反馈类型（helpful/negative/misleading/irrelevant/outdated）
            negative_tags: 负面词标签列表（多选）
            reason: 反馈原因说明
            note: 备注（兼容旧接口）
        """
        # 优先使用 feedback_type，兼容旧的 label 参数
        effective_type = feedback_type or label or "negative"
        return await self._feedback.submit_feedback(
            exp_id=exp_id,
            session_id=session_id,
            feedback_type=effective_type,
            negative_tags=negative_tags,
            reason=reason,
            note=note,
        )
