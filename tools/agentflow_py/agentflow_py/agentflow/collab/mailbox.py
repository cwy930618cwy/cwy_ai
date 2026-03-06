"""
Agent 邮箱系统

基于 Redis Stream 实现 Agent 间的消息传递。
"""

import json
import logging
from typing import List, Optional

from .model import Message, new_message


MAILBOX_MAX_LEN = 200  # 每个 Agent 的邮箱最多保留 200 条消息


class Mailbox:
    """Agent 邮箱（基于 KVStore）"""

    def __init__(self, redis, logger: Optional[logging.Logger] = None):
        self._redis = redis
        self._logger = logger or logging.getLogger(__name__)

    def _mailbox_key(self, agent_id: str) -> str:
        """生成邮箱 Stream key"""
        return self._redis.key("mailbox", agent_id)

    def _read_cursor_key(self, agent_id: str) -> str:
        """生成已读游标 key（记录最后已读的 Stream ID）"""
        return self._redis.key("mailbox", agent_id, "read_cursor")

    async def send(self, msg: Message) -> None:
        """发送消息到目标 Agent 的邮箱"""
        if not msg.from_agent or not msg.to:
            raise ValueError("from_agent 和 to 不能为空")
        if not msg.body:
            raise ValueError("消息正文不能为空")

        data = json.dumps(msg.to_dict(), ensure_ascii=False)
        key = self._mailbox_key(msg.to)
        
        await self._redis.xadd(key, {"msg": data}, maxlen=MAILBOX_MAX_LEN)
        self._logger.debug(f"消息已发送 from={msg.from_agent} to={msg.to} subject={msg.subject}")

    async def read(self, agent_id: str, limit: int = 20) -> List[Message]:
        """读取 Agent 的邮箱消息（最新 limit 条）"""
        if limit <= 0:
            limit = 20
        
        key = self._mailbox_key(agent_id)
        entries = await self._redis.xrevrange(key, max_id="+", min_id="-", count=limit)
        
        # 获取已读游标
        read_cursor = await self._redis.get(self._read_cursor_key(agent_id))
        
        messages = []
        for entry in entries:
            fields = entry.get("fields", {})
            msg_str = fields.get("msg")
            if not msg_str:
                continue
            
            try:
                msg_data = json.loads(msg_str)
                msg = Message(
                    id=msg_data["id"],
                    from_agent=msg_data["from"],
                    to=msg_data["to"],
                    subject=msg_data["subject"],
                    body=msg_data["body"],
                    task_id=msg_data.get("task_id"),
                    created_at=msg_data["created_at"],
                    read_at=msg_data.get("read_at"),
                )
                # 标记已读状态（Stream ID <= read_cursor 的消息为已读）
                if read_cursor and entry["id"] <= read_cursor and not msg.read_at:
                    msg.read_at = msg.created_at  # 标记为已读
                messages.append(msg)
            except (json.JSONDecodeError, KeyError) as e:
                self._logger.warning(f"解析消息失败: {e}")
                continue
        
        # xrevrange 返回倒序（最新在前），reverse 为时间正序返回
        messages.reverse()
        return messages

    async def mark_all_read(self, agent_id: str) -> None:
        """标记所有消息为已读（更新游标到最新消息）"""
        key = self._mailbox_key(agent_id)
        entries = await self._redis.xrevrange(key, max_id="+", min_id="-", count=1)
        
        if not entries:
            return
        
        latest_id = entries[0]["id"]
        cursor_key = self._read_cursor_key(agent_id)
        # 游标保留 7 天
        await self._redis.set(cursor_key, latest_id, ex=7 * 24 * 3600)

    async def unread_count(self, agent_id: str) -> int:
        """获取未读消息数量"""
        key = self._mailbox_key(agent_id)
        total = await self._redis.xlen(key)
        
        # 获取已读游标
        read_cursor = await self._redis.get(self._read_cursor_key(agent_id))
        if not read_cursor:
            # 没有已读记录，全部未读
            return total
        
        # 统计游标之后的消息数量（未读）
        entries = await self._redis.xrevrange(key, max_id="+", min_id=read_cursor)
        # xrevrange 包含 read_cursor 本身，减去1
        unread = len(entries) - 1 if entries else 0
        return max(0, unread)
