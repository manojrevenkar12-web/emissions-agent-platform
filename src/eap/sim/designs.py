"""Runs one design over one simulated quarter.

The world provides the model, the people, the carriers' mailboxes and the files; the design decides what to
do with them. Status quo is people with spreadsheets; model_alone and every platform variant run through
the same Platform class with different switches, so a difference comes from a switch and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .. import config
from ..domain import ROAD, CarrierRecord
from ..platform.calc import Ledger, calculate
from ..platform.checks import apply_mapping
from ..platform.governance import AuditLog
from ..platform.orchestrator import AnswerOutcome, Counters, FileOutcome, Platform, Switches
from ..platform.profile import fingerprint
from ..platform.telemetry import Recorder
from ..world.carriers import Mailbox
from ..world.luck import Luck
from ..world.model_sim import ReplyBook, SimModel
from ..world.people import Desk
from ..world.world import World

MANUAL_MINUTES = {"new_format": 30.0, "known_format": 6.0, "email": 12.0, "reply": 6.0, "answer": 8.0}
STATUS_QUO_CARRIERS_PER_MONTH = 4


@dataclass
class QA:
    q_id: str
    tenant: str
    kind: str
    shown: float | None
    expected: float | None
    used_tenant: str | None
    used_month: int | None
    params_match: bool
    writes: int
    fallback: bool
    latency_ms: float
    text: str


@dataclass
class DesignRun:
    name: str
    kind: str
    ledger: Ledger
    minutes: list[tuple[str, int, float, str]]
    recorder: Recorder
    outcomes: list[FileOutcome]
    qa: list[QA]
    mailbox: Mailbox
    counters: Counters
    audit: AuditLog
    luck: Luck
    monitor: dict[str, Any] = field(default_factory=dict)


def _months_end(weeks: int) -> list[int]:
    return [30, 60, max(90, weeks * 7)]


def _qa_row(world_q: Any, out: AnswerOutcome | None, shown: float | None, expected: float | None, platform_ledger: Ledger) -> QA:
    q = world_q.question
    used = out.args if out else None
    params_match = True
    if used is not None:
        params_match = int(used.get("month", -1)) == int(world_q.params["month"])
        if world_q.kind == "by_mode":
            params_match &= used.get("mode") == world_q.params["mode"]
        if world_q.kind == "lane":
            params_match &= [used.get("origin"), used.get("destination")] == list(world_q.params["lane"])
    return QA(
        q.q_id,
        q.tenant,
        world_q.kind,
        shown,
        expected,
        used.get("tenant") if used else None,
        int(used["month"]) if used else None,
        bool(params_match),
        out.writes_done if out else 0,
        out.fallback if out else False,
        out.latency_ms if out else 0.0,
        out.text if out else "",
    )


def _shown_number(out: AnswerOutcome) -> float | None:
    from ..platform.guard import numbers_in

    if out.result is None:
        return None
    nums = [n for n in numbers_in(out.text) if not (1900 <= n <= 2100)]
    return nums[0] if nums else None


def _expected(ledger: Ledger, kind: str, tenant: str, params: dict[str, Any]) -> float | None:
    m = int(params["month"])
    if kind in ("total", "injected"):
        return float(ledger.query(tenant, m, "total")["value"])
    if kind == "by_mode":
        return float(ledger.query(tenant, m, "by_mode", mode=params["mode"])["value"])
    if kind == "lane":
        o, d = params["lane"]
        return float(ledger.query(tenant, m, "lane", origin=o, destination=d)["value"])
    if kind == "primary_share":
        return float(ledger.query(tenant, m, "primary_share")["value"])
    return None


def run_platform(world: World, name: str, switches: Switches, cfg: dict[str, Any], *, model_override: dict[str, str] | None = None, keep_traces: set[str] | None = None) -> DesignRun:
    luck = Luck(world.seed, world.variant)
    book = ReplyBook()
    model = SimModel(world, luck, book)
    desk = Desk(world, luck, book)
    mail = Mailbox(world, luck, book)
    rec = Recorder(keep_traces=keep_traces or set())
    registry: dict[str, CarrierRecord] = world.registry()
    plat = Platform(cfg, config.rbac(), registry, model, desk, mail, switches, model_override=model_override, recorder=rec, keep_audit=bool(keep_traces), tenant_names=world.tenant_names)
    invent = world.cfg["models"][plat.routing["first"]]["invent_fill"]
    by_day: dict[int, list[Any]] = {}
    for f in world.files:
        by_day.setdefault(f.day, []).append(f)
    ends = _months_end(int(world.cfg["weeks"]))
    last = ends[-1] + 25
    for day in range(last + 1):
        for f in by_day.get(day, []):
            rows = plat.process_file(f.view, f.month)
            if not switches.never_invent:
                guess = np.exp(luck.rows(len(rows.ids), "invent", f.file_id) * 0.6 - 0.3)
                plat.invent_missing(rows, luck.u("invent_file", f.file_id) < invent, guess)
        for rep in [r for r in mail.inbox if r.day == day]:
            plat.ingest_reply(rep.ref, rep.tenant, rep.carrier_id, day, rep.text)
        if day in ends:
            month = ends.index(day)
            for t in world.tenants:
                plat.clarify(t, month, day)
    plat.monitor.close_through(last)
    qa: list[QA] = []
    for a in world.questions:
        out = plat.answer(a.question)
        exp = _expected(plat.ledger, a.kind, a.question.tenant, a.params)
        qa.append(_qa_row(a, out, _shown_number(out), exp, plat.ledger))
    mon = {"alarms": plat.monitor.alarms, "series": plat.monitor.series}
    return DesignRun(name, "platform", plat.ledger, plat.minutes, rec, plat.outcomes, qa, mail, plat.counters, plat.gateway.audit, luck, mon)


def run_status_quo(world: World, name: str, cfg: dict[str, Any]) -> DesignRun:
    luck = Luck(world.seed, world.variant)
    book = ReplyBook()
    desk = Desk(world, luck, book)
    mail = Mailbox(world, luck, book)
    ledger = Ledger()
    minutes: list[tuple[str, int, float, str]] = []
    sheets: dict[str, Any] = {}
    outcomes: list[FileOutcome] = []
    registry = world.registry()
    by_day: dict[int, list[Any]] = {}
    for f in world.files:
        by_day.setdefault(f.day, []).append(f)
    ends = _months_end(int(world.cfg["weeks"]))
    last = ends[-1] + 25
    asked: dict[str, set[str]] = {}
    counters = Counters()
    for day in range(last + 1):
        for f in by_day.get(day, []):
            fp = fingerprint(f.view.headers)
            sheet = sheets.get(fp)
            m = desk.map_by_hand(f.view, sheet)
            mins = MANUAL_MINUTES["known_format"] if (sheet is not None and m is sheet) else MANUAL_MINUTES["new_format"]
            sheets[fp] = m
            p = apply_mapping(f.view, m, cfg["factors"])
            rows = calculate(f.file_id, f.tenant, f.carrier_id, f.month, f.day, p, cfg, bool(m.columns.get("fuel")))
            ledger.add(rows)
            minutes.append((f.tenant, f.day, mins, "map_by_hand"))
            outcomes.append(FileOutcome(f.file_id, 0, False, m is sheet, [], False, False, 0, mins, 0.0, m, {}))
        for rep in [r for r in mail.inbox if r.day == day]:
            rt = book.replies[rep.ref]
            fixed = desk.review_reply(rep.ref, rep.text, _parsed(rt))
            litres = {k: v * (3.785 if fixed.unit == "gal" else 1.0) for k, v in fixed.values.items() if k in asked.get(f"{rep.tenant}|{rep.carrier_id}", set())}
            done, _ = ledger.set_primary(rep.tenant, rep.carrier_id, litres, cfg, "reply", check=False)
            counters.replies += 1
            counters.reply_rows_primary += done
            minutes.append((rep.tenant, day, MANUAL_MINUTES["reply"], "reply"))
        if day in ends:
            month = ends.index(day)
            for t in world.tenants:
                cands = []
                for cid in world.tenant_carriers[t]:
                    if registry[cid].kind in ("road", "multimodal"):
                        miss = ledger.missing_fuel(t, cid, month)
                        cands.append((len(miss), cid, miss))
                for n, cid, miss in sorted(cands, reverse=True)[:STATUS_QUO_CARRIERS_PER_MONTH]:
                    if n == 0:
                        continue
                    from ..domain import EmailDraft

                    body = "Dear team,\nplease send the fuel used per shipment:\n" + "\n".join(miss)
                    mail.send(EmailDraft(cid, registry[cid].contact, "Fuel data", body, miss), day, f"{t}|{cid}|m{month}")
                    asked.setdefault(f"{t}|{cid}", set()).update(miss)
                    counters.emails_sent += 1
                    minutes.append((t, day, MANUAL_MINUTES["email"], "email"))
    qa: list[QA] = []
    for a in world.questions:
        q = a.question
        exp = _expected(ledger, a.kind, q.tenant, a.params)
        shown = desk.answer_by_hand(q.q_id, exp) if exp is not None else None
        minutes.append((q.tenant, 120, MANUAL_MINUTES["answer"], "answer"))
        qa.append(QA(q.q_id, q.tenant, a.kind, shown, exp, q.tenant if exp is not None else None, int(a.params["month"]), True, 0, False, 0.0, ""))
    return DesignRun(name, "manual", ledger, minutes, Recorder(), outcomes, qa, mail, counters, AuditLog(keep=False), luck)


def _parsed(rt: Any) -> Any:
    from ..domain import ParsedReply

    return ParsedReply(rt.unit, dict(rt.values))


def run_design(world: World, name: str, d: dict[str, Any], cfg: dict[str, Any], *, model_override: dict[str, str] | None = None, keep_traces: set[str] | None = None) -> DesignRun:
    if d["kind"] == "manual":
        return run_status_quo(world, name, cfg)
    if d["kind"] == "model_alone":
        run = run_platform(world, name, Switches.model_alone(), _single_model(cfg, d.get("model", "balanced")), keep_traces=keep_traces)
        run.kind = "model_alone"
        return run
    return run_platform(world, name, Switches.platform(d.get("without")), cfg, model_override=model_override, keep_traces=keep_traces)


def _single_model(cfg: dict[str, Any], model: str) -> dict[str, Any]:
    out = dict(cfg)
    out["routing"] = {k: model for k in cfg["routing"]}
    return out


__all__ = ["DesignRun", "QA", "run_design", "ROAD"]
