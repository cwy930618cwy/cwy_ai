"""FixExp Embedding: 向量嵌入客户端，支持 disabled/openai/ollama 三种 provider。"""
import asyncio
import hashlib
import json
import logging
import math
from typing import List, Optional

import aiohttp

from agentflow.config import SemanticSearchConfig
from agentflow.storage import RedisClient


class EmbeddingClient:
    """向量嵌入客户端（支持 openai/ollama/disabled）。

    当 provider=disabled 或配置不完整时，is_available() 返回 False，
    embed() 返回 None，调用方应降级到关键词匹配。
    """

    def __init__(self, cfg: SemanticSearchConfig, redis: RedisClient, logger: logging.Logger):
        self._cfg = cfg
        self._redis = redis
        self._logger = logger
        self._available = self._check_available()
        if self._available:
            self._logger.info(
                f"语义搜索已启用 provider={cfg.provider} model={cfg.model} dim={cfg.dimension}"
            )
        else:
            self._logger.info("语义搜索已禁用，使用关键词匹配模式")

    def _check_available(self) -> bool:
        cfg = self._cfg
        if not cfg.enabled or cfg.provider == "disabled":
            return False
        if cfg.provider == "openai" and not cfg.api_key:
            self._logger.warning("OpenAI provider 未配置 api_key，语义搜索降级为关键词匹配")
            return False
        return True

    def is_available(self) -> bool:
        """检查客户端是否可用。"""
        return self._available

    @property
    def dimension(self) -> int:
        return self._cfg.dimension if self._cfg.dimension > 0 else 1536

    async def embed(self, text: str) -> Optional[List[float]]:
        """将文本转换为向量，失败时返回 None（调用方应降级）。"""
        if not self._available or not text:
            return None

        # 截断过长文本
        if len(text) > 8000:
            text = text[:8000]

        # 尝试从缓存获取
        cache_key = self._cache_key(text)
        cached = await self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        # 调用 API
        try:
            vec = await self._call_api(text)
        except Exception as e:
            self._logger.warning(f"调用 Embedding API 失败: {e}")
            return None

        # 异步写入缓存（后台任务，不影响主流程）
        async def _safe_set_cache():
            try:
                await self._set_to_cache(cache_key, vec)
            except Exception as e:
                self._logger.warning(f"异步写入 Embedding 缓存失败: {e}")
        asyncio.create_task(_safe_set_cache())
        return vec

    async def _call_api(self, text: str) -> List[float]:
        timeout = aiohttp.ClientTimeout(total=self._cfg.timeout or 10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            if self._cfg.provider == "ollama":
                return await self._call_ollama(session, text)
            else:
                return await self._call_openai(session, text)

    async def _call_openai(self, session: aiohttp.ClientSession, text: str) -> List[float]:
        base_url = self._cfg.base_url.rstrip("/")
        url = f"{base_url}/v1/embeddings"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._cfg.api_key}",
        }
        payload = {"input": text, "model": self._cfg.model, "encoding_format": "float"}
        async with session.post(url, headers=headers, json=payload) as resp:
            body = await resp.json()
            if resp.status != 200:
                raise RuntimeError(f"OpenAI API 返回 {resp.status}: {body}")
            if "error" in body:
                err = body["error"]
                raise RuntimeError(f"OpenAI API 错误 [{err.get('type')}]: {err.get('message')}")
            data = body.get("data", [])
            if not data or not data[0].get("embedding"):
                raise RuntimeError("OpenAI API 返回空向量")
            return data[0]["embedding"]

    async def _call_ollama(self, session: aiohttp.ClientSession, text: str) -> List[float]:
        base_url = self._cfg.base_url.rstrip("/")
        url = f"{base_url}/api/embeddings"
        payload = {"model": self._cfg.model, "prompt": text}
        async with session.post(url, json=payload) as resp:
            body = await resp.json()
            if resp.status != 200:
                raise RuntimeError(f"Ollama API 返回 {resp.status}: {body}")
            vec = body.get("embedding", [])
            if not vec:
                raise RuntimeError("Ollama API 返回空向量")
            return vec

    def _cache_key(self, text: str) -> str:
        digest = hashlib.sha256(text.encode()).hexdigest()[:16]
        return self._redis.key("embed", "cache", digest)

    async def _get_from_cache(self, key: str) -> Optional[List[float]]:
        try:
            data = await self._redis.get(key)
            if data:
                return json.loads(data)
        except Exception:
            pass
        return None

    async def _set_to_cache(self, key: str, vec: List[float]) -> None:
        try:
            ttl = self._cfg.cache_ttl if self._cfg.cache_ttl > 0 else 86400
            await self._redis.set(key, json.dumps(vec), ex=ttl)
        except Exception as e:
            self._logger.warning(f"写入 Embedding 缓存失败: {e}")


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """计算两个向量的余弦相似度，返回值范围 [-1, 1]。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
