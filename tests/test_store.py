"""The service store on SQLite here and on PostgreSQL in CI (EAP_TEST_DATABASE_URL)."""

from __future__ import annotations

import os
import uuid

import pytest

from eap.platform.governance import AuditLog, Principal
from eap.service.store import Store


@pytest.fixture
def store() -> Store:
    return Store(os.environ.get("EAP_TEST_DATABASE_URL", "sqlite+pysqlite:///:memory:"))


def test_an_idempotency_key_returns_the_first_response(store) -> None:
    key = f"k-{uuid.uuid4()}"
    assert store.replay(key, "anna") is None
    store.remember(key, "anna", {"file_id": "f1"})
    assert store.remember(key, "anna", {"file_id": "f2"}) == {"file_id": "f1"}
    with pytest.raises(PermissionError):
        store.replay(key, "ben")


def test_the_audit_chain_is_persisted_once(store) -> None:
    log = AuditLog()
    who = Principal("x", "analyst", "*")
    for i in range(3):
        log.append(who, "query", "ok", {"i": i, "run": str(uuid.uuid4())})
    store._audit_n = 0
    rows_before = len(store.audit_rows())
    assert store.sync_audit(log.entries) == 3
    assert store.sync_audit(log.entries) == 0
    assert len(store.audit_rows()) == rows_before + 3
