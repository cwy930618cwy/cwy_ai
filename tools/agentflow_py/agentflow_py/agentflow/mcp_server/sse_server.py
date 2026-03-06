"""MCP SSE/HTTP Server - Streamable HTTP transport."""
import json
import logging
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from .registry import Registry
from .types import ToolResult

MCP_PROTOCOL_VERSION = "2024-11-05"
JSONRPC_VERSION = "2.0"


class SSEServer:
    def __init__(self, registry: Registry, addr: str, logger: logging.Logger):
        self._registry = registry
        self._addr = addr  # e.g. ":8080"
        self._logger = logger
        self._server_name = "agentflow"
        self._server_version = "2.0.0"
        self._app = self._build_app()
        self._server: Optional[uvicorn.Server] = None

    def _build_app(self) -> FastAPI:
        app = FastAPI(title="AgentFlow MCP", version=self._server_version)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization"],
        )

        @app.post("/mcp")
        async def mcp_endpoint(request: Request) -> Response:
            body = await request.body()
            if not body:
                return JSONResponse({"error": "Empty body"}, status_code=400)
            try:
                req = json.loads(body)
            except json.JSONDecodeError as e:
                return JSONResponse(self._make_error_response(None, -32700, f"解析错误: {e}"))

            return JSONResponse(await self._handle_rpc(req))

        @app.get("/health")
        async def health() -> Dict:
            total, l1, l2 = self._registry.stats()
            return {
                "status": "ok",
                "server": self._server_name,
                "version": self._server_version,
                "tools": {"total": total, "layer1": l1, "layer2": l2},
            }

        return app

    async def _handle_rpc(self, req: Dict) -> Dict:
        method = req.get("method", "")
        req_id = req.get("id")
        params = req.get("params") or {}

        self._logger.debug(f"收到HTTP请求 method={method} id={req_id}")

        result = None
        rpc_error = None

        if method == "initialize":
            result = self._handle_initialize(params)
        elif method in ("initialized", "notifications/initialized"):
            result = {}
        elif method == "tools/list":
            result = self._handle_tools_list()
        elif method == "tools/call":
            result, rpc_error = await self._handle_tools_call(params)
        elif method == "ping":
            result = {}
        else:
            rpc_error = {"code": -32601, "message": f"未知方法: {method}"}

        resp: Dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "id": req_id}
        if rpc_error:
            resp["error"] = rpc_error
        else:
            resp["result"] = result
        return resp

    def _make_error_response(self, req_id: Any, code: int, msg: str) -> Dict:
        return {"jsonrpc": JSONRPC_VERSION, "id": req_id, "error": {"code": code, "message": msg}}

    def _handle_initialize(self, params: Dict) -> Dict:
        total, l1, l2 = self._registry.stats()
        self._logger.info(f"MCP HTTP初始化 tools_total={total} layer1={l1} layer2={l2}")
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
        self._logger.info(f"调用工具(HTTP) name={name}")
        result: ToolResult = await self._registry.call(name, arguments)
        return result.to_dict(), None

    def get_app(self) -> FastAPI:
        return self._app

    async def serve(self) -> None:
        host, port = self._parse_addr()
        config = uvicorn.Config(
            self._app,
            host=host,
            port=port,
            log_level="warning",
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        self._logger.info(
            f"AgentFlow MCP Server 启动 transport=streamable-http "
            f"addr={self._addr} endpoint=http://{host}:{port}/mcp"
        )
        await self._server.serve()

    async def stop(self) -> None:
        if self._server:
            self._server.should_exit = True

    def _parse_addr(self):
        addr = self._addr
        if addr.startswith(":"):
            return "0.0.0.0", int(addr[1:])
        parts = addr.rsplit(":", 1)
        host = parts[0] or "0.0.0.0"
        port = int(parts[1]) if len(parts) > 1 else 8080
        return host, port
