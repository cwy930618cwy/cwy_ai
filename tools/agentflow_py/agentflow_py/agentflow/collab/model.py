"""
协作通信数据模型

定义 Agent 间消息和任务评论的数据结构。
"""

import time
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Message:
    """Agent 间通信消息"""
    id: str
    from_agent: str  # 发送方 Agent ID
    to: str  # 接收方 Agent ID
    subject: str  # 消息主题
    body: str  # 消息正文
    created_at: str
    task_id: Optional[str] = None  # 关联任务 ID（可选）
    read_at: Optional[str] = None  # 已读时间（空表示未读）

    def is_read(self) -> bool:
        """判断消息是否已读"""
        return self.read_at is not None and self.read_at != ""

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "from": self.from_agent,
            "to": self.to,
            "subject": self.subject,
            "body": self.body,
            "task_id": self.task_id,
            "created_at": self.created_at,
            "read_at": self.read_at,
        }


def new_message(from_agent: str, to: str, subject: str, body: str, 
                task_id: Optional[str] = None) -> Message:
    """创建新消息"""
    return Message(
        id=f"msg_{int(time.time() * 1000)}",
        from_agent=from_agent,
        to=to,
        subject=subject,
        body=body,
        task_id=task_id,
        created_at=_format_time(),
    )


@dataclass
class Comment:
    """任务评论"""
    id: str
    task_id: str
    agent_id: str  # 评论者 Agent ID
    content: str  # 评论内容
    created_at: str
    mentions: List[str] = field(default_factory=list)  # @提及的 Agent ID 列表

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "content": self.content,
            "mentions": self.mentions,
            "created_at": self.created_at,
        }


def new_comment(task_id: str, agent_id: str, content: str, 
                mentions: List[str]) -> Comment:
    """创建新评论"""
    return Comment(
        id=f"cmt_{int(time.time() * 1000)}",
        task_id=task_id,
        agent_id=agent_id,
        content=content,
        mentions=mentions,
        created_at=_format_time(),
    )


def _format_time() -> str:
    """格式化时间为 RFC3339 格式"""
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
