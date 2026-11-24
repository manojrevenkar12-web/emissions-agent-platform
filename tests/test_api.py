"""The HTTP API: keys decide role and tenant; approvals, idempotency and audit."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eap.service.api import create_demo_app

T1, T2, ANNA, BEN, ADMIN = "demo-viewer-t1", "demo-viewer-t2", "demo-analyst-anna", "demo-analyst-ben", "demo-admin"


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_demo_app())


def h(key: str, **extra: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}", **extra}


def test_unknown_keys_are_refused(client) -> None:
    assert client.get("/v1/emissions?month=0", headers=h("nope")).status_code == 401


def test_a_customer_sees_its_own_emissions_and_not_another_tenants(client) -> None:
    r = client.get("/v1/emissions?month=0", headers=h(T1))
    assert r.status_code == 200 and r.json()["value"] > 0
    assert client.get("/v1/emissions?month=0&tenant=T2", headers=h(T1)).status_code == 403


def test_questions_are_answered_with_the_tools_number(client) -> None:
    r = client.post("/v1/ask", json={"text": "What were our total transport emissions in January?", "month": 0}, headers=h(T1)).json()
    total = client.get("/v1/emissions?month=0", headers=h(T1)).json()["value"]
    assert f"{total:,.1f}" in r["answer"]


def test_an_upload_is_idempotent(client) -> None:
    csv = "Sendungsnummer,Von,Nach,Gewicht (kg),Verkehrsträger,Datum\n" + "".join(f"SHX{i:03d},DEHAM,DEBER,{9000 + i},FTL,05.01.2026\n" for i in range(20))
    carrier = next(iter(client.app.state.platform.registry))
    body = {"tenant": "T1", "carrier_id": carrier, "csv": csv, "month": 1}
    a = client.post("/v1/files", json=body, headers=h(ANNA, **{"Idempotency-Key": "upload-0001"}))
    b = client.post("/v1/files", json=body, headers=h(ANNA, **{"Idempotency-Key": "upload-0001"}))
    assert a.status_code == 200 and a.json() == b.json()
    assert client.post("/v1/files", json=body, headers=h(T1, **{"Idempotency-Key": "upload-0002"})).status_code == 403


def test_carrier_requests_wait_for_a_person(client) -> None:
    r = client.post("/v1/clarify", json={"tenant": "T1", "month": 0, "day": 30}, headers=h(ANNA)).json()
    pending = r["pending"]
    if not pending:
        pytest.skip("no carrier in the demo data has enough road shipments without fuel")
    assert client.post(f"/v1/approvals/{pending[0]}", json={"approve": True}, headers=h(T1)).status_code == 403
    ok = client.post(f"/v1/approvals/{pending[0]}", json={"approve": True}, headers=h(BEN)).json()
    assert ok["status"] == "approved" and ok["sent"] >= 1


def test_the_audit_is_for_admins_and_verifies(client) -> None:
    assert client.get("/v1/audit", headers=h(T1)).status_code == 403
    r = client.get("/v1/audit", headers=h(ADMIN)).json()
    assert r["verified"] and r["count"] > 0
    assert "eap_tokens" in client.get("/metrics").text
