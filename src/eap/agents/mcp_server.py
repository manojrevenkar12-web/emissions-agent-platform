"""The platform's tools over MCP, for agents and developer tools (Claude Code, Claude Desktop, IDEs).

Every MCP tool call goes through the same Gateway as the HTTP API: the caller's principal comes from the
API key the server was started with (EAP_API_KEY), never from tool arguments, so an MCP client gets
exactly the rights of that key. Tools needing approval return a pending approval id instead of acting.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..platform.governance import Denied, Pending, Principal
from ..platform.orchestrator import Platform


def build_server(platform: Platform, who: Principal) -> FastMCP:
    mcp = FastMCP("emissions-agent-platform")
    gw = platform.gateway

    def call(name: str, args: dict[str, Any]) -> str:
        try:
            out = gw.call(who, name, args)
        except Denied as e:
            return json.dumps({"denied": e.reason})
        if isinstance(out, Pending):
            return json.dumps({"pending_approval": out.approval_id})
        return json.dumps(out, default=str)

    @mcp.tool()
    def query_emissions(month: int, metric: str = "total", mode: str | None = None, origin: str | None = None, destination: str | None = None) -> str:
        """Emissions in tonnes CO2e for the caller's company and one month (0 = January).
        metric: total | by_mode (with mode) | lane (with origin and destination LOCODEs) | primary_share."""
        args = {"tenant": who.tenant, "month": month, "metric": metric, "mode": mode, "origin": origin, "destination": destination}
        return call("query_emissions", {k: v for k, v in args.items() if v is not None})

    @mcp.tool()
    def list_missing_fuel(carrier_id: str, month: int) -> str:
        """Road shipments of one carrier in one month that still rest on default factors."""
        return call("list_missing_fuel", {"tenant": who.tenant, "carrier_id": carrier_id, "month": month})

    @mcp.tool()
    def list_approvals() -> str:
        """Approvals waiting for a person."""
        return call("list_approvals", {})

    return mcp


def serve_stdio() -> None:
    from ..service.api import create_demo_app, load_keys

    key = os.environ.get("EAP_API_KEY", "")
    who = load_keys().get(hashlib.sha256(key.encode()).hexdigest())
    if who is None:
        raise SystemExit("set EAP_API_KEY to a valid key")
    app = create_demo_app()
    platform: Platform = app.state.platform
    build_server(platform, who).run("stdio")
