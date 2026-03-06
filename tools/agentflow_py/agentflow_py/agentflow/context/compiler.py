"""8-layer context compiler with elastic token budget."""
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from agentflow.config import CompileConfig
from agentflow.storage import RedisClient, SQLiteStore
from .metrics import MetricsStore, CompilationStats, LayerStat


class ContextCompiler:
    def __init__(self, redis: RedisClient, sqlite: Optional[SQLiteStore],
                 cfg: CompileConfig, logger: logging.Logger):
        self._redis = redis
        self._sqlite = sqlite
        self._cfg = cfg
        self._logger = logger
        self._metrics_store = MetricsStore(sqlite) if sqlite else None

    async def compile_for_claim(self, task_id: str, budget: int = 0) -> Tuple[str, int]:
        """Compile context for claim_task. Returns (text, token_count)."""
        if budget <= 0:
            budget = self._cfg.default_budget
        result = await self.compile(task_id, budget=budget, detail_level="standard")
        return result.get("context", ""), result.get("total_tokens", 0)

    async def compile(self, task_id: str, budget: int = 0,
                      detail_level: str = "standard") -> Dict[str, Any]:
        if budget <= 0:
            budget = self._cfg.default_budget

        # Get task data
        task_data = await self._redis.hgetall(self._redis.key("task", task_id))
        if not task_data:
            return {"context": "", "total_tokens": 0}

        skill_type = task_data.get("skill_type", "")
        deps_json = task_data.get("dependencies", "[]")
        try:
            deps = json.loads(deps_json)
        except Exception:
            deps = []

        # Adjust budget elastically
        budget = self._evaluate_budget(len(deps), skill_type, budget)

        sections = []
        used_tokens = 0
        layer_stats: List[LayerStat] = []  # 记录每层编译指标

        # L1: Global rules
        l1 = await self._compile_global_rules(skill_type, budget - used_tokens)
        l1_tokens = self._estimate_tokens(l1) if l1 else 0
        layer_stats.append(LayerStat(name="global_rules", hit=bool(l1), truncated=l1.endswith("...(截断)") if l1 else False, tokens=l1_tokens))
        if l1:
            sections.append(f"## 全局规则\n{l1}")
            used_tokens += l1_tokens

        # L2: Project config (skip if minimal)
        if detail_level != "minimal" and used_tokens < budget:
            l2 = await self._compile_project_config(budget - used_tokens)
            l2_tokens = self._estimate_tokens(l2) if l2 else 0
            layer_stats.append(LayerStat(name="project_config", hit=bool(l2), truncated=l2.endswith("...(截断)") if l2 else False, tokens=l2_tokens))
            if l2:
                sections.append(f"## 项目配置\n{l2}")
                used_tokens += l2_tokens
        else:
            layer_stats.append(LayerStat(name="project_config", hit=False, skipped=True, tokens=0))

        # L3: Task description
        if used_tokens < budget:
            l3 = self._compile_task_description(task_data, budget - used_tokens)
            l3_tokens = self._estimate_tokens(l3) if l3 else 0
            layer_stats.append(LayerStat(name="task_description", hit=bool(l3), truncated=l3.endswith("...(截断)") if l3 else False, tokens=l3_tokens))
            if l3:
                sections.append(f"## 当前任务\n{l3}")
                used_tokens += l3_tokens
        else:
            layer_stats.append(LayerStat(name="task_description", hit=False, skipped=True, tokens=0))

        # L4: Skill DNA
        if used_tokens < budget:
            l4 = await self._compile_skill_dna(skill_type, budget - used_tokens)
            l4_tokens = self._estimate_tokens(l4) if l4 else 0
            layer_stats.append(LayerStat(name="skill_dna", hit=bool(l4), truncated=l4.endswith("...(截断)") if l4 else False, tokens=l4_tokens))
            if l4:
                sections.append(f"## Skill DNA ({skill_type})\n{l4}")
                used_tokens += l4_tokens
        else:
            layer_stats.append(LayerStat(name="skill_dna", hit=False, skipped=True, tokens=0))

        # L5: Dependency summaries
        if detail_level != "minimal" and deps and used_tokens < budget:
            l5 = await self._compile_dependencies(deps, budget - used_tokens)
            l5_tokens = self._estimate_tokens(l5) if l5 else 0
            layer_stats.append(LayerStat(name="dependencies", hit=bool(l5), truncated=l5.endswith("...(截断)") if l5 else False, tokens=l5_tokens))
            if l5:
                sections.append(f"## 前置依赖摘要\n{l5}")
                used_tokens += l5_tokens
        else:
            layer_stats.append(LayerStat(name="dependencies", hit=False, skipped=True, tokens=0))

        # L6: Experiences
        if detail_level != "minimal" and used_tokens < budget:
            l6 = await self._compile_experiences(skill_type, budget - used_tokens)
            l6_tokens = self._estimate_tokens(l6) if l6 else 0
            layer_stats.append(LayerStat(name="experiences", hit=bool(l6), truncated=l6.endswith("...(截断)") if l6 else False, tokens=l6_tokens))
            if l6:
                sections.append(f"## 相关经验\n{l6}")
                used_tokens += l6_tokens
        else:
            layer_stats.append(LayerStat(name="experiences", hit=False, skipped=True, tokens=0))

        # L7: Evolution log (full only)
        if detail_level == "full" and used_tokens < budget:
            l7 = await self._compile_evolution_log(skill_type, budget - used_tokens)
            l7_tokens = self._estimate_tokens(l7) if l7 else 0
            layer_stats.append(LayerStat(name="evolution_log", hit=bool(l7), truncated=l7.endswith("...(截断)") if l7 else False, tokens=l7_tokens))
            if l7:
                sections.append(f"## 进化日志\n{l7}")
                used_tokens += l7_tokens
        else:
            layer_stats.append(LayerStat(name="evolution_log", hit=False, skipped=True, tokens=0))

        # L8: Recovery context (if interrupted)
        status = task_data.get("status", "")
        if status == "interrupted" and used_tokens < budget:
            l8 = await self._compile_recovery_context(task_id, budget - used_tokens)
            l8_tokens = self._estimate_tokens(l8) if l8 else 0
            layer_stats.append(LayerStat(name="recovery_context", hit=bool(l8), truncated=l8.endswith("...(截断)") if l8 else False, tokens=l8_tokens))
            if l8:
                sections.append(f"## 恢复上下文\n{l8}")
                used_tokens += l8_tokens
        else:
            layer_stats.append(LayerStat(name="recovery_context", hit=False, skipped=True, tokens=0))

        context = "\n\n".join(sections)

        # 使用 MetricsStore 记录完整层级指标（替代原来的 save_compilation_metrics）
        if self._metrics_store:
            try:
                stats = CompilationStats(
                    task_id=task_id,
                    skill_type=skill_type,
                    detail_level=detail_level,
                    budget=budget,
                    total_tokens=used_tokens,
                    layers=layer_stats,
                )
                stats.compute_stats()  # 计算 hit_rate/truncate_rate 等汇总指标
                self._metrics_store.save(stats)
            except Exception as e:
                self._logger.warning(f"保存编译指标失败 task_id={task_id} err={e}")

        return {
            "context": context,
            "total_tokens": used_tokens,
            "budget": budget,
            "layers_compiled": len(sections),
        }

    def _evaluate_budget(self, dep_count: int, skill_type: str, base: int) -> int:
        # Get skill DNA rule count
        adjusted = base + dep_count * 200
        adjusted = max(self._cfg.min_budget, min(self._cfg.max_budget, adjusted))
        return adjusted

    async def _compile_global_rules(self, skill_type: str, remaining: int) -> str:
        rules = await self._redis.lrange(self._redis.key("ctx", "global_rules"), 0, -1)
        if not rules:
            return ""
        result = "\n".join(f"- {r}" for r in rules[:10])
        return self._truncate_to_tokens(result, remaining)

    async def _compile_project_config(self, remaining: int) -> str:
        data = await self._redis.hgetall(self._redis.key("ctx", "project_config"))
        if not data:
            return ""
        lines = [f"{k}: {v}" for k, v in list(data.items())[:5]]
        return self._truncate_to_tokens("\n".join(lines), remaining)

    def _compile_task_description(self, task_data: Dict, remaining: int) -> str:
        parts = [
            f"**标题**: {task_data.get('title', '')}",
            f"**描述**: {task_data.get('description', '')}",
        ]
        if prereqs := task_data.get("prerequisites"):
            try:
                pl = json.loads(prereqs)
                if pl:
                    parts.append("**前提条件**:\n" + "\n".join(f"- {p}" for p in pl))
            except Exception:
                pass
        return self._truncate_to_tokens("\n".join(parts), remaining)

    async def _compile_skill_dna(self, skill_type: str, remaining: int) -> str:
        if not skill_type:
            return ""
        dna = await self._redis.hgetall(self._redis.key("skill", skill_type, "dna"))
        if not dna:
            return ""
        parts = []
        used_rules: list = []
        if rules_str := dna.get("rules"):
            try:
                rules = json.loads(rules_str)
                if rules:
                    parts.append("**规则**:\n" + "\n".join(f"- {r}" for r in rules[:10]))
                    used_rules = rules[:10]
            except Exception:
                pass
        if anti := dna.get("anti_patterns"):
            try:
                al = json.loads(anti)
                if al:
                    parts.append("**反模式**:\n" + "\n".join(f"- {a}" for a in al[:5]))
            except Exception:
                pass
        if bp := dna.get("best_practices"):
            try:
                bpl = json.loads(bp)
                if bpl:
                    parts.append("**最佳实践**:\n" + "\n".join(f"- {b}" for b in bpl[:5]))
            except Exception:
                pass
        result = self._truncate_to_tokens("\n\n".join(parts), remaining) if parts else ""

        # 异步更新 Skill 使用统计（usage_count + last_used + 规则引用序号）
        if result:
            import asyncio
            from datetime import datetime, timezone
            async def _update_metrics():
                try:
                    metrics_key = self._redis.key("skill", skill_type, "metrics")
                    new_seq = await self._redis.hincr_by(metrics_key, "usage_count", 1)
                    await self._redis.hset(metrics_key, {
                        "last_used": datetime.now(timezone.utc).isoformat()
                    })
                    # 记录规则引用序号（供陈旧规则检测使用）
                    if used_rules:
                        usage_key = self._redis.key("skill", skill_type, "rule_usage")
                        rule_map = {r[:50]: str(new_seq) for r in used_rules}
                        await self._redis.hset(usage_key, rule_map)
                except Exception as e:
                    self._logger.warning(f"更新 Skill usage_count 失败 skill={skill_type} err={e}")
            asyncio.ensure_future(_update_metrics())

        return result

    async def _compile_dependencies(self, deps: List[str], remaining: int) -> str:
        parts = []
        for dep_id in deps[:5]:
            data = await self._redis.hgetall(self._redis.key("task", dep_id))
            if not data:
                continue
            summary = data.get("summary", "")
            title = data.get("title", dep_id)
            status = data.get("status", "")
            parts.append(f"- **{title}** ({status}): {summary[:100]}")
        return self._truncate_to_tokens("\n".join(parts), remaining) if parts else ""

    async def _compile_experiences(self, skill_type: str, remaining: int) -> str:
        parts = []
        for stream_key in (self._redis.key("exp", "positive"), self._redis.key("exp", "negative")):
            msgs = await self._redis.xrevrange(stream_key, count=5)
            for msg in msgs:
                fields = msg.get("fields", {})
                if skill_type and fields.get("skill_type") != skill_type:
                    continue
                desc = fields.get("description", "")
                exp_type = "✅" if "positive" in stream_key else "❌"
                category = fields.get("category", "")
                if desc:
                    parts.append(f"{exp_type} [{category}] {desc[:100]}")
        return self._truncate_to_tokens("\n".join(parts[:8]), remaining) if parts else ""

    async def _compile_evolution_log(self, skill_type: str, remaining: int) -> str:
        msgs = await self._redis.xrevrange(self._redis.key("evo", "log"), count=3)
        parts = []
        for msg in msgs:
            fields = msg.get("fields", {})
            if skill_type and fields.get("target") != skill_type:
                continue
            desc = fields.get("description", "")
            if desc:
                parts.append(f"- {desc[:80]}")
        return self._truncate_to_tokens("\n".join(parts), remaining) if parts else ""

    async def _compile_recovery_context(self, task_id: str, remaining: int) -> str:
        cp_key = self._redis.key("task", task_id, "checkpoint")
        val = await self._redis.get(cp_key)
        if not val:
            return ""
        try:
            cp = json.loads(val)
            parts = [f"**恢复时间**: {cp.get('saved_at', '')}"]
            if completed := cp.get("completed_items"):
                parts.append("**已完成**:\n" + "\n".join(f"- {i}" for i in completed[:5]))
            if pending := cp.get("pending_items"):
                parts.append("**待完成**:\n" + "\n".join(f"- {i}" for i in pending[:5]))
            if files := cp.get("modified_files"):
                parts.append("**已修改文件**:\n" + "\n".join(f"- {f}" for f in files[:10]))
            if notes := cp.get("notes"):
                parts.append(f"**备注**: {notes}")
            return self._truncate_to_tokens("\n\n".join(parts), remaining)
        except Exception:
            return ""

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(1, len(text) // 4)

    def _truncate_to_tokens(self, text: str, max_tokens: int) -> str:
        max_chars = max_tokens * 4
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "...(截断)"
