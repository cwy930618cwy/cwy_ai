"""
任务评论系统

支持任务评论和 @mention 通知功能。
"""

import json
import logging
import re
import uuid
from typing import List, Optional

from .model import Comment, Message, new_comment
from .mailbox import Mailbox


COMMENTS_MAX_LEN = 100  # 每个任务最多保留 100 条评论

# 匹配 @agentID 格式（字母数字下划线横线）
MENTION_REGEX = re.compile(r"@([a-zA-Z0-9_\-]+)")


def extract_mentions(content: str) -> List[str]:
    """从内容中提取 @mention 的 Agent ID 列表"""
    matches = MENTION_REGEX.findall(content)
    seen = set()
    mentions = []
    for m in matches:
        if m not in seen:
            seen.add(m)
            mentions.append(m)
    return mentions


class CommentStore:
    """任务评论存储"""

    def __init__(self, redis, mailbox: Optional[Mailbox] = None,
                 logger: Optional[logging.Logger] = None):
        self._redis = redis
        self._mailbox = mailbox
        self._logger = logger or logging.getLogger(__name__)

    def _comments_key(self, task_id: str) -> str:
        """生成评论 List key"""
        return self._redis.key("task", task_id, "comments")

    async def add_comment(self, task_id: str, agent_id: str, content: str) -> Comment:
        """添加评论，自动解析 @mention 并发送通知"""
        if not task_id or not agent_id:
            raise ValueError("task_id 和 agent_id 不能为空")
        if not content or not content.strip():
            raise ValueError("评论内容不能为空")

        # 解析 @mention
        mentions = extract_mentions(content)

        comment = new_comment(task_id, agent_id, content, mentions)
        data = json.dumps(comment.to_dict(), ensure_ascii=False)

        # 使用 RPush 追加到 List 末尾
        key = self._comments_key(task_id)
        await self._redis.rpush(key, data)

        # 使用 Lua 脚本保证 llen + ltrim 原子性（防止高并发下误删评论）
        _LTRIM_SCRIPT = """
        local len = redis.call('LLEN', KEYS[1])
        if len > tonumber(ARGV[1]) then
          redis.call('LTRIM', KEYS[1], -tonumber(ARGV[1]), -1)
        end
        return len
        """
        await self._redis.eval(_LTRIM_SCRIPT, [key], str(COMMENTS_MAX_LEN))

        # 发送 @mention 通知
        if self._mailbox and mentions:
            for mentioned_agent in mentions:
                if mentioned_agent == agent_id:
                    continue  # 不通知自己
                notify_msg = Message(
                    id=f"msg_{uuid.uuid4().hex[:12]}",
                    from_agent=agent_id,
                    to=mentioned_agent,
                    subject=f"📌 任务 [{task_id}] 中有人@了你",
                    body=f"{agent_id} 在任务 [{task_id}] 的评论中提到了你：\n\n{content}",
                    task_id=task_id,
                    created_at=comment.created_at,
                )
                try:
                    await self._mailbox.send(notify_msg)
                except Exception as e:
                    self._logger.warning(f"发送@mention通知失败 to={mentioned_agent} error={e}")

        self._logger.debug(f"评论已添加 task_id={task_id} agent_id={agent_id} mentions={mentions}")
        return comment

    async def get_comments(self, task_id: str) -> List[Comment]:
        """获取任务的所有评论"""
        key = self._comments_key(task_id)
        entries = await self._redis.lrange(key, 0, -1)

        comments = []
        for entry in entries:
            try:
                data = json.loads(entry)
                comment = Comment(
                    id=data["id"],
                    task_id=data["task_id"],
                    agent_id=data["agent_id"],
                    content=data["content"],
                    mentions=data.get("mentions", []),
                    created_at=data["created_at"],
                )
                comments.append(comment)
            except (json.JSONDecodeError, KeyError) as e:
                self._logger.warning(f"解析评论失败: {e}")
                continue
        
        return comments
