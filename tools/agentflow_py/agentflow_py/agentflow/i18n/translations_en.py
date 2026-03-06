"""
英文翻译字典
English translation dictionary
"""

translationsEN: dict[str, str] = {
    # ===== Common =====
    "common.success": "Success",
    "common.failed": "Failed",
    "common.not_found": "Not found",
    "common.invalid_param": "Invalid parameter",
    "common.internal_error": "Internal error",

    # ===== Task Status =====
    "task.status.pending": "Pending",
    "task.status.running": "Running",
    "task.status.completed": "Completed",
    "task.status.failed": "Failed",
    "task.status.blocked": "Blocked",
    "task.status.interrupted": "Interrupted",
    "task.status.review": "In Review",

    # ===== Task Events =====
    "task.completed": "Task completed",
    "task.failed": "Task failed",
    "task.blocked": "Task blocked",
    "task.claimed": "Task claimed",
    "task.released": "Task released",
    "task.no_available": "No available tasks",
    "task.overloaded": "Agent has reached the concurrent task limit. Please complete existing tasks first.",
    "task.dependency_not_met": "Task dependencies not yet satisfied",

    # ===== Goal =====
    "goal.created": "Goal created",
    "goal.completed": "Goal completed",
    "goal.cancelled": "Goal cancelled",

    # ===== Experience =====
    "experience.reported": "Experience reported",
    "experience.evolution_hint": "🧠 Experience pattern has reached evolution threshold. Consider calling distill_and_evolve.",
    "experience.no_results": "No relevant experiences found",

    # ===== Evolution =====
    "evolution.triggered": "Evolution triggered",
    "evolution.completed": "Evolution completed",
    "evolution.no_proposals": "No evolution proposals generated",

    # ===== Webhook =====
    "webhook.added": "✅ Webhook endpoint added",
    "webhook.removed": "✅ Webhook endpoint removed",
    "webhook.tested": "✅ Test event sent successfully",
    "webhook.failed": "❌ Test failed. Please check if the URL is reachable.",

    # ===== Collaboration =====
    "collab.message_sent": "✅ Message sent",
    "collab.comment_added": "✅ Comment added",
    "collab.no_messages": "No messages",
    "collab.no_comments": "No comments",

    # ===== Safety =====
    "safety.health_green": "✅ System healthy",
    "safety.health_yellow": "⚠️ System has warnings",
    "safety.health_red": "🚨 System has critical issues",

    # ===== Tool Descriptions (MCP tool multilingual descriptions) =====
    "tool.claim_task.description": "Atomically claim a task. task_id is optional (smart dispatch if omitted). Interrupted tasks are prioritized. Supports affinity scheduling (affinity_skills), deadline-aware weighting, and load balancing.",
    "tool.report_task_result.description": "Report task execution result. status supports completed/failed/blocked.",
    "tool.create_tasks.description": "Create a list of tasks for a goal. Supports dependencies, difficulty scoring, test design, and deadlines.",
    "tool.send_message.description": "Send a message to another Agent. Supports associating a task ID.",
    "tool.add_task_comment.description": "Add a comment to a task. Supports @agentID syntax to trigger notifications.",
    "tool.webhook_add.description": "Add a Webhook endpoint. AICommander will send HTTP POST notifications to this URL when specified events occur.",
    "tool.get_dashboard.description": "Get the AgentFlow global dashboard: goal progress, task stats, pass rate, token usage, skill performance, evolution status, experience library, and archive scores.",
}
