"""
AgentFlow 协作通信模块

提供任务评论系统和 Agent 邮箱系统，支持 Agent 间消息传递和 @mention 通知。
"""

from .model import Message, Comment, new_message, new_comment
from .mailbox import Mailbox
from .comment import CommentStore
from .tools import register_tools

__all__ = [
    "Message",
    "Comment", 
    "new_message",
    "new_comment",
    "Mailbox",
    "CommentStore",
    "register_tools",
]
