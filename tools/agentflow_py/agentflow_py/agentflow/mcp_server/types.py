import json
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Dict, List, Optional


class ToolLayer(IntEnum):
    LAYER1 = 1
    LAYER2 = 2


@dataclass
class ContentBlock:
    type: str = "text"
    text: str = ""


@dataclass
class ToolResult:
    content: List[ContentBlock] = field(default_factory=list)
    is_error: bool = False

    def to_dict(self) -> Dict:
        d: Dict = {"content": [{"type": b.type, "text": b.text} for b in self.content]}
        if self.is_error:
            d["isError"] = True
        return d


@dataclass
class ToolDef:
    name: str
    description: str
    input_schema: Any  # dict or pre-serialized dict
    layer: ToolLayer = ToolLayer.LAYER1

    def to_dict(self) -> Dict:
        schema = self.input_schema
        if isinstance(schema, str):
            schema = json.loads(schema)
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": schema,
        }


ToolHandler = Callable[[Dict], Any]


def new_text_result(text: str) -> ToolResult:
    return ToolResult(content=[ContentBlock(type="text", text=text)])


def new_json_result(data: Any) -> ToolResult:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    return ToolResult(content=[ContentBlock(type="text", text=text)])


def new_error_result(msg: str) -> ToolResult:
    return ToolResult(
        content=[ContentBlock(type="text", text=msg)],
        is_error=True,
    )
