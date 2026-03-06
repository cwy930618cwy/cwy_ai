import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from agentflow.common import NotFoundError
from agentflow.config import SkillConfig
from agentflow.storage import RedisClient
from .model import Skill, SkillDNA, SkillMetrics, EvidenceItem


class SkillStore:
    def __init__(self, redis: RedisClient, cfg: SkillConfig, logger: logging.Logger):
        self._redis = redis
        self._cfg = cfg
        self._logger = logger

    async def save_dna(self, dna: SkillDNA) -> None:
        key = self._redis.key("skill", dna.skill_type, "dna")
        await self._redis.hset(key, {
            "skill_type": dna.skill_type,
            "rules": json.dumps(dna.rules),
            "templates": json.dumps(dna.templates),
            "checklist": json.dumps(dna.checklist),
            "anti_patterns": json.dumps(dna.anti_patterns),
            "best_practices": json.dumps(dna.best_practices),
            "context_hints": json.dumps(dna.context_hints),
            "evidence_chain": json.dumps([e.to_dict() for e in dna.evidence_chain]),
            "version": str(dna.version),
        })
        await self._redis.sadd(self._redis.key("skill", "types"), dna.skill_type)

    async def get_dna(self, skill_type: str) -> Optional[SkillDNA]:
        key = self._redis.key("skill", skill_type, "dna")
        data = await self._redis.hgetall(key)
        if not data:
            return None
        return self._map_dna(data)

    async def get_skill(self, skill_type: str) -> Optional[Skill]:
        dna = await self.get_dna(skill_type)
        if not dna:
            return None
        metrics = await self.get_metrics(skill_type)
        meta_key = self._redis.key("skill", skill_type, "meta")
        meta = await self._redis.hgetall(meta_key)
        return Skill(
            skill_type=skill_type,
            name=meta.get("name", skill_type),
            description=meta.get("description", ""),
            dna=dna,
            metrics=metrics,
            version=int(meta.get("version", 1)),
            updated_at=meta.get("updated_at", ""),
        )

    async def list_skills(self) -> List[Skill]:
        skill_types = await self._redis.smembers(self._redis.key("skill", "types"))
        result = []
        for st in skill_types:
            skill = await self.get_skill(st)
            if skill:
                result.append(skill)
        return sorted(result, key=lambda s: s.skill_type)

    async def update_dna_fields(self, skill_type: str, updates: Dict) -> Optional[SkillDNA]:
        dna = await self.get_dna(skill_type)
        if not dna:
            return None
        for k, v in updates.items():
            if hasattr(dna, k):
                setattr(dna, k, v)
        dna.version += 1
        await self.save_dna(dna)
        now = datetime.now(timezone.utc).isoformat()
        meta_key = self._redis.key("skill", skill_type, "meta")
        await self._redis.hset(meta_key, {"updated_at": now, "version": str(dna.version)})
        return dna

    async def get_metrics(self, skill_type: str) -> Optional[SkillMetrics]:
        key = self._redis.key("skill", skill_type, "metrics")
        data = await self._redis.hgetall(key)
        if not data:
            return SkillMetrics(skill_type=skill_type)
        return SkillMetrics(
            skill_type=skill_type,
            total_tasks=int(data.get("total_tasks", 0)),
            completed_tasks=int(data.get("completed_tasks", 0)),
            failed_tasks=int(data.get("failed_tasks", 0)),
            avg_tokens=float(data.get("avg_tokens", 0.0)),
            success_rate=float(data.get("success_rate", 0.0)),
            canary_active=data.get("canary_active", "false") == "true",
            canary_ratio=float(data.get("canary_ratio", 0.0)),
            canary_success_rate=float(data.get("canary_success_rate", 0.0)),
            last_evolved=data.get("last_evolved", ""),
        )

    async def record_task_result(self, skill_type: str, success: bool, tokens: int) -> None:
        key = self._redis.key("skill", skill_type, "metrics")
        metrics = await self.get_metrics(skill_type) or SkillMetrics(skill_type=skill_type)
        metrics.total_tasks += 1
        if success:
            metrics.completed_tasks += 1
        else:
            metrics.failed_tasks += 1
        # Exponential moving average for tokens
        if metrics.total_tasks == 1:
            metrics.avg_tokens = float(tokens)
        else:
            metrics.avg_tokens = metrics.avg_tokens * 0.9 + tokens * 0.1
        if metrics.total_tasks > 0:
            metrics.success_rate = metrics.completed_tasks / metrics.total_tasks
        await self._redis.hset(key, {
            "total_tasks": str(metrics.total_tasks),
            "completed_tasks": str(metrics.completed_tasks),
            "failed_tasks": str(metrics.failed_tasks),
            "avg_tokens": f"{metrics.avg_tokens:.1f}",
            "success_rate": f"{metrics.success_rate:.3f}",
        })

    def _map_dna(self, data: Dict) -> SkillDNA:
        def parse_list(raw: str) -> List:
            if not raw:
                return []
            try:
                return json.loads(raw)
            except Exception:
                return []

        evidence = []
        for item in parse_list(data.get("evidence_chain", "[]")):
            evidence.append(EvidenceItem(**item) if isinstance(item, dict) else EvidenceItem(rule=str(item)))

        return SkillDNA(
            skill_type=data.get("skill_type", ""),
            rules=parse_list(data.get("rules", "[]")),
            templates=parse_list(data.get("templates", "[]")),
            checklist=parse_list(data.get("checklist", "[]")),
            anti_patterns=parse_list(data.get("anti_patterns", "[]")),
            best_practices=parse_list(data.get("best_practices", "[]")),
            context_hints=parse_list(data.get("context_hints", "[]")),
            evidence_chain=evidence,
            version=int(data.get("version", 1)),
        )
