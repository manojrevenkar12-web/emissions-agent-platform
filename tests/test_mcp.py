"""The same gateway over MCP: tools list, calls carry the caller's tenant."""

from __future__ import annotations

import json

from mcp.shared.memory import create_connected_server_and_client_session

from eap.agents.claude_runtime import permission_for
from eap.agents.mcp_server import build_server
from eap.platform.governance import Principal
from eap.service.api import create_demo_app


async def test_mcp_tools_answer_for_the_callers_tenant_only() -> None:
    app = create_demo_app()
    plat = app.state.platform
    server = build_server(plat, Principal("viewer@nordhafen", "customer_viewer", "T1"))
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        tools = {t.name for t in (await client.list_tools()).tools}
        assert {"query_emissions", "list_missing_fuel", "list_approvals"} <= tools
        r = await client.call_tool("query_emissions", {"month": 0})
        assert json.loads(r.content[0].text)["value"] > 0
        r = await client.call_tool("list_approvals", {})
        assert "denied" in json.loads(r.content[0].text)


def test_the_agent_sdk_policy_follows_the_gateway() -> None:
    plat = create_demo_app().state.platform
    gw = plat.gateway
    agent = Principal("clarification_agent:T1", "clarification_agent", "T1")
    assert permission_for(gw, agent, "mcp__eap__list_missing_fuel") == (True, "allowed")
    assert not permission_for(gw, agent, "mcp__eap__send_carrier_email")[0]
    assert not permission_for(gw, agent, "Bash")[0]
    assert not permission_for(gw, Principal("q", "qa_agent", "T1"), "mcp__eap__update_shipments")[0]
