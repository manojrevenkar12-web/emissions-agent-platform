"""Security and governance: roles, tenant scope, approvals, audit."""

from __future__ import annotations

import pytest

from eap import config
from eap.platform.governance import AuditLog, Denied, Gateway, Pending, Principal, Tool


def _gw(**kw):
    g = Gateway(config.rbac(), config.platform()["approvals"], **kw)
    sent = []
    g.register(
        Tool("query_emissions", "q", "read", {"type": "object", "properties": {"tenant": {}, "month": {}, "metric": {}}, "required": ["tenant", "month", "metric"]}, lambda a: {"tenant": a["tenant"]})
    )
    g.register(
        Tool(
            "send_carrier_email",
            "s",
            "external",
            {"type": "object", "properties": {"tenant": {}, "to": {}, "carrier_id": {}, "body": {}}, "required": ["tenant", "to", "carrier_id", "body"]},
            lambda a: sent.append(a) or True,
        )
    )
    return g, sent


def test_the_tenant_comes_from_the_caller_not_the_arguments() -> None:
    g, _ = _gw()
    viewer = Principal("v", "customer_viewer", "T1")
    assert g.call(viewer, "query_emissions", {"month": 0, "metric": "total"}) == {"tenant": "T1"}
    with pytest.raises(Denied, match="cross-tenant"):
        g.call(viewer, "query_emissions", {"tenant": "T2", "month": 0, "metric": "total"})


def test_without_scope_the_model_picks_the_tenant() -> None:
    g, _ = _gw(tenant_scope=False)
    assert g.call(Principal("v", "customer_viewer", "T1"), "query_emissions", {"tenant": "T2", "month": 0, "metric": "total"}) == {"tenant": "T2"}


def test_a_role_cannot_call_tools_outside_it() -> None:
    g, _ = _gw()
    with pytest.raises(Denied, match="may not call"):
        g.call(Principal("q", "qa_agent", "T1"), "send_carrier_email", {"to": "x", "carrier_id": "c", "body": "b"})


def test_external_email_waits_for_a_person_who_is_not_the_requester() -> None:
    g, sent = _gw()
    agent = Principal("clarification_agent:T1", "clarification_agent", "T1")
    out = g.call(agent, "send_carrier_email", {"to": "a@b", "carrier_id": "c", "body": "hi"})
    assert isinstance(out, Pending) and not sent
    with pytest.raises(Denied, match="may not approve"):
        g.decide(out.approval_id, agent, True)
    desk = Principal("anna@desk", "analyst", "*")
    assert g.decide(out.approval_id, desk, True).status == "approved"
    assert g.decide(out.approval_id, Principal("ben@desk", "analyst", "*"), True).decided_by == "anna@desk"
    assert len(sent) == 1, "deciding twice sends once"


def test_the_requester_cannot_approve_their_own_request() -> None:
    g, _ = _gw()
    anna = Principal("anna@desk", "analyst", "*")
    g.roles["analyst"].add("send_carrier_email")
    out = g.call(anna, "send_carrier_email", {"tenant": "T1", "to": "a@b", "carrier_id": "c", "body": "hi"})
    with pytest.raises(Denied, match="requester"):
        g.decide(out.approval_id, anna, True)


def test_the_audit_chain_detects_a_changed_entry() -> None:
    log = AuditLog()
    who = Principal("x", "analyst", "*")
    for i in range(5):
        log.append(who, "query", "ok", {"i": i})
    assert log.verify()
    log.entries[2]["detail"]["i"] = 99
    assert not log.verify()
