# 0006 One gateway for every tool call: roles, tenant from identity, approvals, audit

## Decision
Agents, people and integrations call tools through `Gateway.call`. Roles (`config/rbac.yml`) list the tools each principal may call; agents get the narrowest role. A tool with a `tenant` argument gets the caller's tenant, and a different one is denied and logged. Tools that leave the company or override data (`send_carrier_email`, `override_mapping`) wait for a person other than the requester. Every call, denial and decision is appended to a hash-chained audit log, persisted to PostgreSQL. The HTTP API, the MCP server and the Claude Agent SDK runtime all use the same gateway.

## Consequences
A question cannot reach another tenant's data or change data, whatever the model writes into a tool call (ablation `no_tenant_scope`: 50 leaks). Approval adds a person's minute per carrier email; without it, emails with promises nobody approved go out (ablation `no_approvals`).
