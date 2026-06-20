"""
KPI Monitor MCP Server — Streamable HTTP transport

Uses StreamableHTTPSessionManager (mcp >= 1.1) which handles both GET and POST
on a single /mcp endpoint — the protocol expected by the Anthropic MCP client beta.

Deploy on Render:
    render.yaml handles start command

Local test:
    python mcp_server_sse.py
    # exposes http://localhost:8000/mcp
"""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
import uvicorn

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from mcp_server import app  # reuse the fully-configured MCP app

session_manager = StreamableHTTPSessionManager(app=app, stateless=True, json_response=True)


async def handle_mcp(request: Request) -> None:
    await session_manager.handle_request(request.scope, request.receive, request._send)


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": "kpi-monitor"})


@contextlib.asynccontextmanager
async def lifespan(app_: Starlette):
    async with session_manager.run():
        yield


starlette_app = Starlette(
    lifespan=lifespan,
    routes=[
        Route("/health", endpoint=health),
        Route("/mcp", endpoint=handle_mcp, methods=["GET", "POST", "DELETE"]),
    ],
)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(starlette_app, host="0.0.0.0", port=port)
