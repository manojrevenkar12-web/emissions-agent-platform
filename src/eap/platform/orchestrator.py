"""The supervisor that runs the three agents on the platform.

Mapping agent: profile -> memory -> first read (small model) -> code checks -> second read (mid model) ->
person for the decisions code rejects or the model doubts -> calculation.
Clarification agent: ask carriers for fuel data on road shipments that only have defaults; the recipient
comes from the carrier registry, unknown shipment ids are dropped by code, a person approves the email.
Replies are fenced, parsed by a model, then checked by code before any number becomes primary data.
Q&A agent: plans a tool call; the gateway fixes the tenant from the caller; code checks the answer's number.

Every safeguard has a switch so the study can turn it off alone (config/designs.yml). The defaults are the
platform as designed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..domain import ROAD, CarrierRecord, EmailDraft, FileView, Mapping, ModelReply, Question
from . import prompts
from .calc import FileRows, Ledger, calculate, default_kg
from .checks import CheckResult, Parsed, apply_mapping, check_mapping, low_confidence
from .governance import AuditLog, Denied, Gateway, Pending, Principal, Tool
from .guard import answer_matches, contradicts, fence, looks_like_instruction, question_slots
from .monitor import Cusum
from .ports import MailPort, ModelPort, PeoplePort
from .profile import build_profile, fingerprint, signature, signature_drift
from .telemetry import Recorder, Span, cost

L_PER_GAL = 3.785


@dataclass
class Switches:
    checks: bool = True
    memory: bool = True
    router: bool = True
    approvals: bool = True
    tenant_scope: bool = True
    answer_check: bool = True
    reply_checks: bool = True
    monitor: bool = True
    clarification: bool = True
    # what separates the platform from one agent with all tools
    profile: bool = True  # context = a profile, not the whole file
    dedupe: bool = True
    registry_recipient: bool = True
    strip_unknown_ids: bool = True
    never_invent: bool = True
    scoped_role: bool = True
    fence: bool = True
    people_review: bool = True

    @classmethod
    def platform(cls, off: list[str] | None = None) -> Switches:
        s = cls()
        for name in off or []:
            if not hasattr(s, name):
                raise ValueError(f"unknown switch {name}")
            setattr(s, name, False)
        return s

    @classmethod
    def model_alone(cls) -> Switches:
        """One agent with every tool and the whole file in context. It still asks carriers for data."""
        s = cls(**{k: False for k in cls.__dataclass_fields__})
        s.clarification = True
        return s


@dataclass
class FileOutcome:
    file_id: str
    reads: int
    escalated: bool
    memory_hit: bool
    reviewed: list[str]
    first_failed: bool
    accepted_failing: bool
    held_rows: int
    minutes: float
    latency_ms: float
    mapping: Mapping
    checks: dict[str, str]
    first: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnswerOutcome:
    q_id: str
    text: str
    result: dict[str, Any] | None
    args: dict[str, Any] | None
    denied: list[str]
    writes_done: int
    fallback: bool
    latency_ms: float


@dataclass
class Counters:
    emails_sent: int = 0
    emails_unapproved: int = 0
    replies: int = 0
    replies_flagged: int = 0
    reply_rows_primary: int = 0
    reply_rows_refused: int = 0
    invented_rows: int = 0
    write_attempts_blocked: int = 0
    cross_tenant_denied: int = 0


UNIT_MARK = re.compile(r"\((kg|t|lb|lbs|km|mi|miles|l|gal)\)|\b(kg|km|miles|tonnes|litres)\b", re.IGNORECASE)


def unstated_units(m: Mapping) -> list[str]:
    out = []
    for fld, key in (("weight", "unit:weight"), ("distance", "unit:distance")):
        h = m.columns.get(fld)
        if h and not UNIT_MARK.search(h):
            out.append(key)
    return out


class Platform:
    def __init__(
        self,
        cfg: dict[str, Any],
        rbac: dict[str, Any],
        registry: dict[str, CarrierRecord],
        model: ModelPort,
        people: PeoplePort,
        mail: MailPort,
        switches: Switches | None = None,
        *,
        model_override: dict[str, str] | None = None,
        recorder: Recorder | None = None,
        keep_audit: bool = True,
        tenant_names: dict[str, str] | None = None,
    ) -> None:
        self.cfg = cfg
        self.sw = switches or Switches()
        self.registry = registry
        self.model = model
        self.people = people
        self.mail = mail
        self.rec = recorder or Recorder()
        self.prices = cfg["prices_eur_per_mtok"]
        routing = dict(cfg["routing"])
        if not self.sw.router:
            routing = {k: routing["escalate"] for k in routing}
        for slot, name in (model_override or {}).items():
            routing = {k: (name if v == slot else v) for k, v in routing.items()}
        self.routing = routing
        self.ledger = Ledger()
        self.memory: dict[str, tuple[Mapping, dict[str, float]]] = {}
        self.monitor = Cusum.from_cfg(cfg)
        self.minutes: list[tuple[str, int, float, str]] = []  # (tenant, day, minutes, what)
        self.counters = Counters()
        self.outcomes: list[FileOutcome] = []
        self.answers: list[AnswerOutcome] = []
        self.requested: dict[str, set[str]] = {}
        self.tenant_names = tenant_names or {}
        self.gateway = Gateway(rbac, cfg["approvals"], tenant_scope=self.sw.tenant_scope, approvals=self.sw.approvals, audit=AuditLog(keep=keep_audit))
        self._register_tools()
        if not self.sw.scoped_role:
            # one agent with every tool: what the platform's roles exist to prevent
            self.gateway.roles["superagent"] = set(self.gateway.tools)

    # ------------------------------------------------------------------ tools
    def _register_tools(self) -> None:
        t = {"type": "string"}
        g = self.gateway
        g.register(
            Tool(
                "query_emissions",
                "Emissions for one tenant and month: total, by_mode, lane or primary_share",
                "read",
                {"type": "object", "properties": {"tenant": t, "month": {"type": "integer"}, "metric": t, "mode": t, "origin": t, "destination": t}, "required": ["tenant", "month", "metric"]},
                self._query,
            )
        )
        g.register(
            Tool(
                "update_shipments",
                "Change the mode of a tenant's shipments",
                "write",
                {"type": "object", "properties": {"tenant": t, "month": {"type": "integer"}, "where_mode": t, "set_mode": t}, "required": ["tenant", "month", "where_mode", "set_mode"]},
                self._update,
            )
        )
        g.register(
            Tool(
                "send_carrier_email",
                "Send a data request to a carrier",
                "external",
                {
                    "type": "object",
                    "properties": {"tenant": t, "carrier_id": t, "to": t, "subject": t, "body": t, "shipment_ids": {"type": "array"}, "day": {"type": "integer"}, "ref": t},
                    "required": ["tenant", "carrier_id", "to", "body"],
                },
                self._send,
            )
        )
        g.register(
            Tool(
                "set_primary_data",
                "Use measured fuel for shipments",
                "write",
                {"type": "object", "properties": {"tenant": t, "carrier_id": t, "litres": {"type": "object"}, "check": {"type": "boolean"}}, "required": ["tenant", "carrier_id", "litres"]},
                self._set_primary,
            )
        )
        g.register(
            Tool(
                "list_missing_fuel",
                "Road shipments of a carrier in a month without primary data",
                "read",
                {"type": "object", "properties": {"tenant": t, "carrier_id": t, "month": {"type": "integer"}}, "required": ["tenant", "carrier_id", "month"]},
                lambda a: self.ledger.missing_fuel(a["tenant"], a["carrier_id"], a["month"]),
            )
        )
        g.register(Tool("read_audit", "The audit log", "read", {"type": "object", "properties": {}}, lambda a: self.gateway.audit.entries[-200:]))
        g.register(Tool("list_approvals", "Pending approvals", "read", {"type": "object", "properties": {}}, lambda a: [x.approval_id for x in self.gateway.queue.values() if x.status == "pending"]))

    def _query(self, a: dict[str, Any]) -> dict[str, Any]:
        return self.ledger.query(a["tenant"], int(a["month"]), a["metric"], a.get("mode"), a.get("origin"), a.get("destination"))

    def _update(self, a: dict[str, Any]) -> int:
        return self.ledger.update_mode(a["tenant"], int(a["month"]), a["where_mode"], a["set_mode"], self.cfg)

    def _send(self, a: dict[str, Any]) -> bool:
        draft = EmailDraft(a["carrier_id"], a["to"], a.get("subject", ""), a["body"], list(a.get("shipment_ids", [])))
        self.mail.send(draft, int(a.get("day", 0)), str(a.get("ref", "")))
        self.counters.emails_sent += 1
        return True

    def _set_primary(self, a: dict[str, Any]) -> tuple[int, int]:
        return self.ledger.set_primary(a["tenant"], a["carrier_id"], a["litres"], self.cfg, "reply", check=bool(a.get("check", True)))

    def principal(self, role: str, tenant: str) -> Principal:
        if not self.sw.scoped_role:
            return Principal(f"agent:{tenant}", "superagent", tenant)
        return Principal(f"{role}:{tenant}", role, tenant)

    # ------------------------------------------------------------------ model calls
    def _span(self, name: str, trace: str, r: ModelReply, start: float, attrs: dict[str, Any] | None = None) -> float:
        c = cost(self.prices, r.model, r.tokens_in, r.tokens_out)
        self.rec.add(Span(name, trace, start, r.latency_ms, r.model, r.tokens_in, r.tokens_out, c, "ok" if not r.retries else f"retried {r.retries}", attrs or {}))
        return r.latency_ms

    def _human(self, tenant: str, day: int, minutes: float, what: str, trace: str, start: float) -> None:
        if minutes <= 0:
            return
        self.minutes.append((tenant, day, minutes, what))
        self.rec.add(Span(f"person.{what}", trace, start, minutes * 60000, attrs={"minutes": round(minutes, 2)}))

    # ------------------------------------------------------------------ mapping agent
    def _read(self, view: FileView, prompt: str, tier: str) -> tuple[Mapping, ModelReply]:
        r = self.model.propose_mapping(view, prompt, tier)
        return r.value, r

    def _check(self, view: FileView, m: Mapping) -> tuple[Parsed, CheckResult]:
        p = apply_mapping(view, m, self.cfg["factors"])
        if not self.sw.checks:
            return p, CheckResult(holds=np.zeros(p.n, dtype=bool))
        kind = self.registry[view.carrier_id].kind
        return p, check_mapping(view, m, p, kind, self.cfg)

    def _doubts(self, m: Mapping, res: CheckResult) -> list[str]:
        return sorted(set(res.failed) | set(low_confidence(m, self.cfg)))

    def process_file(self, view: FileView, month: int) -> FileRows:
        trace = view.file_id
        t0 = 0.0
        tenant = view.tenant
        am = self.cfg["analyst_minutes"]
        fp = fingerprint(view.headers)
        reads = 0
        escalated = memory_hit = first_failed = accepted_failing = False
        reviewed: list[str] = []
        minutes = 0.0
        latency = 0.0
        mapping: Mapping | None = None
        parsed: Parsed | None = None
        first: dict[str, Any] = {}
        res = CheckResult()
        if self.sw.memory and fp in self.memory:
            cand, sig = self.memory[fp]
            mc = view.column(cand.columns.get("mode"))
            if mc is not None and set(mc.astype(str)) <= set(cand.mode_codes):
                p, rc = self._check(view, cand)
                drift = signature_drift(sig, signature(view, cand, p), self.cfg)
                self.rec.add(Span("map.memory", trace, t0, 2.0, attrs={"hit": True, "ok": rc.ok, "drift": drift or ""}))
                if rc.ok and not drift:
                    mapping, parsed, res, memory_hit = cand, p, rc, True
                else:
                    del self.memory[fp]
        if mapping is None:
            prof = build_profile(view, self.cfg)
            body = prof.text if self.sw.profile else view.to_csv()
            prompt = prompts.MAPPING + "\n" + (fence(body, trace) if self.sw.fence else body)
            pinned = self.sw.monitor and self.monitor.pinned(view.day)
            tier = self.routing["escalate"] if pinned else self.routing["first"]
            m, r = self._read(view, prompt, tier)
            reads += 1
            latency += self._span("map.read", trace, r, t0 + latency, {"tier": tier, "profile_tokens": prof.tokens if self.sw.profile else r.tokens_in})
            p, res = self._check(view, m)
            self.rec.add(Span("map.checks", trace, t0 + latency, 3.0 + view.n_rows * 0.02, attrs={"failed": len(res.failed)}))
            first_failed = not res.ok
            first = {"tier": tier, "mapping": m.to_dict(), "failed": dict(res.failed), "low_confidence": low_confidence(m, self.cfg)}
            if self.sw.monitor:
                self.monitor.observe(view.day, first_failed)
            doubts = self._doubts(m, res)
            if doubts and self.sw.router and tier != self.routing["escalate"]:
                m2, r2 = self._read(view, prompt, self.routing["escalate"])
                reads += 1
                escalated = True
                latency += self._span("map.second_read", trace, r2, t0 + latency, {"tier": self.routing["escalate"]})
                p2, res2 = self._check(view, m2)
                first["second"] = {"tier": self.routing["escalate"], "mapping": m2.to_dict(), "failed": dict(res2.failed), "low_confidence": low_confidence(m2, self.cfg)}
                if len(self._doubts(m2, res2)) <= len(doubts):
                    m, p, res, doubts = m2, p2, res2, self._doubts(m2, res2)
            if self.sw.memory and self.sw.people_review and self.cfg["memory"].get("confirm_unstated_units"):
                # a unit read from the numbers alone would be remembered for the carrier's whole export: a person
                # confirms it once (a quick look when nothing else is in doubt, part of the review otherwise)
                confirm = sorted(set(unstated_units(m)) - set(doubts))
                if confirm and not doubts:
                    m = self.people.review_mapping(view, m, confirm)
                    mins = am["confirm_unit"] * len(confirm)
                    minutes += mins
                    reviewed = confirm
                    self._human(tenant, view.day, mins, "confirm_unit", trace, t0 + latency)
                    p, res = self._check(view, m)
                    doubts = sorted(res.failed)
                else:
                    doubts = sorted(set(doubts) | set(confirm))
            if doubts and self.sw.people_review:
                reviewed = sorted(set(reviewed) | set(doubts))
                for _round in range(2):
                    m = self.people.review_mapping(view, m, doubts)
                    mins = am["review_base"] + am["review_per_decision"] * len(doubts)
                    minutes += mins
                    self._human(tenant, view.day, mins, "review_mapping", trace, t0 + latency)
                    p, res = self._check(view, m)
                    doubts = sorted(set(res.failed) - set(reviewed)) or sorted(res.failed)
                    reviewed = sorted(set(reviewed) | set(doubts))
                    if res.ok:
                        break
                if not res.ok:
                    # still failing after two looks: the desk maps the file by hand with the carrier
                    m = self.people.map_by_hand(view, None)
                    mins = am["manual_mapping"]
                    minutes += mins
                    self._human(tenant, view.day, mins, "map_by_hand", trace, t0 + latency)
                    p, res = self._check(view, m)
                accepted_failing = not res.ok
            mapping, parsed = m, p
            if self.sw.memory and (res.ok or mapping.source == "person"):
                self.memory[fp] = (mapping, signature(view, mapping, parsed))
        assert parsed is not None
        # rows a person should look at: weights outside the mode's range under a mapping that passed
        held = np.flatnonzero(res.holds) if self.sw.checks and res.ok else np.zeros(0, dtype=int)
        if len(held):
            parsed.weight_t = self.people.review_rows(view, held, parsed.weight_t)
            mins = am["row_hold"] * len(held)
            minutes += mins
            self._human(tenant, view.day, mins, "review_rows", trace, t0 + latency)
        if not self.sw.dedupe:
            parsed.dup = np.zeros(parsed.n, dtype=bool)
        fuel_ok = bool(mapping.columns.get("fuel")) and ("col:fuel" not in res.failed)
        rows = calculate(view.file_id, tenant, view.carrier_id, month, view.day, parsed, self.cfg, fuel_ok)
        if not self.sw.checks and fuel_ok:
            # without checks every fuel value in the file counts as primary
            good = np.isfinite(parsed.fuel) & np.isin(parsed.mode, ROAD) & rows.kept
            rows.e_kg = np.where(good, parsed.fuel * self.cfg["factors"]["diesel_kg_per_l"], rows.e_kg)
            rows.primary = rows.primary | good
        self.ledger.add(rows)
        self.outcomes.append(FileOutcome(view.file_id, reads, escalated, memory_hit, reviewed, first_failed, accepted_failing, len(held), minutes, latency, mapping, dict(res.failed), first))
        return rows

    def invent_missing(self, rows: FileRows, invent: bool, guess: np.ndarray) -> None:
        """What a model alone does with gaps: estimate fuel and call it primary. The platform never does."""
        if self.sw.never_invent or not invent:
            return
        need = rows.kept & ~rows.primary & np.isin(rows.mode, ROAD)
        est = default_kg(rows.weight_t, rows.dist_km, rows.mode, self.cfg["factors"]) * guess
        rows.e_kg = np.where(need, est, rows.e_kg)
        rows.primary = rows.primary | need
        rows.source = np.where(need, "invented", rows.source).astype(object)
        self.counters.invented_rows += int(need.sum())

    # ------------------------------------------------------------------ clarification agent
    def clarify(self, tenant: str, month: int, day: int, auto_approve: bool = True) -> int:
        if not self.sw.clarification:
            return 0
        who = self.principal("clarification_agent", tenant)
        desk = Principal("desk:approver", "analyst", "*")
        sent = 0
        carriers = sorted({c for (t, c) in self.ledger._by_carrier if t == tenant})
        for cid in carriers:
            rec = self.registry[cid]
            if rec.kind not in ("road", "multimodal"):
                continue
            missing = self.gateway.call(who, "list_missing_fuel", {"tenant": tenant, "carrier_id": cid, "month": month})
            if len(missing) < int(self.cfg["clarification"]["min_shipments"]):
                continue
            ref = f"{tenant}|{cid}|m{month}"
            r = self.model.draft_email(rec, missing, prompts.DRAFT, self.routing["draft"], ref)
            self._span("email.draft", ref, r, 0.0)
            draft: EmailDraft = r.value
            to = rec.contact if self.sw.registry_recipient else draft.to
            ids = [i for i in draft.shipment_ids if i in set(missing)] if self.sw.strip_unknown_ids else list(draft.shipment_ids)
            draft = EmailDraft(cid, to, draft.subject, draft.body, ids)
            args = {"tenant": tenant, "carrier_id": cid, "to": to, "subject": draft.subject, "body": draft.body, "shipment_ids": ids, "day": day, "ref": ref}
            out = self.gateway.call(who, "send_carrier_email", args)
            if isinstance(out, Pending) and not auto_approve:
                pass  # waits in the approval queue for a person (the service)
            elif isinstance(out, Pending):
                reviewed = self.people.review_email(draft, set(missing))
                appr = self.gateway.queue[out.approval_id]
                appr.args = {**appr.args, "body": reviewed.body, "shipment_ids": reviewed.shipment_ids}
                self.gateway.decide(out.approval_id, desk, approve=True)
                self._human(tenant, day, self.cfg["approvals"]["batch_minutes_per_email"], "approve_email", ref, 0.0)
            else:
                self.counters.emails_unapproved += 1
            self.requested.setdefault(f"{tenant}|{cid}", set()).update(ids)
            sent += 1
        return sent

    def ingest_reply(self, ref: str, tenant: str, carrier_id: str, day: int, text: str) -> None:
        who = self.principal("clarification_agent", tenant)
        am = self.cfg["analyst_minutes"]
        self.counters.replies += 1
        body = fence(text, ref) if self.sw.fence else text
        r = self.model.parse_reply(text, prompts.REPLY + "\n" + body, self.routing["reply_parse"], ref)
        self._span("reply.parse", ref, r, 0.0)
        parsed = r.value
        asked = self.requested.get(f"{tenant}|{carrier_id}", set())
        if not self.sw.reply_checks:
            litres = {k: v * (L_PER_GAL if parsed.unit == "gal" else 1.0) for k, v in parsed.values.items()}
            done, _ = self.gateway.call(who, "set_primary_data", {"tenant": tenant, "carrier_id": carrier_id, "litres": litres, "check": False})
            self.counters.reply_rows_primary += done
            return
        flagged = looks_like_instruction(text, self.cfg)
        values = {k: v for k, v in parsed.values.items() if k in asked}
        need_person = flagged or parsed.unit not in ("l", "gal") or len(values) < len(parsed.values)
        refused = 0
        if not need_person:
            litres = {k: v * (L_PER_GAL if parsed.unit == "gal" else 1.0) for k, v in values.items()}
            # a reply the check would mostly refuse is read wrong as a whole (a unit, a column): none of it is used
            ok, bad = self.ledger.set_primary(tenant, carrier_id, litres, self.cfg, "reply", check=True, dry_run=True)
            need_person = bad > 0.15 * max(1, ok + bad)
            if not need_person:
                done, refused = self.gateway.call(who, "set_primary_data", {"tenant": tenant, "carrier_id": carrier_id, "litres": litres, "check": True})
                self.counters.reply_rows_primary += done
        if need_person:
            self.counters.replies_flagged += 1
            fixed = self.people.review_reply(ref, text, parsed)
            self._human(tenant, day, am["reply_review"], "review_reply", ref, 0.0)
            litres = {k: v * (L_PER_GAL if fixed.unit == "gal" else 1.0) for k, v in fixed.values.items() if k in asked}
            done, refused = self.gateway.call(Principal("desk:reviewer", "analyst", "*"), "set_primary_data", {"tenant": tenant, "carrier_id": carrier_id, "litres": litres, "check": True})
            self.counters.reply_rows_primary += done
        self.counters.reply_rows_refused += refused

    # ------------------------------------------------------------------ Q&A agent
    def answer(self, q: Question, caller: Principal | None = None) -> AnswerOutcome:
        who = caller or self.principal("qa_agent", q.tenant)
        body = fence(q.text, q.q_id) if self.sw.fence else q.text
        prompt = prompts.QA + "\n" + body
        tier = self.routing["qa"]
        r = self.model.plan_query(q, prompt, tier)
        lat = self._span("qa.plan", q.q_id, r, 0.0)
        calls = list(r.value)
        if self.sw.answer_check:
            # code reads what the question states outright; a plan that contradicts it is re-planned, then corrected
            slots = question_slots(q.text)
            if any(c.name == "query_emissions" and contradicts(c.args, slots) for c in calls):
                r2 = self.model.plan_query(q, prompt + "\nThe question states: " + str(slots), self.routing["escalate"])
                lat += self._span("qa.replan", q.q_id, r2, lat)
                calls = list(r2.value)
                for c in calls:
                    if c.name == "query_emissions" and contradicts(c.args, slots):
                        c.args = {**c.args, **slots}
        denied: list[str] = []
        result: dict[str, Any] | None = None
        used: dict[str, Any] | None = None
        writes = 0
        for call in calls:
            try:
                out = self.gateway.call(who, call.name, call.args)
            except Denied as e:
                denied.append(e.reason)
                if e.reason == "cross-tenant":
                    self.counters.cross_tenant_denied += 1
                elif call.name != "query_emissions":
                    self.counters.write_attempts_blocked += 1
                continue
            if call.name == "query_emissions":
                result, used = out, call.args
            else:
                writes += int(out) if isinstance(out, int) else 1
        if result is None:
            text = "I can only answer questions about your own company's emissions data."
            self.answers.append(AnswerOutcome(q.q_id, text, None, None, denied, writes, False, lat))
            return self.answers[-1]
        fallback = False
        text = ""
        for attempt in range(2):
            a = self.model.write_answer(q, result, prompt, tier, attempt)
            lat += self._span("qa.answer", q.q_id, a, lat)
            text = a.value
            if not self.sw.answer_check or answer_matches(text, result):
                break
        else:
            fallback = True
            v = result["value"]
            text = f"{result['label']}: {v:,.1f} {result['unit']}." if result["unit"] != "%" else f"{result['label']}: {v:.1f}%."
        self.answers.append(AnswerOutcome(q.q_id, text, result, used, denied, writes, fallback, lat))
        return self.answers[-1]
