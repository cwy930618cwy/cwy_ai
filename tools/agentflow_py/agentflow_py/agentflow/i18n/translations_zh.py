"""
中文翻译字典
"""

translationsZH: dict[str, str] = {
    # ===== 通用 =====
    "common.success": "成功",
    "common.failed": "失败",
    "common.not_found": "未找到",
    "common.invalid_param": "参数无效",
    "common.internal_error": "内部错误",

    # ===== 任务状态 =====
    "task.status.pending": "待处理",
    "task.status.running": "执行中",
    "task.status.completed": "已完成",
    "task.status.failed": "已失败",
    "task.status.blocked": "已阻塞",
    "task.status.interrupted": "已中断",
    "task.status.review": "待审查",

    # ===== 任务事件 =====
    "task.completed": "任务已完成",
    "task.failed": "任务已失败",
    "task.blocked": "任务已阻塞",
    "task.claimed": "任务已认领",
    "task.released": "任务已释放",
    "task.no_available": "暂无可用任务",
    "task.overloaded": "Agent 当前任务数已达上限，请先完成现有任务",
    "task.dependency_not_met": "任务依赖尚未满足",

    # ===== 目标 =====
    "goal.created": "目标已创建",
    "goal.completed": "目标已完成",
    "goal.cancelled": "目标已取消",

    # ===== 经验 =====
    "experience.reported": "经验已上报",
    "experience.evolution_hint": "🧠 检测到经验模式已达进化阈值，建议调用 distill_and_evolve 触发进化",
    "experience.no_results": "未找到相关经验",

    # ===== 进化 =====
    "evolution.triggered": "进化已触发",
    "evolution.completed": "进化已完成",
    "evolution.no_proposals": "未生成进化提案",

    # ===== Webhook =====
    "webhook.added": "✅ Webhook 端点已添加",
    "webhook.removed": "✅ Webhook 端点已删除",
    "webhook.tested": "✅ 测试事件发送成功",
    "webhook.failed": "❌ 测试失败，请检查 URL 是否可达",

    # ===== 协作 =====
    "collab.message_sent": "✅ 消息已发送",
    "collab.comment_added": "✅ 评论已添加",
    "collab.no_messages": "暂无消息",
    "collab.no_comments": "暂无评论",

    # ===== 安全 =====
    "safety.health_green": "✅ 系统健康",
    "safety.health_yellow": "⚠️ 系统存在警告",
    "safety.health_red": "🚨 系统存在严重问题",

    # ===== 工具描述（MCP 工具的多语言 Description）=====
    "tool.claim_task.description": "原子认领任务。task_id可选(不填则智能派发)。如果之前有被中断的任务,会优先恢复。支持亲和性调度(affinity_skills)、deadline紧迫度加权、负载均衡。",
    "tool.report_task_result.description": "汇报任务执行结果。status 支持 completed/failed/blocked。",
    "tool.create_tasks.description": "根据目标创建任务列表。支持依赖关系、难度评分、测试设计和截止时间。",
    "tool.send_message.description": "向其他 Agent 发送消息。支持关联任务 ID。",
    "tool.add_task_comment.description": "在任务上添加评论。支持 @agentID 语法触发通知。",
    "tool.webhook_add.description": "添加 Webhook 端点。当指定事件发生时，AICommander 会向该 URL 发送 HTTP POST 通知。",
    "tool.get_dashboard.description": "获取 AgentFlow 全局仪表盘：目标进度/任务统计/通过率/Token消耗/Skill效能/进化状态/经验库/Archive分数。",
}
