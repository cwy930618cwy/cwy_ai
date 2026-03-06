"""
Agent 协作通信 MCP 工具

提供 Agent 间消息传递和任务评论功能。
"""

import json
from typing import TYPE_CHECKING

from agentflow.mcp_server.types import ToolDef, ToolLayer, ToolResult, new_json_result, new_error_result
from .model import Message, new_message
from .mailbox import Mailbox
from .comment import CommentStore

if TYPE_CHECKING:
    from agentflow.mcp_server.registry import Registry


# 工具 JSON Schema 定义
SEND_MESSAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "from": {"type": "string", "description": "发送方 Agent ID"},
        "to": {"type": "string", "description": "接收方 Agent ID"},
        "subject": {"type": "string", "description": "消息主题"},
        "body": {"type": "string", "description": "消息正文"},
        "task_id": {"type": "string", "description": "关联任务 ID（可选）"}
    },
    "required": ["from", "to", "subject", "body"]
}

READ_MESSAGES_SCHEMA = {
    "type": "object",
    "properties": {
        "agent_id": {"type": "string", "description": "要读取邮箱的 Agent ID"},
        "limit": {"type": "integer", "description": "最多返回条数，默认 20，最大 50"},
        "mark_read": {"type": "boolean", "description": "是否标记所有消息为已读，默认 false"}
    },
    "required": ["agent_id"]
}

MARK_MESSAGES_READ_SCHEMA = {
    "type": "object",
    "properties": {
        "agent_id": {"type": "string", "description": "Agent ID"}
    },
    "required": ["agent_id"]
}

ADD_TASK_COMMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "task_id": {"type": "string", "description": "任务 ID"},
        "agent_id": {"type": "string", "description": "评论者 Agent ID"},
        "content": {"type": "string", "description": "评论内容，支持 @agentID 语法触发通知"}
    },
    "required": ["task_id", "agent_id", "content"]
}

GET_TASK_COMMENTS_SCHEMA = {
    "type": "object",
    "properties": {
        "task_id": {"type": "string", "description": "任务 ID"}
    },
    "required": ["task_id"]
}


def register_tools(registry: "Registry", mailbox: Mailbox, comments: CommentStore) -> None:
    """注册 Agent 协作通信 MCP 工具"""

    # send_message: 向其他 Agent 发送消息
    async def handle_send_message(params: dict) -> ToolResult:
        from_agent = params.get("from", "")
        to = params.get("to", "")
        subject = params.get("subject", "")
        body = params.get("body", "")
        task_id = params.get("task_id")

        if not from_agent or not to:
            return new_error_result("from 和 to 不能为空")
        if not body:
            return new_error_result("消息正文不能为空")

        msg = new_message(from_agent, to, subject, body, task_id)
        try:
            await mailbox.send(msg)
        except Exception as e:
            return new_error_result(f"发送消息失败: {e}")

        return new_json_result({
            "message_id": msg.id,
            "from": msg.from_agent,
            "to": msg.to,
            "subject": msg.subject,
            "created_at": msg.created_at,
            "message": "✅ 消息已发送",
        })

    registry.register(ToolDef(
        name="send_message",
        description="向其他 Agent 发送消息。支持关联任务 ID，接收方可通过 read_messages 查看。",
        input_schema=SEND_MESSAGE_SCHEMA,
        layer=ToolLayer.LAYER1,
    ), handle_send_message)

    # read_messages: 读取 Agent 的邮箱消息
    async def handle_read_messages(params: dict) -> ToolResult:
        agent_id = params.get("agent_id", "")
        limit = params.get("limit", 20)
        mark_read = params.get("mark_read", False)

        if not agent_id:
            return new_error_result("agent_id 不能为空")
        if limit <= 0 or limit > 50:
            limit = 20

        try:
            messages = await mailbox.read(agent_id, limit)
            unread = await mailbox.unread_count(agent_id)
            
            if mark_read:
                await mailbox.mark_all_read(agent_id)
                unread = 0

            return new_json_result({
                "messages": [m.to_dict() for m in messages],
                "total": len(messages),
                "unread": unread,
            })
        except Exception as e:
            return new_error_result(f"读取消息失败: {e}")

    registry.register(ToolDef(
        name="read_messages",
        description="读取指定 Agent 的邮箱消息（最新 N 条）。同时返回未读消息数量。",
        input_schema=READ_MESSAGES_SCHEMA,
        layer=ToolLayer.LAYER1,
    ), handle_read_messages)

    # mark_messages_read: 标记所有消息为已读
    async def handle_mark_messages_read(params: dict) -> ToolResult:
        agent_id = params.get("agent_id", "")

        if not agent_id:
            return new_error_result("agent_id 不能为空")

        try:
            await mailbox.mark_all_read(agent_id)
        except Exception as e:
            return new_error_result(f"标记已读失败: {e}")

        return new_json_result({
            "agent_id": agent_id,
            "message": "✅ 所有消息已标记为已读",
        })

    registry.register(ToolDef(
        name="mark_messages_read",
        description="将指定 Agent 邮箱中的所有消息标记为已读。",
        input_schema=MARK_MESSAGES_READ_SCHEMA,
        layer=ToolLayer.LAYER1,
    ), handle_mark_messages_read)

    # add_task_comment: 添加任务评论
    async def handle_add_task_comment(params: dict) -> ToolResult:
        task_id = params.get("task_id", "")
        agent_id = params.get("agent_id", "")
        content = params.get("content", "")

        if not task_id or not agent_id:
            return new_error_result("task_id 和 agent_id 不能为空")
        if not content:
            return new_error_result("评论内容不能为空")

        try:
            comment = await comments.add_comment(task_id, agent_id, content)
        except Exception as e:
            return new_error_result(f"添加评论失败: {e}")

        result = {
            "comment_id": comment.id,
            "task_id": comment.task_id,
            "agent_id": comment.agent_id,
            "content": comment.content,
            "created_at": comment.created_at,
            "message": "✅ 评论已添加",
        }
        if comment.mentions:
            result["mentions_notified"] = comment.mentions
            result["message"] = f"✅ 评论已添加，已通知 {len(comment.mentions)} 位 Agent"

        return new_json_result(result)

    registry.register(ToolDef(
        name="add_task_comment",
        description="在任务上添加评论。支持 @agentID 语法，被@的 Agent 会收到邮箱通知。",
        input_schema=ADD_TASK_COMMENT_SCHEMA,
        layer=ToolLayer.LAYER1,
    ), handle_add_task_comment)

    # get_task_comments: 获取任务评论列表
    async def handle_get_task_comments(params: dict) -> ToolResult:
        task_id = params.get("task_id", "")

        if not task_id:
            return new_error_result("task_id 不能为空")

        try:
            comment_list = await comments.get_comments(task_id)
        except Exception as e:
            return new_error_result(f"获取评论失败: {e}")

        if not comment_list:
            return new_json_result({
                "task_id": task_id,
                "comments": [],
                "total": 0,
                "message": "暂无评论",
            })

        return new_json_result({
            "task_id": task_id,
            "comments": [c.to_dict() for c in comment_list],
            "total": len(comment_list),
        })

    registry.register(ToolDef(
        name="get_task_comments",
        description="获取指定任务的所有评论（按时间正序）。",
        input_schema=GET_TASK_COMMENTS_SCHEMA,
        layer=ToolLayer.LAYER1,
    ), handle_get_task_comments)
