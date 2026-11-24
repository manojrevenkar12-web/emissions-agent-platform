"""The HTTP API. The caller's role and tenant come from the API key; every data access goes through the
platform's gateway, so the same RBAC, tenant scoping, approvals and audit apply to people, agents and
integrations.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import numpy as np
from fastapi import Depends, FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field

from .. import config
from ..domain import CarrierRecord, EmailDraft, FileView, Mapping, ParsedReply, Question
from ..platform.governance import Denied, Principal
from ..platform.local_model import LocalModel
from ..platform.orchestrator import Platform, Switches
from ..platform.telemetry import Recorder
from .otel import setup
from .store import Store

DEMO = config.ROOT / "data" / "demo"


class DeskQueue:
    """People in the service: flagged decisions become review tasks; nothing is decided for them."""

    def __init__(self) -> None:
        self.tasks: list[dict[str, Any]] = []
        self._last: dict[str, Mapping] = {}

    def review_mapping(self, view: FileView, proposal: Mapping, flagged: list[str]) -> Mapping:
        self.tasks.append({"file_id": view.file_id, "kind": "mapping", "decisions": list(flagged)})
        self._last[view.file_id] = proposal
        return proposal

    def map_by_hand(self, view: FileView, sheet: Mapping | None) -> Mapping:
        self.tasks.append({"file_id": view.file_id, "kind": "map_by_hand", "decisions": []})
        return self._last.get(view.file_id) or (sheet if sheet is not None else Mapping({}, None, "kg", None, {}))

    def review_rows(self, view: FileView, rows: np.ndarray, weight_t: np.ndarray) -> np.ndarray:
        self.tasks.append({"file_id": view.file_id, "kind": "rows", "rows": [int(i) for i in rows][:50]})
        return weight_t

    def review_reply(self, ref: str, text: str, parsed: ParsedReply) -> ParsedReply:
        self.tasks.append({"ref": ref, "kind": "reply"})
        return ParsedReply(parsed.unit, {})

    def review_email(self, draft: EmailDraft, valid_ids: set[str]) -> EmailDraft:
        return draft


class Outbox:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def send(self, draft: EmailDraft, day: int, ref: str) -> None:
        self.sent.append({"to": draft.to, "carrier_id": draft.carrier_id, "ids": len(draft.shipment_ids), "ref": ref})


class FileIn(BaseModel):
    tenant: str = Field(pattern=r"^T\d+$")
    carrier_id: str
    csv: str = Field(max_length=5_000_000)
    month: int = Field(ge=0, le=11)
    day: int = Field(ge=0, le=400, default=0)


class AskIn(BaseModel):
    text: str = Field(max_length=2000)
    month: int = Field(ge=0, le=11, default=0)


class ClarifyIn(BaseModel):
    tenant: str
    month: int = Field(ge=0, le=11)
    day: int = 0


class DecisionIn(BaseModel):
    approve: bool


def load_keys() -> dict[str, Principal]:
    rows = json.loads(os.environ["EAP_KEYS_JSON"]) if os.environ.get("EAP_KEYS_JSON") else config.rbac()["demo_keys"]
    return {r["key_sha256"]: Principal(r["subject"], r["role"], r["tenant"]) for r in rows}


def create_app(platform: Platform, store: Store, keys: dict[str, Principal], desk: DeskQueue | None = None, outbox: Outbox | None = None) -> FastAPI:
    app = FastAPI(title="emissions-agent-platform", version="1.0.0")
    app.state.platform = platform
    gw = platform.gateway

    def caller(authorization: str = Header(default="")) -> Principal:
        token = authorization.removeprefix("Bearer ").strip()
        who = keys.get(hashlib.sha256(token.encode()).hexdigest()) if token else None
        if who is None:
            raise HTTPException(401, "unknown API key")
        return who

    def persist() -> None:
        store.sync_audit(gw.audit.entries)
        store.sync_approvals(gw.queue)

    def denied(e: Denied) -> HTTPException:
        persist()
        return HTTPException(403, e.reason)

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"ok": True, "files": len(platform.ledger.files)}

    @app.post("/v1/files")
    def upload(body: FileIn, who: Principal = Depends(caller), idempotency_key: str = Header(min_length=8, max_length=200)) -> dict[str, Any]:
        if who.role != "analyst":
            raise HTTPException(403, f"role {who.role} may not upload files")
        stored = store.replay(idempotency_key, who.subject)
        if stored is not None:
            return stored
        if body.carrier_id not in platform.registry:
            raise HTTPException(422, "unknown carrier")
        fid = f"{body.tenant}-{body.carrier_id}-{hashlib.sha1(body.csv.encode()).hexdigest()[:10]}"
        try:
            view = FileView.from_csv(body.csv, file_id=fid, tenant=body.tenant, carrier_id=body.carrier_id, day=body.day)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        rows = platform.process_file(view, body.month)
        o = platform.outcomes[-1]
        gw.audit.append(who, "upload_file", "ok", {"file_id": fid, "rows": view.n_rows})
        resp = {
            "file_id": fid,
            "rows": view.n_rows,
            "t_co2e": round(float(rows.e_kg.sum()) / 1000, 3),
            "status": "needs_review" if (o.reviewed or o.held_rows) else "ready",
            "failed_checks": o.checks,
            "review": o.reviewed,
            "held_rows": o.held_rows,
            "memory_hit": o.memory_hit,
            "mapping": o.mapping.to_dict(),
        }
        persist()
        return store.remember(idempotency_key, who.subject, resp)

    @app.get("/v1/emissions")
    def emissions(
        month: int, metric: str = "total", mode: str | None = None, origin: str | None = None, destination: str | None = None, tenant: str | None = None, who: Principal = Depends(caller)
    ) -> dict[str, Any]:
        args: dict[str, Any] = {"tenant": tenant or who.tenant, "month": month, "metric": metric, "mode": mode, "origin": origin, "destination": destination}
        try:
            out = gw.call(who, "query_emissions", {k: v for k, v in args.items() if v is not None})
        except Denied as e:
            raise denied(e) from e
        persist()
        return dict(out)

    @app.post("/v1/ask")
    def ask(body: AskIn, who: Principal = Depends(caller)) -> dict[str, Any]:
        if who.role != "customer_viewer":
            raise HTTPException(403, "questions come from a customer's key")
        qid = "api-" + hashlib.sha1(f"{who.subject}|{body.text}|{body.month}".encode()).hexdigest()[:10]
        out = platform.answer(Question(qid, who.tenant, body.month, body.text), caller=Principal(f"qa_agent:{who.tenant}", "qa_agent", who.tenant))
        persist()
        return {"answer": out.text, "result": out.result, "denied": out.denied, "checked": True}

    @app.post("/v1/clarify")
    def clarify(body: ClarifyIn, who: Principal = Depends(caller)) -> dict[str, Any]:
        if who.role != "analyst":
            raise HTTPException(403, "only the desk starts carrier requests")
        n = platform.clarify(body.tenant, body.month, body.day, auto_approve=False)
        persist()
        return {"drafted": n, "pending": [a.approval_id for a in gw.queue.values() if a.status == "pending"]}

    @app.get("/v1/approvals")
    def approvals(who: Principal = Depends(caller)) -> list[dict[str, Any]]:
        try:
            ids = gw.call(who, "list_approvals", {})
        except Denied as e:
            raise denied(e) from e
        return [
            {"approval_id": i, "tool": gw.queue[i].tool, "carrier_id": gw.queue[i].args.get("carrier_id"), "to": gw.queue[i].args.get("to"), "shipments": len(gw.queue[i].args.get("shipment_ids", []))}
            for i in ids
        ]

    @app.post("/v1/approvals/{approval_id}")
    def decide(approval_id: str, body: DecisionIn, who: Principal = Depends(caller)) -> dict[str, Any]:
        try:
            a = gw.decide(approval_id, who, body.approve)
        except Denied as e:
            raise denied(e) from e
        persist()
        return {"approval_id": a.approval_id, "status": a.status, "decided_by": a.decided_by, "sent": len(outbox.sent) if outbox else None}

    @app.get("/v1/audit")
    def audit(who: Principal = Depends(caller)) -> dict[str, Any]:
        try:
            entries = gw.call(who, "read_audit", {})
        except Denied as e:
            raise denied(e) from e
        return {"verified": gw.audit.verify(), "count": gw.audit.count, "entries": entries[-100:]}

    @app.get("/v1/review-tasks")
    def tasks(who: Principal = Depends(caller)) -> list[dict[str, Any]]:
        if who.role != "analyst":
            raise HTTPException(403, "desk only")
        return desk.tasks[-200:] if desk else []

    @app.get("/metrics")
    def metrics() -> Response:
        rec = platform.rec
        lines = [
            "# TYPE eap_llm_cost_eur counter",
            f"eap_llm_cost_eur {rec.cost_eur:.6f}",
            "# TYPE eap_tokens counter",
            f'eap_tokens{{dir="in"}} {rec.tokens_in}',
            f'eap_tokens{{dir="out"}} {rec.tokens_out}',
            "# TYPE eap_span_p95_ms gauge",
        ]
        for name, s in rec.summary().items():
            lines.append(f'eap_span_p95_ms{{span="{name}"}} {s["p95_ms"]:.1f}')
            lines.append(f'eap_span_count{{span="{name}"}} {s["count"]}')
        for reason, n in gw.denials.items():
            lines.append(f'eap_denials{{reason="{reason}"}} {n}')
        lines.append(f"eap_approvals_pending {sum(1 for a in gw.queue.values() if a.status == 'pending')}")
        lines.append(f"eap_quality_alarms {len(platform.monitor.alarms)}")
        first = [o for o in platform.outcomes if o.reads]
        lines.append(f"eap_first_read_fail_rate {sum(o.first_failed for o in first) / max(1, len(first)):.4f}")
        return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")

    return app


def demo_registry() -> dict[str, CarrierRecord]:
    rows = json.loads((DEMO / "registry.json").read_text(encoding="utf-8"))
    return {r["carrier_id"]: CarrierRecord(**r) for r in rows}


def create_demo_app(db_url: str | None = None, load_files: bool = True) -> FastAPI:
    cfg = config.platform()
    model: Any
    if os.environ.get("EAP_MODEL") == "claude":
        from ..platform.claude_model import ClaudeModel

        model = ClaudeModel(cfg)
        routing = cfg["routing"]
    else:
        model = LocalModel()
        routing = {k: "local" for k in cfg["routing"]}
    cfg = {**cfg, "routing": routing}
    export, _ = setup()
    rec = Recorder(exporter=export)
    desk, outbox = DeskQueue(), Outbox()
    plat = Platform(cfg, config.rbac(), demo_registry(), model, desk, outbox, Switches(), recorder=rec)
    store = Store(db_url or os.environ.get("EAP_DATABASE_URL", "sqlite+pysqlite:///:memory:"))
    if load_files:
        for path in sorted((DEMO / "files").glob("*.csv")):
            tenant, carrier, month = path.stem.split("__")
            view = FileView.from_csv(path.read_text(encoding="utf-8"), file_id=path.stem, tenant=tenant, carrier_id=carrier, day=int(month) * 30)
            plat.process_file(view, int(month))
    return create_app(plat, store, load_keys(), desk, outbox)
