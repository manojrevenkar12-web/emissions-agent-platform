"""Security and governance for agent tool calls: who may call what, for which tenant, with whose approval,
and a tamper-evident record of every call.

Every tool call from every agent and every API client goes through `Gateway.call`. The tenant comes from the
caller's identity, never from the tool arguments a model wrote. Tools that change data or leave the company
wait in the approval queue until a person other than the requester approves them.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Principal:
    subject: str
    role: str
    tenant: str  # "*" for desk staff who serve every tenant


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    risk: str  # read | write | external
    schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Any]


class Denied(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class Pending:
    approval_id: str
    tool: str


@dataclass
class AuditLog:
    """Append-only, hash-chained: each entry commits to the one before it."""

    entries: list[dict[str, Any]] = field(default_factory=list)
    keep: bool = True
    count: int = 0
    _last: str = "0" * 64

    def append(self, actor: Principal, action: str, outcome: str, detail: dict[str, Any]) -> str:
        self.count += 1
        body = {"n": self.count, "actor": actor.subject, "role": actor.role, "tenant": actor.tenant, "action": action, "outcome": outcome, "detail": detail, "prev": self._last}
        digest = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
        self._last = digest
        if self.keep:
            self.entries.append({**body, "hash": digest})
        return digest

    def verify(self) -> bool:
        prev = "0" * 64
        for e in self.entries:
            body = {k: v for k, v in e.items() if k != "hash"}
            if body["prev"] != prev:
                return False
            if hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest() != e["hash"]:
                return False
            prev = e["hash"]
        return True


@dataclass
class Approval:
    approval_id: str
    tool: str
    args: dict[str, Any]
    requested_by: Principal
    status: str = "pending"  # pending | approved | rejected
    decided_by: str | None = None
    result: Any = None


class Gateway:
    def __init__(self, rbac: dict[str, Any], approvals_cfg: dict[str, Any], *, tenant_scope: bool = True, approvals: bool = True, audit: AuditLog | None = None) -> None:
        self.roles: dict[str, set[str]] = {r: set(t) for r, t in rbac["roles"].items()}
        self.needs_approval = set(approvals_cfg["required_for"]) if approvals else set()
        self.tenant_scope = tenant_scope
        self.tools: dict[str, Tool] = {}
        self.audit = audit or AuditLog()
        self.queue: dict[str, Approval] = {}
        self.denials: dict[str, int] = {}

    def register(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def _deny(self, who: Principal, name: str, reason: str) -> Denied:
        self.denials[reason] = self.denials.get(reason, 0) + 1
        self.audit.append(who, name, "denied", {"reason": reason})
        return Denied(reason)

    def allowed(self, who: Principal) -> list[str]:
        return sorted(n for n in self.tools if n in self.roles.get(who.role, set()))

    def call(self, who: Principal, name: str, args: dict[str, Any]) -> Any:
        tool = self.tools.get(name)
        if tool is None:
            raise self._deny(who, name, "unknown tool")
        if name not in self.roles.get(who.role, set()):
            raise self._deny(who, name, f"role {who.role} may not call {name}")
        args = dict(args)
        if "tenant" in tool.schema.get("properties", {}):
            asked = args.get("tenant", who.tenant)
            if self.tenant_scope:
                if who.tenant != "*" and asked != who.tenant:
                    raise self._deny(who, name, "cross-tenant")
                if who.tenant != "*":
                    args["tenant"] = who.tenant
        for req in tool.schema.get("required", []):
            if req not in args:
                raise self._deny(who, name, f"missing {req}")
        if name in self.needs_approval:
            aid = hashlib.sha1(json.dumps([name, args, who.subject], sort_keys=True, default=str).encode()).hexdigest()[:12]
            if aid not in self.queue:
                self.queue[aid] = Approval(aid, name, args, who)
                self.audit.append(who, name, "queued", {"approval": aid})
            return Pending(aid, name)
        result = tool.handler(args)
        self.audit.append(who, name, "ok", {"args": _digest(args)})
        return result

    def decide(self, approval_id: str, who: Principal, approve: bool) -> Approval:
        a = self.queue.get(approval_id)
        if a is None:
            raise self._deny(who, "approve", "unknown approval")
        if "approve" not in self.roles.get(who.role, set()):
            raise self._deny(who, "approve", f"role {who.role} may not approve")
        if who.subject == a.requested_by.subject:
            raise self._deny(who, "approve", "requester cannot approve")
        if who.tenant not in ("*", a.requested_by.tenant):
            raise self._deny(who, "approve", "cross-tenant")
        if a.status != "pending":
            return a  # deciding twice changes nothing
        if approve:
            a.result = self.tools[a.tool].handler(a.args)
            a.status = "approved"
        else:
            a.status = "rejected"
        a.decided_by = who.subject
        self.audit.append(who, f"decide:{a.tool}", a.status, {"approval": approval_id})
        return a


def _digest(args: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()[:16]
