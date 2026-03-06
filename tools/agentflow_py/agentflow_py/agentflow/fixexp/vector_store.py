"""FixExp VectorStore: 基于 Redis Hash 的经验向量存储。

key 格式: fixexp:vec:{exp_id}
field: vector -> JSON 序列化的 float 列表
       source_type -> fix_session / experience_stream
       created_at -> ISO8601 时间戳

相似度搜索使用全表扫描 + 余弦相似度（适用于经验数 < 10000 的场景）。
"""
import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

from agentflow.storage import RedisClient
from .embedding import cosine_similarity


class VectorSearchResult:
    """向量搜索结果。"""

    def __init__(self, source_id: str, source_type: str, similarity: float):
        self.source_id = source_id
        self.source_type = source_type
        self.similarity = similarity

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "similarity": round(self.similarity, 4),
        }


class VectorStore:
    """经验向量存储（Redis Hash 实现）。

    每条经验的向量以 Hash 形式存储在 Redis 中：
        key: fixexp:vec:{source_id}
        fields: vector, source_type, created_at
    """

    # 最小相似度阈值，低于此值的结果被过滤
    MIN_SIMILARITY = 0.3

    def __init__(self, redis: RedisClient, logger: logging.Logger):
        self._redis = redis
        self._logger = logger

    def _vec_key(self, source_id: str) -> str:
        return self._redis.key("fixexp", "vec", source_id)

    def _index_key(self) -> str:
        """所有向量 source_id 的集合 key。"""
        return self._redis.key("fixexp", "vec", "_index")

    async def upsert(self, source_id: str, source_type: str, vector: List[float]) -> None:
        """插入或更新经验向量。"""
        if not source_id:
            raise ValueError("source_id 不能为空")
        if not vector:
            raise ValueError("向量不能为空")

        key = self._vec_key(source_id)
        now = datetime.now(timezone.utc).isoformat()
        await self._redis.hset(key, {
            "source_id": source_id,
            "source_type": source_type,
            "vector": json.dumps(vector),
            "created_at": now,
        })
        # 维护索引集合
        await self._redis.sadd(self._index_key(), source_id)
        self._logger.debug(f"向量已存储 source_id={source_id} source_type={source_type}")

    async def delete(self, source_id: str) -> None:
        """删除向量。"""
        key = self._vec_key(source_id)
        await self._redis.delete(key)
        await self._redis.srem(self._index_key(), source_id)

    async def search_top_k(
        self,
        query_vec: List[float],
        k: int = 10,
        source_type: Optional[str] = None,
    ) -> List[VectorSearchResult]:
        """全表扫描余弦相似度，返回 Top-K 结果。

        Args:
            query_vec: 查询向量
            k: 返回结果数量
            source_type: 可选，按来源类型过滤
        """
        if not query_vec:
            return []
        if k <= 0:
            k = 10

        # 获取所有 source_id
        source_ids = await self._redis.smembers(self._index_key())
        if not source_ids:
            return []

        candidates = []
        for sid in source_ids:
            key = self._vec_key(sid)
            data = await self._redis.hgetall(key)
            if not data:
                # 索引中有但数据已过期，清理索引
                await self._redis.srem(self._index_key(), sid)
                continue

            # 按 source_type 过滤
            if source_type and data.get("source_type") != source_type:
                continue

            try:
                vec = json.loads(data["vector"])
            except Exception:
                self._logger.warning(f"反序列化向量失败 source_id={sid}")
                continue

            sim = cosine_similarity(query_vec, vec)
            if sim > self.MIN_SIMILARITY:
                candidates.append(VectorSearchResult(
                    source_id=data.get("source_id", sid),
                    source_type=data.get("source_type", ""),
                    similarity=sim,
                ))

        # 按相似度降序排序，取 Top-K
        candidates.sort(key=lambda x: x.similarity, reverse=True)
        return candidates[:k]

    async def count(self) -> int:
        """返回已存储向量总数。"""
        members = await self._redis.smembers(self._index_key())
        return len(members)
