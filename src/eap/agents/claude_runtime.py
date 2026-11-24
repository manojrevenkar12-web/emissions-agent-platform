"""A desk assistant on the Claude Agent SDK, wired to the platform's gateway.

The agent sees the platform's tools as an in-process MCP server. The SDK's `can_use_tool` callback asks the
gateway's policy before every call: tools outside the principal's role are denied, tools that need a
person are denied with a pointer to the approval queue, and the agent never gets built-in file, shell or
web tools. A PostToolUse hook records a span per call, so the agent's work shows up next to the
platform's own traces.

Requires `pip install emissions-agent-platform[claude]` and the Claude Code CLI; not exercised in CI.
"""

from __future__ import annotations

import json
from typing import Any

from ..platform.governance import Denied, Gateway, Pending, Principal
from ..platform.telemetry import Recorder, Span

SERVER = "eap"


def permission_for(gateway: Gateway, who: Principal, tool_name: str) -> tuple[bool, str]:
    """The policy the SDK callback applies. Pure, so it is tested without the SDK."""
    if not tool_name.startswith(f"mcp__{SERVER}__"):
        return False, "only platform tools are available to this agent"
    name = tool_name.removeprefix(f"mcp__{SERVER}__")
    if name not in gateway.tools:
        return False, f"unknown tool {name}"
    if name not in gateway.roles.get(who.role, set()):
        return False, f"role {who.role} may not call {name}"
    if name in gateway.needs_approval:
        return False, f"{name} needs a person: it was queued for approval instead"
    return True, "allowed"


def build_options(gateway: Gateway, who: Principal, recorder: Recorder, model: str, system_prompt: str) -> Any:
    from claude_agent_sdk import ClaudeAgentOptions, HookMatcher, PermissionResultAllow, PermissionResultDeny, create_sdk_mcp_server, tool

    tools = []
    for t in gateway.tools.values():
        if t.name not in gateway.roles.get(who.role, set()):
            continue

        def make(tname: str) -> Any:
            @tool(tname, gateway.tools[tname].description, gateway.tools[tname].schema)
            async def handler(args: dict[str, Any]) -> dict[str, Any]:
                try:
                    out = gateway.call(who, tname, args)
                except Denied as e:
                    return {"content": [{"type": "text", "text": json.dumps({"denied": e.reason})}], "is_error": True}
                if isinstance(out, Pending):
                    out = {"pending_approval": out.approval_id}
                return {"content": [{"type": "text", "text": json.dumps(out, default=str)}]}

            return handler

        tools.append(make(t.name))
    server = create_sdk_mcp_server(name=SERVER, version="1.0.0", tools=tools)

    async def can_use_tool(tool_name: str, tool_input: dict[str, Any], context: Any) -> Any:
        ok, reason = permission_for(gateway, who, tool_name)
        return PermissionResultAllow() if ok else PermissionResultDeny(message=reason)

    async def after(input_data: dict[str, Any], tool_use_id: str | None, context: Any) -> dict[str, Any]:
        recorder.add(Span(f"agent.tool:{input_data.get('tool_name', '')}", tool_use_id or "agent", 0.0, 0.0, attrs={"principal": who.subject}))
        return {}

    return ClaudeAgentOptions(
        model=model,
        system_prompt=system_prompt,
        mcp_servers={SERVER: server},
        allowed_tools=[],
        tools=[],
        can_use_tool=can_use_tool,
        hooks={"PostToolUse": [HookMatcher(hooks=[after])]},
        max_turns=8,
    )


async def ask(gateway: Gateway, who: Principal, recorder: Recorder, question: str, model: str = "claude-sonnet-5-5") -> str:
    from claude_agent_sdk import AssistantMessage, ClaudeSDKClient, TextBlock

    from ..platform import prompts

    options = build_options(gateway, who, recorder, model, prompts.QA)
    parts: list[str] = []
    async with ClaudeSDKClient(options=options) as client:
        await client.query(question)
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                parts.extend(b.text for b in msg.content if isinstance(b, TextBlock))
    return "\n".join(parts)
