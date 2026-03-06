"""
Webhook 数据模型定义

移植自 Go 工程 internal/webhook/model.go
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Any


class EventType(str, Enum):
    """Webhook 事件类型"""
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    AGENT_BLOCKED = "agent_blocked"
    EVOLUTION_TRIGGERED = "evolution_triggered"
    SAFETY_ALERT = "safety_alert"
    EXPERIENCE_REPORTED = "experience_reported"


@dataclass
class WebhookEvent:
    """Webhook 事件载荷"""
    event_type: EventType
    timestamp: str
    source: str  # 触发来源（如 task_id、skill_type）
    data: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def new_event(cls, event_type: EventType, source: str, 
                  data: Optional[Dict[str, Any]] = None) -> "WebhookEvent":
        """创建新事件"""
        return cls(
            event_type=event_type,
            timestamp=datetime.now(timezone.utc).isoformat(),
            source=source,
            data=data or {},
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "source": self.source,
            "data": self.data,
        }


@dataclass
class WebhookEndpoint:
    """单个 Webhook 端点配置"""
    id: str = ""
    url: str = ""
    event_types: List[EventType] = field(default_factory=list)  # 空表示接收所有事件
    secret: str = ""  # HMAC 签名密钥（可选）
    enabled: bool = True
    created_at: str = ""

    def should_receive(self, event_type: EventType) -> bool:
        """判断该端点是否应接收指定事件类型"""
        if not self.enabled:
            return False
        if not self.event_types:
            return True  # 空列表表示接收所有事件
        return event_type in self.event_types

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "url": self.url,
            "event_types": [et.value for et in self.event_types],
            "secret": self.secret,
            "enabled": self.enabled,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WebhookEndpoint":
        """从字典创建"""
        event_types = []
        raw_types = data.get("event_types", [])
        if isinstance(raw_types, list):
            for et in raw_types:
                if isinstance(et, str):
                    try:
                        event_types.append(EventType(et))
                    except ValueError:
                        pass  # 忽略无效的事件类型
                elif isinstance(et, EventType):
                    event_types.append(et)
        
        return cls(
            id=data.get("id", ""),
            url=data.get("url", ""),
            event_types=event_types,
            secret=data.get("secret", ""),
            enabled=data.get("enabled", True),
            created_at=data.get("created_at", ""),
        )
