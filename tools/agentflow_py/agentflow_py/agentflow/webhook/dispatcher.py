"""
Webhook 分发器

移植自 Go 工程 internal/webhook/dispatcher.go

功能:
- 异步分发事件到 Webhook 端点
- 支持 HMAC-SHA256 签名验证
- 支持指数退避重试
- 支持 Redis 持久化配置
"""

import asyncio
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from typing import List, Optional

import aiohttp

from .model import EventType, WebhookEvent, WebhookEndpoint


# 默认配置
DEFAULT_MAX_RETRIES = 3
DEFAULT_TIMEOUT = 10.0  # 秒
CONFIGS_HASH_KEY = "webhook:configs"  # Redis Hash key（不含前缀）


class Dispatcher:
    """Webhook 分发器"""

    def __init__(self, redis, logger: Optional[logging.Logger] = None):
        """
        初始化 Webhook 分发器
        
        Args:
            redis: Redis 客户端实例
            logger: 日志记录器
        """
        self._redis = redis
        self._logger = logger or logging.getLogger("agentflow.webhook")
        self._max_retries = DEFAULT_MAX_RETRIES
        self._timeout = aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 aiohttp session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    async def close(self) -> None:
        """关闭资源"""
        if self._session and not self._session.closed:
            await self._session.close()

    async def dispatch(self, event: WebhookEvent) -> None:
        """
        异步分发事件（不阻塞调用方）
        
        Args:
            event: 要分发的事件
        """
        # 创建异步任务，不阻塞调用方
        asyncio.create_task(self._dispatch_async(event))

    async def _dispatch_async(self, event: WebhookEvent) -> None:
        """异步分发实现"""
        try:
            endpoints = await self.load_endpoints()
            for ep in endpoints:
                if ep.should_receive(event.event_type):
                    await self._send_with_retry(ep, event)
        except Exception as e:
            self._logger.warning(f"Webhook: 分发事件失败 error={e}")

    async def _send_with_retry(self, ep: WebhookEndpoint, event: WebhookEvent) -> None:
        """
        带重试的发送（指数退避）
        
        Args:
            ep: Webhook 端点
            event: 事件
        """
        payload = json.dumps(event.to_dict(), ensure_ascii=False)
        payload_bytes = payload.encode("utf-8")

        for attempt in range(self._max_retries):
            if attempt > 0:
                # 指数退避：1s, 2s, 4s
                backoff = 1 << (attempt - 1)
                await asyncio.sleep(backoff)

            try:
                await self._send(ep, payload_bytes)
                self._logger.debug(
                    f"Webhook: 发送成功 url={ep.url} "
                    f"event={event.event_type.value} attempt={attempt + 1}"
                )
                return
            except Exception as e:
                self._logger.warning(
                    f"Webhook: 发送失败，准备重试 url={ep.url} "
                    f"event={event.event_type.value} attempt={attempt + 1} error={e}"
                )

        self._logger.error(
            f"Webhook: 发送最终失败 url={ep.url} "
            f"event={event.event_type.value} max_retries={self._max_retries}"
        )

    async def _send(self, ep: WebhookEndpoint, payload: bytes) -> None:
        """
        发送单次 HTTP POST 请求
        
        Args:
            ep: Webhook 端点
            payload: 请求体（JSON 字节）
            
        Raises:
            Exception: 发送失败时抛出异常
        """
        session = await self._get_session()
        
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "AgentFlow-Webhook/1.0",
            "X-AgentFlow-Event": event.event_type.value,
            "X-AgentFlow-Delivery": ep.id,
        }

        # HMAC 签名（如果配置了 secret）
        if ep.secret:
            mac = hmac.new(
                ep.secret.encode("utf-8"),
                payload,
                hashlib.sha256
            )
            sig = mac.hexdigest()
            headers["X-AgentFlow-Signature"] = f"sha256={sig}"

        async with session.post(ep.url, data=payload, headers=headers) as resp:
            if resp.status < 200 or resp.status >= 300:
                raise Exception(f"HTTP 响应状态码异常: {resp.status}")

    async def load_endpoints(self) -> List[WebhookEndpoint]:
        """从 Redis 加载所有 Webhook 端点配置"""
        key = self._redis.key(CONFIGS_HASH_KEY)
        data = await self._redis.hgetall(key)
        
        endpoints = []
        for v in data.values():
            try:
                ep = WebhookEndpoint.from_dict(json.loads(v))
                endpoints.append(ep)
            except Exception as e:
                self._logger.warning(f"Webhook: 解析端点配置失败 error={e}")
                continue
        
        return endpoints

    async def add_endpoint(self, ep: WebhookEndpoint) -> None:
        """
        添加 Webhook 端点配置
        
        Args:
            ep: Webhook 端点
            
        Raises:
            ValueError: 参数无效时抛出
        """
        if not ep.url:
            raise ValueError("URL 不能为空")
        
        if not ep.id:
            ep.id = f"wh_{int(time.time() * 1000)}"
        
        ep.created_at = datetime.now().isoformat()
        ep.enabled = True

        data = json.dumps(ep.to_dict(), ensure_ascii=False)
        key = self._redis.key(CONFIGS_HASH_KEY)
        await self._redis.hset(key, {ep.id: data})
        
        self._logger.info(f"Webhook: 添加端点 id={ep.id} url={ep.url}")

    async def remove_endpoint(self, id: str) -> None:
        """
        删除 Webhook 端点配置
        
        Args:
            id: 端点 ID
        """
        key = self._redis.key(CONFIGS_HASH_KEY)
        await self._redis.hdel(key, id)
        self._logger.info(f"Webhook: 删除端点 id={id}")

    async def list_endpoints(self) -> List[WebhookEndpoint]:
        """列出所有 Webhook 端点配置"""
        return await self.load_endpoints()

    async def test_endpoint(self, url: str) -> None:
        """
        发送测试事件到指定 URL
        
        Args:
            url: 目标 URL
            
        Raises:
            Exception: 发送失败时抛出
        """
        test_event = WebhookEvent.new_event(
            EventType.TASK_COMPLETED,
            "test",
            {
                "message": "这是一条来自 AgentFlow 的测试 Webhook 事件",
                "test": True,
            }
        )
        payload = json.dumps(test_event.to_dict(), ensure_ascii=False).encode("utf-8")
        ep = WebhookEndpoint(url=url, enabled=True)
        await self._send(ep, payload)
