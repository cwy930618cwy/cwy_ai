#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 collab 模块导入"""

import sys
sys.path.insert(0, '.')

from agentflow.collab.model import Message, Comment, new_message, new_comment
from agentflow.collab.mailbox import Mailbox
from agentflow.collab.comment import CommentStore, extract_mentions
from agentflow.collab.tools import register_tools

# 测试数据模型
msg = new_message("agent1", "agent2", "测试主题", "测试内容", "task_001")
print(f"Message: id={msg.id}, from={msg.from_agent}, to={msg.to}")

cmt = new_comment("task_001", "agent1", "评论内容 @agent2 @agent3", ["agent2", "agent3"])
print(f"Comment: id={cmt.id}, mentions={cmt.mentions}")

# 测试 mention 提取
mentions = extract_mentions("Hello @agent1 and @agent2, @agent1 again!")
print(f"Extracted mentions: {mentions}")

print("\n[OK] collab module verified!")
