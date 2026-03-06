from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class EvidenceItem:
    rule: str = ""
    source: str = ""
    confidence: float = 1.0
    evidence_count: int = 1

    def to_dict(self):
        return {
            "rule": self.rule,
            "source": self.source,
            "confidence": self.confidence,
            "evidence_count": self.evidence_count,
        }


@dataclass
class SkillDNA:
    skill_type: str = ""
    rules: List[str] = field(default_factory=list)
    templates: List[str] = field(default_factory=list)
    checklist: List[str] = field(default_factory=list)
    anti_patterns: List[str] = field(default_factory=list)
    best_practices: List[str] = field(default_factory=list)
    context_hints: List[str] = field(default_factory=list)
    evidence_chain: List[EvidenceItem] = field(default_factory=list)
    version: int = 1

    def to_dict(self):
        return {
            "skill_type": self.skill_type,
            "rules": self.rules,
            "templates": self.templates,
            "checklist": self.checklist,
            "anti_patterns": self.anti_patterns,
            "best_practices": self.best_practices,
            "context_hints": self.context_hints,
            "evidence_chain": [e.to_dict() for e in self.evidence_chain],
            "version": self.version,
        }


@dataclass
class SkillMetrics:
    skill_type: str = ""
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    avg_tokens: float = 0.0
    success_rate: float = 0.0
    canary_active: bool = False
    canary_ratio: float = 0.0
    canary_success_rate: float = 0.0
    last_evolved: str = ""

    def to_dict(self):
        return {
            "skill_type": self.skill_type,
            "total_tasks": self.total_tasks,
            "completed_tasks": self.completed_tasks,
            "failed_tasks": self.failed_tasks,
            "avg_tokens": self.avg_tokens,
            "success_rate": self.success_rate,
            "canary_active": self.canary_active,
            "canary_ratio": self.canary_ratio,
            "canary_success_rate": self.canary_success_rate,
            "last_evolved": self.last_evolved,
        }


@dataclass
class Skill:
    skill_type: str = ""
    name: str = ""
    description: str = ""
    dna: Optional[SkillDNA] = None
    metrics: Optional[SkillMetrics] = None
    version: int = 1
    updated_at: str = ""

    def to_dict(self):
        return {
            "skill_type": self.skill_type,
            "name": self.name,
            "description": self.description,
            "dna": self.dna.to_dict() if self.dna else None,
            "metrics": self.metrics.to_dict() if self.metrics else None,
            "version": self.version,
            "updated_at": self.updated_at,
        }
