"""Skill evolver: canary deployment and cross-skill rule promotion."""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from agentflow.config import SkillConfig
from agentflow.storage import RedisClient
from .model import SkillDNA, EvidenceItem
from .store import SkillStore


class SkillEvolver:
    def __init__(self, store: SkillStore, redis: RedisClient, cfg: SkillConfig, logger: logging.Logger):
        self._store = store
        self._redis = redis
        self._cfg = cfg
        self._logger = logger

    async def apply_evolution(self, skill_type: str, changes: Dict,
                               source: str = "evolution") -> Optional[SkillDNA]:
        """Apply proposed changes to skill DNA."""
        dna = await self._store.get_dna(skill_type)
        if not dna:
            # Create new skill DNA from scratch
            dna = SkillDNA(skill_type=skill_type)

        limits = self._cfg.limits

        # Apply rules
        if new_rules := changes.get("new_rules", []):
            for rule in new_rules:
                if rule not in dna.rules:
                    dna.rules.append(rule)
                    # Add evidence chain entry
                    dna.evidence_chain.append(EvidenceItem(
                        rule=rule, source=source, confidence=0.8, evidence_count=1
                    ))
            if len(dna.rules) > limits.max_rules:
                dna.rules = dna.rules[-limits.max_rules:]

        # Apply anti_patterns
        if new_anti := changes.get("new_anti_patterns", []):
            for ap in new_anti:
                if ap not in dna.anti_patterns:
                    dna.anti_patterns.append(ap)
            if len(dna.anti_patterns) > limits.max_anti_patterns:
                dna.anti_patterns = dna.anti_patterns[-limits.max_anti_patterns:]

        # Apply best_practices
        if new_bp := changes.get("new_best_practices", []):
            for bp in new_bp:
                if bp not in dna.best_practices:
                    dna.best_practices.append(bp)
            if len(dna.best_practices) > limits.max_best_practices:
                dna.best_practices = dna.best_practices[-limits.max_best_practices:]

        # Remove stale rules
        if remove_rules := changes.get("remove_rules", []):
            dna.rules = [r for r in dna.rules if r not in remove_rules]
            dna.evidence_chain = [e for e in dna.evidence_chain if e.rule not in remove_rules]

        dna.version += 1
        await self._store.save_dna(dna)

        # Update last_evolved metric
        now = datetime.now(timezone.utc).isoformat()
        meta_key = self._redis.key("skill", skill_type, "meta")
        await self._redis.hset(meta_key, {"updated_at": now, "version": str(dna.version)})
        metrics_key = self._redis.key("skill", skill_type, "metrics")
        await self._redis.hset(metrics_key, {"last_evolved": now})

        self._logger.info(f"Skill DNA 已进化 skill_type={skill_type} version={dna.version}")
        return dna

    async def promote_cross_skill(self, rule: str, source_skill: str,
                                   target_skills: Optional[List[str]] = None) -> List[str]:
        """Promote a rule from one skill to other skills."""
        if not target_skills:
            all_skills = await self._redis.smembers(self._redis.key("skill", "types"))
            target_skills = [s for s in all_skills if s != source_skill]

        promoted_to = []
        for skill_type in target_skills:
            dna = await self._store.get_dna(skill_type)
            if not dna:
                continue
            if rule not in dna.rules:
                dna.rules.append(f"[from {source_skill}] {rule}")
                dna.evidence_chain.append(EvidenceItem(
                    rule=rule,
                    source=f"cross_skill_from_{source_skill}",
                    confidence=0.6,
                    evidence_count=1,
                ))
                dna.version += 1
                await self._store.save_dna(dna)
                promoted_to.append(skill_type)

        self._logger.info(f"跨Skill规则推广 rule={rule[:50]} promoted_to={promoted_to}")
        return promoted_to

    async def start_canary(self, skill_type: str, candidate_changes: Dict,
                            ratio: float = 0.2) -> None:
        """Start a canary deployment of skill DNA changes."""
        canary_key = self._redis.key("skill", skill_type, "canary")
        import json
        await self._redis.set(canary_key, json.dumps({
            "changes": candidate_changes,
            "ratio": ratio,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "total_uses": 0,
            "success_count": 0,
        }))
        self._logger.info(f"Canary部署启动 skill_type={skill_type} ratio={ratio}")

    async def record_canary_result(self, skill_type: str, success: bool) -> Optional[str]:
        """Record canary result, return 'promote'/'rollback'/None."""
        import json
        canary_key = self._redis.key("skill", skill_type, "canary")
        val = await self._redis.get(canary_key)
        if not val:
            return None
        data = json.loads(val)
        data["total_uses"] += 1
        if success:
            data["success_count"] += 1
        await self._redis.set(canary_key, json.dumps(data))

        cfg = self._cfg.canary
        if not cfg.enabled:
            return None
        if data["total_uses"] < cfg.min_samples:
            return None

        rate = data["success_count"] / data["total_uses"]
        if rate >= cfg.promote_threshold:
            await self.apply_evolution(skill_type, data["changes"], "canary_promote")
            await self._redis.delete(canary_key)
            return "promote"
        elif rate < cfg.rollback_threshold:
            await self._redis.delete(canary_key)
            return "rollback"
        return None
