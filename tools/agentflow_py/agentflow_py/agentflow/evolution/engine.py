"""Evolution Engine: pattern detection, scoring, distillation."""
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from agentflow.common import generate_pattern_id, generate_evolution_id
from agentflow.config import EvolutionConfig
from agentflow.storage import RedisClient, SQLiteStore


@dataclass
class DistillAndEvolveParams:
    """Agent 主动发起经验提炼和进化的参数"""
    skill_type: str
    auto_apply: bool = True
    include_stale: bool = True
    max_proposals: int = 5


@dataclass
class DistillAndEvolveResult:
    """提炼进化结果"""
    skill_type: str
    experiences_analyzed: int = 0
    patterns_detected: int = 0
    proposals_generated: int = 0
    proposals_applied: int = 0
    proposals_pending: int = 0
    stale_rules_removed: int = 0
    duplicates_removed: int = 0
    proposals: List[Dict] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> Dict:
        return {
            "skill_type": self.skill_type,
            "experiences_analyzed": self.experiences_analyzed,
            "patterns_detected": self.patterns_detected,
            "proposals_generated": self.proposals_generated,
            "proposals_applied": self.proposals_applied,
            "proposals_pending": self.proposals_pending,
            "stale_rules_removed": self.stale_rules_removed,
            "duplicates_removed": self.duplicates_removed,
            "proposals": self.proposals,
            "summary": self.summary,
        }


class EvolutionEngine:
    def __init__(self, redis: RedisClient, sqlite: Optional[SQLiteStore],
                 cfg: EvolutionConfig, logger: logging.Logger):
        self._redis = redis
        self._sqlite = sqlite
        self._cfg = cfg
        self._logger = logger
        self._evolution_count = 0

    # ── Experience Reporting ─────────────────────────────────────────────────

    async def report_experience(self, agent_id: str, skill_type: str,
                                 exp_type: str, category: str,
                                 description: str, evidence: str = "",
                                 confidence: float = 0.7,
                                 severity: float = 0.5) -> Dict:
        cfg = self._cfg.experience
        if len(description) < cfg.min_description_length:
            return {"status": "rejected", "reason": f"描述过短（最少{cfg.min_description_length}字符）"}
        if confidence < cfg.low_confidence_threshold:
            return {"status": "rejected", "reason": f"置信度过低（{confidence:.2f}）"}

        stream_key = self._redis.key("exp", exp_type if exp_type in ("positive", "negative") else "general")
        msg_id = await self._redis.xadd(stream_key, {
            "agent_id": agent_id,
            "skill_type": skill_type,
            "type": exp_type,
            "category": category,
            "description": description,
            "evidence": evidence,
            "confidence": str(confidence),
            "severity": str(severity),
            "score": str(severity * confidence),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, maxlen=cfg.stream_maxlen)

        # Try to detect pattern
        await self._detect_patterns(skill_type, category, exp_type)

        return {"status": "accepted", "exp_id": msg_id, "stream_key": stream_key}

    async def _detect_patterns(self, skill_type: str, category: str, exp_type: str) -> None:
        cfg = self._cfg.pattern
        stream_key = self._redis.key("exp", exp_type if exp_type in ("positive", "negative") else "general")
        msgs = await self._redis.xrevrange(stream_key, count=20)

        # Count similar category+skill_type combinations
        count = 0
        for msg in msgs:
            fields = msg.get("fields", {})
            if fields.get("skill_type") == skill_type and fields.get("category") == category:
                count += 1

        if count >= cfg.min_evidence:
            # Pattern detected — check if already recorded
            pattern_key = self._redis.key("evo", "patterns")
            pattern_id = f"pat:{skill_type}:{category}:{exp_type}"
            existing = await self._redis.hget(pattern_key, pattern_id)
            if not existing:
                pattern = {
                    "id": pattern_id,
                    "skill_type": skill_type,
                    "category": category,
                    "type": exp_type,
                    "evidence_count": count,
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                }
                await self._redis.hset(pattern_key, {pattern_id: json.dumps(pattern)})
                self._logger.info(f"检测到新模式 pattern_id={pattern_id} evidence={count}")

    # ── Distill and Evolve ────────────────────────────────────────────────────

    async def distill_and_evolve(self, skill_type: str, agent_id: str = "") -> Dict:
        # Gather experiences for this skill
        experiences = []
        for stream_suffix in ("positive", "negative"):
            stream_key = self._redis.key("exp", stream_suffix)
            msgs = await self._redis.xrevrange(stream_key, count=50)
            for msg in msgs:
                fields = msg.get("fields", {})
                if fields.get("skill_type") == skill_type:
                    experiences.append(fields)

        if not experiences:
            return {"status": "no_experiences", "skill_type": skill_type}

        # Weighted scoring: severity × confidence
        scored = []
        for exp in experiences:
            severity = float(exp.get("severity", 0.5))
            confidence = float(exp.get("confidence", 0.7))
            score = severity * confidence
            scored.append((score, exp))
        scored.sort(key=lambda x: -x[0])

        # Extract top insights
        new_rules = []
        new_anti_patterns = []
        new_best_practices = []

        for score, exp in scored[:10]:
            desc = exp.get("description", "")
            exp_type = exp.get("type", "")
            category = exp.get("category", "")
            if exp_type == "negative" and score >= 0.4:
                if category in ("bug", "design_flaw", "architecture"):
                    new_anti_patterns.append(desc[:120])
                else:
                    new_rules.append(f"避免: {desc[:100]}")
            elif exp_type == "positive" and score >= 0.4:
                if category in ("pattern", "technique", "optimization"):
                    new_best_practices.append(desc[:120])
                else:
                    new_rules.append(desc[:100])

        if not new_rules and not new_anti_patterns and not new_best_practices:
            return {"status": "no_changes", "skill_type": skill_type}

        # Apply via evolver
        from agentflow.skill.evolver import SkillEvolver
        from agentflow.skill.store import SkillStore
        skill_store = SkillStore(self._redis, __import__("agentflow.config", fromlist=["SkillConfig"]).SkillConfig(), self._logger)
        evolver = SkillEvolver(skill_store, self._redis, __import__("agentflow.config", fromlist=["SkillConfig"]).SkillConfig(), self._logger)
        dna = await evolver.apply_evolution(skill_type, {
            "new_rules": new_rules[:5],
            "new_anti_patterns": new_anti_patterns[:5],
            "new_best_practices": new_best_practices[:5],
        }, source=f"distill_by_{agent_id}")

        # Log evolution
        evo_id = generate_evolution_id()
        evo_log_key = self._redis.key("evo", "log")
        await self._redis.xadd(evo_log_key, {
            "evo_id": evo_id,
            "type": "distill_and_evolve",
            "target": skill_type,
            "agent_id": agent_id,
            "rules_added": str(len(new_rules)),
            "anti_patterns_added": str(len(new_anti_patterns)),
            "best_practices_added": str(len(new_best_practices)),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, maxlen=self._cfg.evo_log_maxlen)

        self._evolution_count += 1
        self._logger.info(f"Skill DNA 提炼进化完成 skill_type={skill_type} evo_id={evo_id}")

        return {
            "status": "evolved",
            "skill_type": skill_type,
            "evo_id": evo_id,
            "rules_added": len(new_rules),
            "anti_patterns_added": len(new_anti_patterns),
            "best_practices_added": len(new_best_practices),
            "total_experiences": len(experiences),
        }

    # ── Audit ─────────────────────────────────────────────────────────────────

    async def audit_skill_quality(self, skill_type: str) -> Dict:
        from agentflow.skill.store import SkillStore
        skill_store = SkillStore(self._redis, __import__("agentflow.config", fromlist=["SkillConfig"]).SkillConfig(), self._logger)
        dna = await skill_store.get_dna(skill_type)
        if not dna:
            return {"status": "not_found", "skill_type": skill_type}

        issues = []
        cfg_limits = self._cfg.pattern

        if len(dna.rules) == 0:
            issues.append("无规则定义")
        if len(dna.anti_patterns) == 0:
            issues.append("无反模式定义")

        # Check stale rules (rules with low evidence support)
        stale_rules = []
        for evidence in dna.evidence_chain:
            if evidence.confidence < 0.3:
                stale_rules.append(evidence.rule[:50])
        if stale_rules:
            issues.append(f"低置信度规则: {len(stale_rules)} 条")

        metrics = await skill_store.get_metrics(skill_type)
        quality_score = 100
        if issues:
            quality_score -= len(issues) * 15
        if metrics and metrics.success_rate < 0.7 and metrics.total_tasks > 5:
            quality_score -= 20
            issues.append(f"成功率偏低: {metrics.success_rate:.1%}")

        return {
            "skill_type": skill_type,
            "quality_score": max(0, quality_score),
            "issues": issues,
            "rules_count": len(dna.rules),
            "anti_patterns_count": len(dna.anti_patterns),
            "best_practices_count": len(dna.best_practices),
            "version": dna.version,
            "metrics": metrics.to_dict() if metrics else None,
        }

    # ── Status ────────────────────────────────────────────────────────────────

    async def get_evolution_status(self) -> Dict:
        # Get recent evolution log
        msgs = await self._redis.xrevrange(self._redis.key("evo", "log"), count=10)
        recent_evolutions = []
        for msg in msgs:
            f = msg.get("fields", {})
            recent_evolutions.append({
                "evo_id": f.get("evo_id", ""),
                "type": f.get("type", ""),
                "target": f.get("target", ""),
                "timestamp": f.get("timestamp", ""),
            })

        # Pattern count
        patterns = await self._redis.hgetall(self._redis.key("evo", "patterns"))

        # Pending approvals
        pending_count = await self._redis.llen(self._redis.key("evo", "pending_approvals"))

        # All skills metrics
        skill_types = await self._redis.smembers(self._redis.key("skill", "types"))
        skill_stats = []
        for st in skill_types:
            metrics_data = await self._redis.hgetall(self._redis.key("skill", st, "metrics"))
            skill_stats.append({
                "skill_type": st,
                "total_tasks": int(metrics_data.get("total_tasks", 0)),
                "success_rate": float(metrics_data.get("success_rate", 0.0)),
                "last_evolved": metrics_data.get("last_evolved", ""),
            })

        return {
            "total_evolutions": self._evolution_count,
            "total_patterns": len(patterns),
            "pending_approvals": pending_count,
            "recent_evolutions": recent_evolutions,
            "skill_stats": skill_stats,
        }

    async def get_experiences(self, skill_type: str = "", exp_type: str = "",
                               limit: int = 20) -> List[Dict]:
        streams = []
        if exp_type in ("positive", "negative"):
            streams = [self._redis.key("exp", exp_type)]
        else:
            streams = [self._redis.key("exp", "positive"), self._redis.key("exp", "negative")]

        results = []
        for stream_key in streams:
            msgs = await self._redis.xrevrange(stream_key, count=limit)
            for msg in msgs:
                fields = msg.get("fields", {})
                if skill_type and fields.get("skill_type") != skill_type:
                    continue
                results.append({"id": msg["id"], **fields})

        results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return results[:limit]

    # ── Snapshot (for advanced.py integration) ─────────────────────────────────

    async def create_snapshot(self, agent_id: str, note: str = "") -> Dict:
        skill_types = await self._redis.smembers(self._redis.key("skill", "types"))
        from agentflow.skill.store import SkillStore
        skill_store = SkillStore(self._redis, __import__("agentflow.config", fromlist=["SkillConfig"]).SkillConfig(), self._logger)
        snapshot_data = {}
        total_score = 0.0
        for st in skill_types:
            dna = await skill_store.get_dna(st)
            if dna:
                snapshot_data[st] = dna.to_dict()
                metrics = await skill_store.get_metrics(st)
                if metrics:
                    total_score += metrics.success_rate

        avg_score = total_score / max(1, len(skill_types))
        from agentflow.common import generate_archive_id
        archive_id = generate_archive_id()
        now = datetime.now(timezone.utc).isoformat()

        if self._sqlite:
            await self._sqlite.archive_agent_snapshot(
                archive_id, json.dumps(snapshot_data), avg_score, now, note
            )

        await self._redis.lpush(self._redis.key("evo", "archives"), json.dumps({
            "archive_id": archive_id,
            "score": avg_score,
            "created_at": now,
            "note": note,
        }))

        self._logger.info(f"快照已创建 archive_id={archive_id} score={avg_score:.3f}")
        return {"archive_id": archive_id, "score": avg_score, "skill_count": len(skill_types), "note": note}

    async def approve_evolution(self, proposal_id: str, approved: bool, reviewer: str = "") -> Dict:
        pending_key = self._redis.key("evo", "pending_approvals")
        items = await self._redis.lrange(pending_key, 0, -1)
        for i, item_str in enumerate(items):
            try:
                item = json.loads(item_str)
                if item.get("proposal_id") == proposal_id:
                    await self._redis.lrem(pending_key, 1, item_str)
                    if approved:
                        await self.distill_and_evolve(item.get("skill_type", ""), reviewer)
                    status = "approved" if approved else "rejected"
                    self._logger.info(f"进化提案{status} proposal_id={proposal_id} reviewer={reviewer}")
                    return {"status": status, "proposal_id": proposal_id}
            except Exception:
                continue
        return {"status": "not_found", "proposal_id": proposal_id}

    # ── Advanced: Approve Evolution (Go 对齐版) ──────────────────────────────

    async def approve_evolution_v2(self, evo_id: str, action: str,
                                    modification: str = "", approver: str = "",
                                    approval_reason: str = "") -> Dict:
        """审批进化提案（Go 对齐版）。
        action: approve | reject | modify
        高影响提案(impact >= 0.5) 审批时必须提供 approval_reason。
        """
        if not evo_id:
            raise ValueError("evo_id 不能为空")

        pending_key = self._redis.key("evo", "pending", evo_id)
        evo_data = await self._redis.hgetall(pending_key)
        if not evo_data:
            raise ValueError(f"进化提案 {evo_id} 不存在或已处理")

        # 判断是否为高影响提案
        is_high_impact = self._is_high_impact_proposal(evo_data)
        if is_high_impact and not approval_reason and action in ("approve", "modify"):
            raise ValueError("高影响进化提案(impact >= 0.5)审批时必须提供 approval_reason")

        if not approver:
            approver = "unknown"

        approved_at = datetime.now(timezone.utc).isoformat()
        result: Dict[str, Any] = {
            "evo_id": evo_id,
            "action": action,
            "approver": approver,
            "approved_at": approved_at,
            "high_impact": is_high_impact,
        }
        if approval_reason:
            result["approval_reason"] = approval_reason

        evo_log_key = self._redis.key("evo", "log")

        if action == "approve":
            # 高影响提案审批前自动快照
            if is_high_impact:
                try:
                    snap = await self.snapshot_agent(trigger="auto",
                                                      note=f"高影响进化审批前自动快照 (evo_id: {evo_id})")
                    result["rollback_snapshot_id"] = snap["archive_id"]
                except Exception as e:
                    self._logger.warning(f"审批前自动快照失败，继续审批 error={e}")

            # 解析提案内容，检查是否为 create_skill 类型
            proposal_json = evo_data.get("proposal", "")
            proposal_obj: Optional[Dict] = None
            if proposal_json:
                try:
                    proposal_obj = json.loads(proposal_json)
                except Exception:
                    pass

            if proposal_obj is not None:
                proposal_action = proposal_obj.get("action", "")
                if proposal_action == "create_skill":
                    # 执行创建新 Skill
                    try:
                        await self._execute_create_skill(proposal_obj)
                        new_skill_name = proposal_obj.get("new_skill_name", "")
                        result["status"] = "applied"
                        result["detail"] = f"新 Skill {new_skill_name} 已自动创建"
                        result["action_type"] = "create_skill"
                        result["new_skill_name"] = new_skill_name
                    except Exception as e:
                        raise ValueError(f"创建 Skill 失败: {e}") from e
                else:
                    result["status"] = "applied"
                    result["detail"] = "进化已应用"
            else:
                result["status"] = "applied"
                result["detail"] = "进化已应用"

            log_values: Dict[str, str] = {
                "timestamp": approved_at,
                "evolution_type": evo_data.get("evolution_type", ""),
                "target": evo_data.get("skill_type", ""),
                "trigger": "human_approved",
                "evo_id": evo_id,
                "approver": approver,
                "high_impact": str(is_high_impact),
            }
            if approval_reason:
                log_values["approval_reason"] = approval_reason
            if "rollback_snapshot_id" in result:
                log_values["rollback_snapshot_id"] = result["rollback_snapshot_id"]
            await self._redis.xadd(evo_log_key, log_values,
                                   maxlen=self._cfg.evo_log_maxlen)

            # 更新校准计数
            calib_key = self._redis.key("safety", "evo_since_calibration")
            await self._redis.incr(calib_key)

        elif action == "reject":
            result["status"] = "rejected"
            result["detail"] = "进化已拒绝"

            log_values = {
                "timestamp": approved_at,
                "evolution_type": evo_data.get("evolution_type", ""),
                "target": evo_data.get("skill_type", ""),
                "trigger": "human_rejected",
                "evo_id": evo_id,
                "approver": approver,
            }
            if approval_reason:
                log_values["approval_reason"] = approval_reason
            await self._redis.xadd(evo_log_key, log_values,
                                   maxlen=self._cfg.evo_log_maxlen)

        elif action == "modify":
            # 解析 modification 参数（JSON 格式），合并到提案的 changes 字段
            modification_changes: Dict = {}
            if modification:
                try:
                    modification_changes = json.loads(modification)
                except Exception as e:
                    self._logger.warning(f"modification 参数解析失败，将作为文本处理 error={e}")
                    modification_changes = {"raw_modification": modification}

            # 将修改内容合并到原始提案的 changes 字段
            proposal_json = evo_data.get("proposal", "")
            merged_proposal: Optional[Dict] = None
            if proposal_json:
                try:
                    merged_proposal = json.loads(proposal_json)
                except Exception:
                    merged_proposal = {}
            else:
                merged_proposal = {}

            # 合并修改内容到提案
            if modification_changes:
                existing_changes = merged_proposal.get("changes", {})
                if isinstance(existing_changes, dict):
                    existing_changes.update(modification_changes)
                else:
                    existing_changes = modification_changes
                merged_proposal["changes"] = existing_changes
                # 同步更新顶层字段（rules/anti_patterns/best_practices 等）
                for key in ("new_rules", "new_anti_patterns", "new_best_practices",
                             "rules", "anti_patterns", "best_practices"):
                    if key in modification_changes:
                        merged_proposal[key] = modification_changes[key]

            result["status"] = "modified"
            result["detail"] = "进化已修改后应用"
            result["modification"] = modification

            if is_high_impact:
                try:
                    snap = await self.snapshot_agent(trigger="auto",
                                                      note=f"高影响进化修改审批前自动快照 (evo_id: {evo_id})")
                    result["rollback_snapshot_id"] = snap["archive_id"]
                except Exception as e:
                    self._logger.warning(f"审批前自动快照失败，继续审批 error={e}")

            # 执行与 approve 相同的应用逻辑（使用合并后的提案）
            if merged_proposal is not None:
                proposal_action = merged_proposal.get("action", "")
                if proposal_action == "create_skill":
                    try:
                        await self._execute_create_skill(merged_proposal)
                        new_skill_name = merged_proposal.get("new_skill_name", "")
                        result["detail"] = f"新 Skill {new_skill_name} 已修改后创建"
                        result["action_type"] = "create_skill"
                        result["new_skill_name"] = new_skill_name
                    except Exception as e:
                        raise ValueError(f"修改后创建 Skill 失败: {e}") from e
                else:
                    # 应用 DNA 变更
                    try:
                        await self._apply_distill_proposal(evo_data.get("skill_type", ""), merged_proposal)
                        result["detail"] = "进化已修改后应用到 Skill DNA"
                    except Exception as e:
                        self._logger.warning(f"应用修改后提案失败 error={e}")

            log_values = {
                "timestamp": approved_at,
                "evolution_type": evo_data.get("evolution_type", ""),
                "target": evo_data.get("skill_type", ""),
                "trigger": "human_modified",
                "evo_id": evo_id,
                "approver": approver,
                "modification": modification,
            }
            if approval_reason:
                log_values["approval_reason"] = approval_reason
            if "rollback_snapshot_id" in result:
                log_values["rollback_snapshot_id"] = result["rollback_snapshot_id"]
            await self._redis.xadd(evo_log_key, log_values,
                                   maxlen=self._cfg.evo_log_maxlen)

            # 更新校准计数
            calib_key = self._redis.key("safety", "evo_since_calibration")
            await self._redis.incr(calib_key)
        else:
            raise ValueError(f"不支持的 action: {action}，可选: approve | reject | modify")

        # 记录审批历史
        await self._record_approval_history(evo_id, action, approver, approval_reason,
                                             evo_data, result, is_high_impact)

        # 清理待处理提案
        await self._redis.delete(pending_key)
        # 从 pending 列表移除
        pending_list_key = self._redis.key("evo", "pending")
        await self._redis.lrem(pending_list_key, 1, evo_id)

        self._logger.info(f"进化提案已处理 evo_id={evo_id} action={action} "
                          f"approver={approver} high_impact={is_high_impact}")
        return result

    async def _execute_create_skill(self, proposal: Dict) -> None:
        """执行创建新 Skill（由 approve_evolution_v2 调用，对齐 Go 版本 ExecuteCreateSkill）。
        从提案中提取 skill_name、description、rules、anti_patterns、best_practices，
        然后调用 SkillStore 创建新的 Skill DNA。
        """
        skill_name = proposal.get("new_skill_name", "")
        if not skill_name:
            raise ValueError("create_skill 提案缺少 new_skill_name")

        description = proposal.get("description", "")

        # 提取 DNA 组件（兼容 list[str] 和 list[Any] 两种格式）
        def extract_str_list(key: str) -> List[str]:
            raw = proposal.get(key, [])
            if isinstance(raw, list):
                return [str(item) for item in raw if item]
            return []

        rules = extract_str_list("rules")
        anti_patterns = extract_str_list("anti_patterns")
        best_practices = extract_str_list("best_practices")

        # 通过 SkillStore 创建新 Skill DNA
        from agentflow.skill.store import SkillStore
        import agentflow.config as _cfg
        skill_store = SkillStore(self._redis, _cfg.SkillConfig(), self._logger)

        # 检查是否已存在
        existing = await skill_store.get_dna(skill_name)
        if existing:
            self._logger.warning(f"Skill {skill_name} 已存在，跳过创建")
            return

        from agentflow.skill.model import SkillDNA
        dna = SkillDNA(
            skill_type=skill_name,
            rules=rules[:20],
            anti_patterns=anti_patterns[:15],
            best_practices=best_practices[:15],
            context_hints=[description] if description else [],
        )
        await skill_store.save_dna(dna)

        # 记录进化日志
        evo_log_key = self._redis.key("evo", "log")
        await self._redis.xadd(evo_log_key, {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "evolution_type": "create_skill",
            "target": skill_name,
            "trigger": "experience_driven",
            "rules_count": str(len(rules)),
            "anti_patterns": str(len(anti_patterns)),
            "best_practices": str(len(best_practices)),
        }, maxlen=self._cfg.evo_log_maxlen)

        self._logger.info(f"新 Skill 已自动创建 skill={skill_name} "
                          f"rules={len(rules)} anti_patterns={len(anti_patterns)} "
                          f"best_practices={len(best_practices)}")

    def _is_high_impact_proposal(self, evo_data: Dict[str, str]) -> bool:
        """判断提案是否为高影响提案"""
        proposal_json = evo_data.get("proposal", "")
        if proposal_json:
            try:
                proposal = json.loads(proposal_json)
                impact = proposal.get("impact")
                if isinstance(impact, (int, float)) and impact >= 0.5:
                    return True
            except Exception:
                pass
        return evo_data.get("high_impact", "") == "true"

    async def _record_approval_history(self, evo_id: str, action: str, approver: str,
                                        approval_reason: str, evo_data: Dict[str, str],
                                        result: Dict, is_high_impact: bool) -> None:
        """记录审批历史到独立的审批历史流"""
        history_values: Dict[str, str] = {
            "evo_id": evo_id,
            "action": action,
            "approver": approver,
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "skill_type": evo_data.get("skill_type", ""),
            "evolution_type": evo_data.get("evolution_type", ""),
            "high_impact": str(is_high_impact),
        }
        if approval_reason:
            history_values["approval_reason"] = approval_reason
        if "rollback_snapshot_id" in result:
            history_values["rollback_snapshot_id"] = str(result["rollback_snapshot_id"])
        if result.get("modification"):
            history_values["modification"] = result["modification"]

        approval_history_key = self._redis.key("evo", "approval_history")
        await self._redis.xadd(approval_history_key, history_values, maxlen=200)

    # ── Advanced: Snapshot Agent (SICA 核心) ─────────────────────────────────

    async def snapshot_agent(self, trigger: str = "manual", note: str = "") -> Dict:
        """保存当前 Agent 状态快照到 Archive（SICA 核心）。
        自动计算综合评分（动态权重）。如果当前表现优于历史最佳→成为新 baseline。
        """
        import time as _time
        archive_id = f"arc_{int(_time.time() * 1000)}"

        # 收集所有 Skill 完整 DNA（修复：使用 skill:types，并存储完整 DNA 而非仅版本号）
        skill_names = await self._redis.smembers(self._redis.key("skill", "types"))
        skill_dna_snapshot: Dict[str, Dict] = {}
        for name in skill_names:
            try:
                dna_key = self._redis.key("skill", name, "dna")
                dna_data = await self._redis.hgetall(dna_key)
                if dna_data:
                    skill_dna_snapshot[name] = dna_data
            except Exception:
                pass

        # 收集全局规则
        rules_key = self._redis.key("ctx", "global_rules")
        rules = await self._redis.lrange(rules_key, 0, -1)

        # 计算综合评分
        score = await self._calculate_archive_score()

        # 获取历史最佳分数
        leaderboard = self._redis.key("archive", "leaderboard")
        top_entries = await self._redis.zrevrange_with_scores(leaderboard, 0, 0)
        best_score = top_entries[0][1] if top_entries else 0.0
        is_new_best = score > best_score

        # 存储 Archive
        archive_key = self._redis.key("archive", archive_id)
        await self._redis.hset(archive_key, {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "skills_snapshot": json.dumps(skill_dna_snapshot),
            "rules_snapshot": json.dumps(rules),
            "score": f"{score:.4f}",
            "trigger": trigger,
            "note": note,
        })

        # 更新排行榜
        await self._redis.zadd(leaderboard, {archive_id: score})

        # 只保留 Top 10
        await self._redis.zremrangebyrank(leaderboard, 0, -11)

        # 记录进化日志
        evo_log_key = self._redis.key("evo", "log")
        await self._redis.xadd(evo_log_key, {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "evolution_type": "snapshot",
            "target": "agent",
            "trigger": trigger,
            "archive_id": archive_id,
            "score": f"{score:.4f}",
            "is_new_best": str(is_new_best),
        }, maxlen=self._cfg.evo_log_maxlen)

        self._logger.info(f"Agent 快照已保存 archive_id={archive_id} "
                          f"score={score:.4f} best={best_score:.4f} is_new_best={is_new_best}")

        return {
            "archive_id": archive_id,
            "score": score,
            "best_score": best_score,
            "is_new_best": is_new_best,
            "score_delta": score - best_score,
        }

    async def _calculate_archive_score(self) -> float:
        """计算 Archive 综合评分（动态权重）"""
        completed_key = self._redis.key("task", "queue", "completed")
        failed_key = self._redis.key("task", "queue", "failed")

        completed_count = await self._redis.zcard(completed_key)
        failed_count = await self._redis.zcard(failed_key)
        total_tasks = completed_count + failed_count

        if total_tasks == 0:
            return 0.0

        pass_rate = completed_count / total_tasks
        token_efficiency = 0.7  # 默认值
        retry_rate = 0.1        # 默认低重试率

        # 动态权重（根据项目阶段）
        early_threshold = getattr(self._cfg, "early_phase_threshold", 20)
        mid_threshold = getattr(self._cfg, "mid_phase_threshold", 100)

        if total_tasks < early_threshold:
            w1, w2, w3, w4 = 0.5, 0.2, 0.2, 0.1
        elif total_tasks < mid_threshold:
            w1, w2, w3, w4 = 0.4, 0.3, 0.2, 0.1
        else:
            w1, w2, w3, w4 = 0.3, 0.35, 0.2, 0.15

        raw_score = pass_rate * w1 + token_efficiency * w2 + (1 - retry_rate) * w3 + 0.5 * w4
        return raw_score

    # ── Advanced: Rollback to Archive ────────────────────────────────────────

    async def rollback_to_archive(self, archive_id: str) -> Dict:
        """回滚到历史最佳配置（从 Archive 恢复 Skill 版本）"""
        if not archive_id:
            raise ValueError("archive_id 不能为空")

        # 从 Redis 读取 Archive
        archive_key = self._redis.key("archive", archive_id)
        archive_data = await self._redis.hgetall(archive_key)

        # 若 Redis 中不存在，尝试从 SQLite 读取
        if not archive_data and self._sqlite:
            try:
                rows = await self._sqlite.fetchall(
                    "SELECT * FROM agent_archives WHERE archive_id=?", (archive_id,)
                )
                if rows:
                    archive_data = dict(rows[0])
            except Exception as e:
                self._logger.warning(f"从 SQLite 读取 Archive 失败 error={e}")

        if not archive_data:
            raise ValueError(f"Archive {archive_id} 不存在")

        # 解析 skills_snapshot（支持新格式：完整 DNA dict；兼容旧格式：{name: version}）
        skills_snapshot_raw = archive_data.get("skills_snapshot", "{}")
        try:
            skills_snapshot = json.loads(skills_snapshot_raw)
        except Exception:
            skills_snapshot = {}

        # 恢复每个 Skill 完整 DNA
        restored = 0
        for skill_name, dna_data in skills_snapshot.items():
            try:
                dna_key = self._redis.key("skill", skill_name, "dna")
                if isinstance(dna_data, dict) and len(dna_data) > 1:
                    # 新格式：完整 DNA dict，直接恢复
                    await self._redis.hset(dna_key, dna_data)
                    # 同步更新 meta 中的 version
                    version = dna_data.get("version", "1")
                    meta_key = self._redis.key("skill", skill_name, "meta")
                    await self._redis.hset(meta_key, {"version": str(version)})
                    # 确保 skill:types 中包含该 skill
                    await self._redis.sadd(self._redis.key("skill", "types"), skill_name)
                else:
                    # 旧格式兼容：只有版本号，仅更新 version 字段
                    version = dna_data if isinstance(dna_data, str) else str(dna_data)
                    await self._redis.hset(dna_key, {"version": version})
                    meta_key = self._redis.key("skill", skill_name, "meta")
                    await self._redis.hset(meta_key, {"version": version})
                restored += 1
            except Exception as e:
                self._logger.warning(f"恢复 Skill {skill_name} 失败 error={e}")

        # 记录回滚日志
        evo_log_key = self._redis.key("evo", "log")
        await self._redis.xadd(evo_log_key, {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "evolution_type": "rollback",
            "target": "agent",
            "archive_id": archive_id,
            "skills_restored": str(restored),
            "original_score": archive_data.get("score", "0"),
        }, maxlen=self._cfg.evo_log_maxlen)

        self._logger.info(f"已回滚到 Archive archive_id={archive_id} skills_restored={restored}")

        return {
            "status": "rolled_back",
            "archive_id": archive_id,
            "skills_restored": restored,
            "original_score": float(archive_data.get("score", 0)),
            "original_timestamp": archive_data.get("timestamp", ""),
            "note": archive_data.get("note", ""),
        }

    # ── Advanced: Safety Report (五维检测) ───────────────────────────────────

    async def get_safety_report(self) -> Dict:
        """获取安全报告（五维检测）：
        1. 进化频率检测
        2. 高影响进化比例
        3. 待审批积压
        4. 近期失败率
        5. 校准距离
        """
        report: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "dimensions": {},
            "overall_status": "safe",
            "warnings": [],
            "recommendations": [],
        }

        # 维度1: 进化频率检测（近24小时进化次数）
        evo_log_key = self._redis.key("evo", "log")
        recent_evos = await self._redis.xrevrange(evo_log_key, count=50)
        now_ts = time.time()
        evo_last_24h = 0
        for msg in recent_evos:
            ts_str = msg.get("fields", {}).get("timestamp", "")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if (now_ts - ts.timestamp()) < 86400:
                        evo_last_24h += 1
                except Exception:
                    pass

        evo_freq_status = "safe"
        evo_freq_threshold = getattr(self._cfg, "max_evolutions_per_day", 20)
        if evo_last_24h > evo_freq_threshold:
            evo_freq_status = "warning"
            report["warnings"].append(f"进化频率过高: 近24小时 {evo_last_24h} 次（阈值 {evo_freq_threshold}）")
            report["recommendations"].append("建议暂停自动进化，人工审查进化质量")

        report["dimensions"]["evolution_frequency"] = {
            "status": evo_freq_status,
            "evolutions_last_24h": evo_last_24h,
            "threshold": evo_freq_threshold,
        }

        # 维度2: 高影响进化比例
        high_impact_count = 0
        for msg in recent_evos[:20]:
            fields = msg.get("fields", {})
            if fields.get("high_impact") == "True":
                high_impact_count += 1
        total_recent = min(len(recent_evos), 20)
        high_impact_ratio = high_impact_count / max(1, total_recent)

        impact_status = "safe"
        if high_impact_ratio > 0.5:
            impact_status = "warning"
            report["warnings"].append(f"高影响进化比例过高: {high_impact_ratio:.0%}")
            report["recommendations"].append("建议加强高影响进化的人工审批流程")

        report["dimensions"]["high_impact_ratio"] = {
            "status": impact_status,
            "high_impact_count": high_impact_count,
            "total_recent": total_recent,
            "ratio": round(high_impact_ratio, 3),
        }

        # 维度3: 待审批积压
        pending_list_key = self._redis.key("evo", "pending")
        pending_count = await self._redis.llen(pending_list_key)
        pending_status = "safe"
        pending_threshold = getattr(self._cfg, "max_pending_approvals", 10)
        if pending_count > pending_threshold:
            pending_status = "warning"
            report["warnings"].append(f"待审批积压: {pending_count} 个（阈值 {pending_threshold}）")
            report["recommendations"].append("建议及时处理待审批的进化提案")

        report["dimensions"]["pending_approvals"] = {
            "status": pending_status,
            "pending_count": pending_count,
            "threshold": pending_threshold,
        }

        # 维度4: 近期任务失败率
        completed_key = self._redis.key("task", "queue", "completed")
        failed_key = self._redis.key("task", "queue", "failed")
        completed_count = await self._redis.zcard(completed_key)
        failed_count = await self._redis.zcard(failed_key)
        total = completed_count + failed_count
        fail_rate = failed_count / max(1, total)

        fail_status = "safe"
        fail_threshold = getattr(self._cfg, "max_fail_rate", 0.3)
        if total > 5 and fail_rate > fail_threshold:
            fail_status = "warning"
            report["warnings"].append(f"任务失败率偏高: {fail_rate:.0%}（阈值 {fail_threshold:.0%}）")
            report["recommendations"].append("建议检查近期进化是否引入了回归问题，考虑回滚")

        report["dimensions"]["task_failure_rate"] = {
            "status": fail_status,
            "completed": completed_count,
            "failed": failed_count,
            "fail_rate": round(fail_rate, 3),
            "threshold": fail_threshold,
        }

        # 维度5: 校准距离（距上次校准的进化次数）
        calib_key = self._redis.key("safety", "evo_since_calibration")
        evo_since_calib_str = await self._redis.get(calib_key)
        evo_since_calib = int(evo_since_calib_str) if evo_since_calib_str else 0
        calib_threshold = getattr(self._cfg, "calibration_interval", 50)
        calib_status = "safe"
        if evo_since_calib > calib_threshold:
            calib_status = "warning"
            report["warnings"].append(f"距上次校准已进化 {evo_since_calib} 次（阈值 {calib_threshold}），建议重新校准")
            report["recommendations"].append("调用 snapshot_agent 创建基准快照并重置校准计数")

        report["dimensions"]["calibration_distance"] = {
            "status": calib_status,
            "evo_since_calibration": evo_since_calib,
            "threshold": calib_threshold,
        }

        # 汇总整体状态
        all_statuses = [d["status"] for d in report["dimensions"].values()]
        if "critical" in all_statuses:
            report["overall_status"] = "critical"
        elif "warning" in all_statuses:
            report["overall_status"] = "warning"
        else:
            report["overall_status"] = "safe"

        return report

    # ── Advanced: Trigger Evolution (升级版) ─────────────────────────────────

    async def trigger_evolution_v2(self, scope: str = "all", target: str = "",
                                    force: bool = False) -> Dict:
        """手动触发进化分析（Go 对齐版）。
        scope: skill | rules | strategy | all
        target: skill_name 或 "global"
        force=True 跳过最少证据阈值
        """
        result: Dict[str, Any] = {
            "patterns_found": 0,
            "proposed_changes": [],
            "estimated_impact": {},
            "safety_assessment": "reviewed",
        }

        # 确定目标 Skill 列表
        if scope == "skill" and target and target != "global":
            target_skills = [target]
        else:
            target_skills = list(await self._redis.smembers(self._redis.key("skill", "types")))

        total_patterns = 0
        min_evidence = getattr(self._cfg.pattern, "min_evidence", 3)

        for skill_name in target_skills:
            index_key = self._redis.key("pattern", "index", skill_name)
            try:
                patterns = await self._redis.zrevrange_with_scores(index_key, 0, 9)
            except Exception:
                continue

            for pattern_key, occurrences in patterns:
                occurrences_int = int(occurrences)
                if not force and occurrences_int < min_evidence:
                    continue

                total_patterns += 1
                result["proposed_changes"].append({
                    "skill": skill_name,
                    "pattern": pattern_key,
                    "occurrences": occurrences_int,
                    "action": "add_anti_pattern_or_rule",
                    "evidence": f"该模式出现 {occurrences_int} 次",
                })

        result["patterns_found"] = total_patterns
        result["estimated_impact"] = {
            "affected_skills": len(target_skills),
            "patterns": total_patterns,
            "risk_level": self._assess_risk(total_patterns),
        }
        if total_patterns > 5:
            result["safety_assessment"] = "needs_human_review"

        return result

    @staticmethod
    def _assess_risk(pattern_count: int) -> str:
        """评估风险等级"""
        if pattern_count > 10:
            return "high"
        elif pattern_count > 3:
            return "medium"
        return "low"

    # ── Advanced: Distill and Evolve (升级版，支持 DistillAndEvolveParams) ───

    async def distill_and_evolve_advanced(self, params: DistillAndEvolveParams) -> DistillAndEvolveResult:
        """主动发起经验提炼整理和进化（Go 对齐版）。
        流程: 汇总经验 → 去重整理 → 模式检测 → 生成提案 → 低影响自动应用 → 高影响待审批
        """
        if not params.skill_type:
            raise ValueError("skill_type 不能为空")
        if params.max_proposals <= 0:
            params.max_proposals = 5

        result = DistillAndEvolveResult(skill_type=params.skill_type)

        # 1. 汇总该 Skill 的所有经验（正+负）
        positive_exps = await self.get_experiences(params.skill_type, "positive", 100)
        negative_exps = await self.get_experiences(params.skill_type, "negative", 100)
        result.experiences_analyzed = len(positive_exps) + len(negative_exps)

        if result.experiences_analyzed == 0:
            result.summary = f"Skill {params.skill_type} 暂无经验数据，无法进行提炼进化"
            return result

        # 2. 按 category 聚合经验
        category_groups: Dict[str, List[Dict]] = {}
        for exp in positive_exps + negative_exps:
            cat = exp.get("category", "general")
            if cat not in category_groups:
                category_groups[cat] = []
            category_groups[cat].append(exp)

        # 3. 从经验中提取可进化的模式
        proposals: List[Dict] = []
        proposal_count = 0

        for category, exps in category_groups.items():
            if proposal_count >= params.max_proposals:
                break
            if len(exps) < 2:
                continue

            result.patterns_detected += 1

            # 收集证据 ID
            evidence_ids = [exp.get("id", "") for exp in exps if exp.get("id")]

            # 从负经验提取反模式
            anti_patterns = [exp["root_cause"] for exp in exps if exp.get("root_cause")]
            solutions = [exp["solution"] for exp in exps if exp.get("solution")]

            # 从正经验提取最佳实践
            best_practices = [
                exp["description"] for exp in exps
                if not exp.get("root_cause") and len(exp.get("description", "")) >= 50
            ]

            # 计算影响度
            impact = 0.3
            if category in ("architecture", "security"):
                impact = 0.7
            if len(exps) >= 5:
                impact = max(impact, 0.5)

            proposal: Dict[str, Any] = {
                "category": category,
                "evidence_count": len(exps),
                "skill": params.skill_type,
                "anti_patterns": anti_patterns,
                "best_practices": best_practices,
                "solutions": solutions,
                "evidence_ids": evidence_ids,
                "impact": impact,
                "action": "evolve_dna",
            }
            proposals.append(proposal)
            proposal_count += 1

        result.proposals_generated = len(proposals)
        result.proposals = proposals

        # 4. 自动应用低影响提案，高影响提案放入待审批队列
        import time as _time
        import uuid as _uuid
        applied = 0
        pending = 0
        for proposal in proposals:
            impact_val = proposal.get("impact", 0.3)
            if params.auto_apply and impact_val < 0.5:
                # 低影响: 直接提炼应用
                await self._apply_distill_proposal(params.skill_type, proposal)
                proposal["status"] = "applied"
                applied += 1
            else:
                # 高影响: 放入待审批队列
                evo_id = f"evo_distill_{int(_time.time() * 1000)}_{params.skill_type}_{_uuid.uuid4().hex[:6]}"
                await self._queue_proposal(evo_id, params.skill_type, proposal)
                proposal["status"] = "pending_approval"
                proposal["evo_id"] = evo_id
                pending += 1

        result.proposals_applied = applied
        result.proposals_pending = pending

        # 5. 清理重复和陈旧规则
        if params.include_stale:
            dups, stale = await self._cleanup_skill_dna(params.skill_type)
            result.duplicates_removed = dups
            result.stale_rules_removed = stale

        # 6. 生成摘要
        result.summary = (
            f"Skill {params.skill_type} 提炼完成: 分析{result.experiences_analyzed}条经验, "
            f"检测到{result.patterns_detected}个模式, 生成{result.proposals_generated}个提案"
            f"(已应用{result.proposals_applied}/待审批{result.proposals_pending}), "
            f"清理重复{result.duplicates_removed}/陈旧{result.stale_rules_removed}条规则"
        )

        self._logger.info(f"Agent 主动提炼进化完成 skill={params.skill_type} "
                          f"experiences={result.experiences_analyzed} "
                          f"proposals={result.proposals_generated} "
                          f"applied={result.proposals_applied}")
        return result

    async def _apply_distill_proposal(self, skill_type: str, proposal: Dict) -> None:
        """应用提炼提案到 Skill DNA"""
        try:
            from agentflow.skill.evolver import SkillEvolver
            from agentflow.skill.store import SkillStore
            import agentflow.config as _cfg
            skill_store = SkillStore(self._redis, _cfg.SkillConfig(), self._logger)
            evolver = SkillEvolver(skill_store, self._redis, _cfg.SkillConfig(), self._logger)
            await evolver.apply_evolution(skill_type, {
                "new_rules": proposal.get("solutions", [])[:3],
                "new_anti_patterns": proposal.get("anti_patterns", [])[:3],
                "new_best_practices": proposal.get("best_practices", [])[:3],
            }, source="distill_and_evolve_advanced")
        except Exception as e:
            self._logger.warning(f"应用提炼提案失败 skill={skill_type} error={e}")

    async def _queue_proposal(self, evo_id: str, skill_type: str, proposal: Dict) -> None:
        """将高影响提案放入待审批队列"""
        pending_key = self._redis.key("evo", "pending", evo_id)
        await self._redis.hset(pending_key, {
            "evo_id": evo_id,
            "skill_type": skill_type,
            "evolution_type": "distill",
            "proposal": json.dumps(proposal),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "high_impact": str(proposal.get("impact", 0) >= 0.5),
        })
        # 加入 pending 列表
        pending_list_key = self._redis.key("evo", "pending")
        await self._redis.lpush(pending_list_key, evo_id)

    async def _cleanup_skill_dna(self, skill_type: str) -> Tuple[int, int]:
        """清理 Skill DNA 中的重复和陈旧规则，返回 (duplicates_removed, stale_removed)"""
        dups_removed = 0
        stale_removed = 0
        dna_key = self._redis.key("skill", skill_type, "dna")
        try:
            for field_name in ("rules", "anti_patterns", "best_practices"):
                field_json = await self._redis.hget(dna_key, field_name)
                if not field_json:
                    continue
                items: List[str] = json.loads(field_json)
                deduped = self._dedup_list(items)
                removed = len(items) - len(deduped)
                if removed > 0:
                    await self._redis.hset(dna_key, {field_name: json.dumps(deduped)})
                    dups_removed += removed
        except Exception as e:
            self._logger.warning(f"清理 Skill DNA 失败 skill={skill_type} error={e}")
        return dups_removed, stale_removed

    @staticmethod
    def _dedup_list(items: List[str]) -> List[str]:
        """去重列表（保持顺序）"""
        seen: Dict[str, bool] = {}
        result: List[str] = []
        for item in items:
            normalized = item.strip().lower()
            if normalized not in seen:
                seen[normalized] = True
                result.append(item)
        return result