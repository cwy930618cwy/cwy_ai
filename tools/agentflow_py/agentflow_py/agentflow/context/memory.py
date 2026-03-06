"""Memory manager: decay-based forgetting with relevance scoring."""
import asyncio
import json
import logging
import time
from typing import Dict, List, Optional

from agentflow.storage import RedisClient


class MemoryManager:
    DECAY_FACTOR = 0.95
    CAPACITY = 200
    DECAY_INTERVAL = 600  # 10 minutes
    FORGET_THRESHOLD = 0.1

    def __init__(self, redis: RedisClient, logger: logging.Logger):
        self._redis = redis
        self._logger = logger
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._decay_loop())
        self._logger.info("MemoryManager 已启动")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _decay_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self.DECAY_INTERVAL)
            try:
                await self._run_decay_cycle()
            except Exception as e:
                self._logger.error(f"MemoryManager 衰减异常: {e}")

    async def _run_decay_cycle(self) -> None:
        relevance_key = self._redis.key("memory", "relevance_weights")
        members = await self._redis.zrange_withscores(relevance_key, 0, -1)
        to_delete = []
        updates: Dict[str, float] = {}
        for mem_id, score in members:
            new_score = score * self.DECAY_FACTOR
            if new_score < self.FORGET_THRESHOLD:
                to_delete.append(mem_id)
            else:
                updates[mem_id] = new_score

        for mem_id in to_delete:
            await self._redis.zrem(relevance_key, mem_id)
            await self._redis.hdel(self._redis.key("memory", "summaries"), mem_id)

        if updates:
            await self._redis.zadd(relevance_key, updates)

        # Capacity capping
        total = await self._redis.zcard(relevance_key)
        if total > self.CAPACITY:
            lowest = await self._redis.zrange_withscores(relevance_key, 0, total - self.CAPACITY - 1)
            for mem_id, _ in lowest:
                await self._redis.zrem(relevance_key, mem_id)
                await self._redis.hdel(self._redis.key("memory", "summaries"), mem_id)

    async def record_access(self, memory_id: str) -> None:
        relevance_key = self._redis.key("memory", "relevance_weights")
        current = await self._redis.zscore(relevance_key, memory_id)
        boost = 0.3
        new_score = min(1.0, (current or 0.0) + boost)
        await self._redis.zadd(relevance_key, {memory_id: new_score})

    async def store_summary(self, memory_id: str, summary: str, skill_type: str = "") -> None:
        summaries_key = self._redis.key("memory", "summaries")
        await self._redis.hset(summaries_key, {memory_id: json.dumps({
            "summary": summary,
            "skill_type": skill_type,
            "stored_at": str(time.time()),
        })})
        await self._redis.zadd(self._redis.key("memory", "relevance_weights"), {memory_id: 1.0})

    async def get_relevant_memories(self, skill_type: str = "", limit: int = 5) -> List[Dict]:
        relevance_key = self._redis.key("memory", "relevance_weights")
        summaries_key = self._redis.key("memory", "summaries")
        top_ids = await self._redis.zrevrange_withscores(relevance_key, 0, limit * 2 - 1)
        results = []
        for mem_id, score in top_ids:
            raw = await self._redis.hget(summaries_key, mem_id)
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            if skill_type and data.get("skill_type") != skill_type:
                continue
            results.append({"id": mem_id, "score": score, **data})
            if len(results) >= limit:
                break
        return results

    async def get_stats(self) -> Dict:
        relevance_key = self._redis.key("memory", "relevance_weights")
        total = await self._redis.zcard(relevance_key)
        return {"total_memories": total, "capacity": self.CAPACITY, "decay_factor": self.DECAY_FACTOR}
