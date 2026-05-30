"""
Smart Proxy Forwarder — MCP Server

Exposes proxy-forwarder management as MCP tools for AI agents.

Usage:
  python proxy_forwarder_mcp.py

Register in ~/.hermes/config.yaml:
  mcp_servers:
    proxy:
      command: "python"
      args: ["/path/to/proxy_forwarder_mcp.py"]
"""
import argparse
import json
import os
import subprocess
import sys
from typing import Any

from mcp.server import Server
from mcp.server.models import InitializationOptions
import mcp.server.stdio
import mcp.types as types
from mcp.types import ServerCapabilities, ToolsCapability

# ── Config ──
CONFIG_DIR = os.path.expanduser("~/.config/proxy-forwarder")
MANAGER = os.path.join(CONFIG_DIR, "proxy-manager.sh")
STATS_FILE = "/tmp/proxy-forwarder-stats.json"

app = Server("proxy-forwarder")


def _run_manager(action: str) -> dict:
    try:
        result = subprocess.run(
            ["bash", MANAGER, action],
            capture_output=True, text=True, timeout=15
        )
        return {"success": result.returncode == 0, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}
    except FileNotFoundError:
        return {"success": False, "stdout": "", "stderr": "Manager script not found at " + MANAGER}
    except subprocess.TimeoutExpired:
        return {"success": False, "stdout": "", "stderr": "Command timed out"}


def _read_stats() -> dict:
    try:
        with open(STATS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="status",
            description="Get proxy forwarder status: running/stopped, PID, port, uptime, connections, traffic, health",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="start",
            description="Start the proxy forwarder (no-op if already running)",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="stop",
            description="Stop the proxy forwarder",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="restart",
            description="Restart the proxy forwarder",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="stats",
            description="Get detailed proxy statistics as JSON: connections, traffic, upstream, health",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="logs",
            description="View the last 50 lines of proxy forwarder logs",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "status":
        r = _run_manager("status")
        return [types.TextContent(type="text", text=r["stdout"] or r["stderr"])]
    elif name == "start":
        r = _run_manager("start")
        return [types.TextContent(type="text", text=r["stdout"] or r["stderr"])]
    elif name == "stop":
        r = _run_manager("stop")
        return [types.TextContent(type="text", text=r["stdout"] or r["stderr"])]
    elif name == "restart":
        r = _run_manager("restart")
        return [types.TextContent(type="text", text=r["stdout"] or r["stderr"])]
    elif name == "stats":
        data = _read_stats()
        if not data:
            return [types.TextContent(type="text", text="Proxy not running or stats unavailable")]
        return [types.TextContent(type="text", text=json.dumps(data, indent=2, ensure_ascii=False))]
    elif name == "logs":
        r = _run_manager("logs")
        return [types.TextContent(type="text", text=r["stdout"] or r["stderr"])]
    raise ValueError(f"Unknown tool: {name}")


async def main_stdio():
    async with mcp.server.stdio.stdio_server() as (read, write):
        await app.run(
            read, write,
            InitializationOptions(
                server_name="proxy-forwarder",
                server_version="1.0.0",
                capabilities=ServerCapabilities(tools=ToolsCapability(list_tools=True)),
            ),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main_stdio())
