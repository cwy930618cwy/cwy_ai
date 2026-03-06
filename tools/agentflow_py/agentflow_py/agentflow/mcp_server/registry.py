import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from .types import ToolDef, ToolLayer, ToolHandler, ToolResult, new_error_result

CallHook = Callable[[str, Dict], None]


class Registry:
    """Tool registry with Layer1/Layer2 support and call hooks."""

    def __init__(self, logger: logging.Logger):
        self._tools: Dict[str, Tuple[ToolDef, ToolHandler]] = {}
        self._layer2_on: bool = False
        self._call_hooks: List[CallHook] = []
        self._logger = logger
        self._lock = asyncio.Lock()

    def register(self, definition: ToolDef, handler: ToolHandler = None):
        """注册工具。支持两种方式：
        1. 直接调用: registry.register(ToolDef(...), handler)
        2. 装饰器模式: @registry.register(ToolDef(...))
        """
        if handler is None:
            # 装饰器模式，返回一个接受 handler 的函数
            def decorator(h: ToolHandler) -> ToolHandler:
                self._register_tool(definition, h)
                return h
            return decorator
        else:
            # 直接调用模式
            self._register_tool(definition, handler)

    def _register_tool(self, definition: ToolDef, handler: ToolHandler) -> None:
        if definition.name in self._tools:
            raise ValueError(f"工具已注册: {definition.name}")
        self._tools[definition.name] = (definition, handler)
        self._logger.debug(f"注册工具 name={definition.name} layer={definition.layer}")

    def enable_layer2(self) -> None:
        self._layer2_on = True
        self._logger.info("Layer 2 扩展工具已启用")

    def disable_layer2(self) -> None:
        self._layer2_on = False
        self._logger.info("Layer 2 扩展工具已禁用")

    def is_layer2_enabled(self) -> bool:
        return self._layer2_on

    def list_tools(self) -> List[ToolDef]:
        result = []
        for name, (defn, _) in self._tools.items():
            if defn.layer == ToolLayer.LAYER1 or (defn.layer == ToolLayer.LAYER2 and self._layer2_on):
                result.append(defn)
        return result

    def get_handler(self, name: str) -> Optional[ToolHandler]:
        item = self._tools.get(name)
        if not item:
            return None
        defn, handler = item
        if defn.layer == ToolLayer.LAYER2 and not self._layer2_on:
            return None
        return handler

    def add_call_hook(self, hook: CallHook) -> None:
        self._call_hooks.append(hook)

    async def call(self, name: str, params: Dict) -> ToolResult:
        item = self._tools.get(name)
        if not item:
            return new_error_result(f"工具不存在: {name}")
        defn, handler = item
        if defn.layer == ToolLayer.LAYER2 and not self._layer2_on:
            return new_error_result(
                f"工具 {name} 属于 Layer 2, 尚未启用（调用 get_extended_tools 启用）"
            )
        # Fire call hooks (for implicit heartbeat, etc.)
        for hook in self._call_hooks:
            try:
                if asyncio.iscoroutinefunction(hook):
                    await hook(name, params)
                else:
                    hook(name, params)
            except Exception as e:
                self._logger.debug(f"调用钩子异常: {e}")

        try:
            if asyncio.iscoroutinefunction(handler):
                result = await handler(params)
            else:
                result = handler(params)
            if isinstance(result, ToolResult):
                return result
            return new_error_result(f"工具返回值类型错误: {type(result)}")
        except Exception as e:
            self._logger.error(f"工具调用失败 name={name} error={e}")
            return new_error_result(f"工具执行失败: {e}")

    def list_tools_by_role(self, role: str) -> Tuple[List[ToolDef], List[ToolDef]]:
        from .roles import get_role_info
        info = get_role_info(role)
        if not info:
            return [], []
        core_set = set(info.core_tools)
        extra_set = set(info.extra_tools)
        core_tools, extra_tools = [], []
        for name, (defn, _) in self._tools.items():
            if defn.layer == ToolLayer.LAYER2 and not self._layer2_on:
                continue
            if name in core_set:
                core_tools.append(defn)
            elif name in extra_set:
                extra_tools.append(defn)
        return core_tools, extra_tools

    def unregister(self, tool_name: str) -> bool:
        """注销指定工具，返回是否成功"""
        if tool_name in self._tools:
            del self._tools[tool_name]
            self._logger.debug(f"注销工具 name={tool_name}")
            return True
        return False

    def unregister_by_prefix(self, prefix: str) -> int:
        """注销所有以指定前缀开头的工具，返回注销数量"""
        to_remove = [name for name in self._tools if name.startswith(prefix)]
        for name in to_remove:
            del self._tools[name]
            self._logger.debug(f"注销工具 name={name}")
        if to_remove:
            self._logger.info(f"按前缀注销工具 prefix={prefix}, count={len(to_remove)}")
        return len(to_remove)

    def stats(self) -> Tuple[int, int, int]:
        total = len(self._tools)
        layer1 = sum(1 for d, _ in self._tools.values() if d.layer == ToolLayer.LAYER1)
        layer2 = total - layer1
        return total, layer1, layer2