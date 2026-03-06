"""MCP Server - stdio transport (JSON-RPC 2.0)."""
import asyncio
import json
import logging
import sys
from typing import Any, Dict, Optional

from .registry import Registry
from .types import ToolResult

MCP_PROTOCOL_VERSION = "2024-11-05"
JSONRPC_VERSION = "2.0"


class MCPServer:
    def __init__(self, registry: Registry, logger: logging.Logger):
        self._registry = registry
        self._logger = logger
        self._server_name = "agentflow"
        self._server_version = "2.0.0"
        self._initialized = False
        self._running = False

    async def serve(self) -> None:
        self._running = True
        self._logger.info(f"AgentFlow MCP Server 启动 transport=stdio version={self._server_version}")
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin.buffer)

        write_transport, _ = await loop.connect_write_pipe(asyncio.BaseProtocol, sys.stdout.buffer)

        async def write_line(data: bytes) -> None:
            write_transport.write(data + b"\n")

        try:
            while self._running:
                try:
                    line = await asyncio.wait_for(reader.readline(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                if not line:
                    self._logger.info("stdin EOF, 服务退出")
                    break
                line = line.strip()
                if not line:
                    continue
                asyncio.create_task(self._handle_message(line, write_line))
        finally:
            self._running = False

    def stop(self) -> None:
        self._running = False

    async def _handle_message(self, data: bytes, write_fn) -> None:
        try:
            req = json.loads(data)
        except json.JSONDecodeError as e:
            self._logger.error(f"解析JSON-RPC请求失败: {e}")
            return

        method = req.get("method", "")
        req_id = req.get("id")
        params = req.get("params") or {}

        self._logger.debug(f"收到请求 method={method} id={req_id}")

        result = None
        rpc_error = None

        if method == "initialize":
            result = self._handle_initialize(params)
        elif method == "initialized":
            self._initialized = True
            return
        elif method == "tools/list":
            result = self._handle_tools_list()
        elif method == "tools/call":
            result, rpc_error = await self._handle_tools_call(params)
        elif method == "ping":
            result = {}
        else:
            rpc_error = {"code": -32601, "message": f"未知方法: {method}"}

        if req_id is not None:
            resp: Dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "id": req_id}
            if rpc_error:
                resp["error"] = rpc_error
            else:
                resp["result"] = result
            try:
                await write_fn(json.dumps(resp, ensure_ascii=False).encode())
            except Exception as e:
                self._logger.error(f"写入响应失败: {e}")

    def _handle_initialize(self, params: Dict) -> Dict:
        total, l1, l2 = self._registry.stats()
        self._logger.info(f"MCP初始化 tools_total={total} layer1={l1} layer2={l2}")
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": self._server_name, "version": self._server_version},
        }

    def _handle_tools_list(self) -> Dict:
        tools = self._registry.list_tools()
        return {"tools": [t.to_dict() for t in tools]}

    async def _handle_tools_call(self, params: Dict):
        name = params.get("name", "")
        arguments = params.get("arguments") or {}

        param_str = json.dumps(arguments)[:500]
        self._logger.info(f"调用工具 name={name} params={param_str}")

        result: ToolResult = await self._registry.call(name, arguments)
        result_dict = result.to_dict()

        result_str = json.dumps(result_dict)[:500]
        self._logger.info(f"工具调用完成 name={name} result={result_str}")

        return result_dict, None
