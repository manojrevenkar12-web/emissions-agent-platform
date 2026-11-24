"""Durable state for the service: idempotency keys, the audit chain and approvals. SQLAlchemy Core, so the
same code runs on SQLite (tests, local) and PostgreSQL (Azure Database for PostgreSQL)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import JSON, Column, Integer, MetaData, String, Table, Text, create_engine, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

meta = MetaData()
idempotency = Table("idempotency", meta, Column("key", String(200), primary_key=True), Column("principal", String(200), nullable=False), Column("response", Text, nullable=False))
audit = Table(
    "audit", meta, Column("n", Integer, primary_key=True), Column("hash", String(64), nullable=False, unique=True), Column("prev", String(64), nullable=False), Column("body", JSON, nullable=False)
)
approvals = Table(
    "approvals",
    meta,
    Column("approval_id", String(40), primary_key=True),
    Column("tool", String(80), nullable=False),
    Column("status", String(20), nullable=False),
    Column("requested_by", String(200)),
    Column("decided_by", String(200)),
    Column("args", JSON),
)


class Store:
    def __init__(self, url: str = "sqlite+pysqlite:///:memory:") -> None:
        if url.startswith("sqlite") and ":memory:" in url:
            # one shared connection, or every connection gets its own empty database
            self.engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
        else:
            self.engine = create_engine(url, pool_pre_ping=True)
        meta.create_all(self.engine)
        self._audit_n = 0

    def replay(self, key: str, principal: str) -> dict[str, Any] | None:
        with self.engine.connect() as c:
            row = c.execute(select(idempotency).where(idempotency.c.key == key)).first()
        if row is None:
            return None
        if row.principal != principal:
            raise PermissionError("idempotency key belongs to another caller")
        return dict(json.loads(row.response))

    def remember(self, key: str, principal: str, response: dict[str, Any]) -> dict[str, Any]:
        try:
            with self.engine.begin() as c:
                c.execute(insert(idempotency).values(key=key, principal=principal, response=json.dumps(response, default=str)))
        except IntegrityError:
            stored = self.replay(key, principal)
            assert stored is not None
            return stored
        return response

    def sync_audit(self, entries: list[dict[str, Any]]) -> int:
        new = [e for e in entries if e["n"] > self._audit_n]
        if not new:
            return 0
        with self.engine.begin() as c:
            for e in new:
                c.execute(insert(audit).values(n=e["n"], hash=e["hash"], prev=e["prev"], body=e))
        self._audit_n = new[-1]["n"]
        return len(new)

    def sync_approvals(self, queue: dict[str, Any]) -> None:
        with self.engine.begin() as c:
            for a in queue.values():
                c.execute(approvals.delete().where(approvals.c.approval_id == a.approval_id))
                c.execute(
                    insert(approvals).values(
                        approval_id=a.approval_id, tool=a.tool, status=a.status, requested_by=a.requested_by.subject, decided_by=a.decided_by, args=json.loads(json.dumps(a.args, default=str))
                    )
                )

    def audit_rows(self) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            return [dict(r.body) for r in c.execute(select(audit).order_by(audit.c.n))]
