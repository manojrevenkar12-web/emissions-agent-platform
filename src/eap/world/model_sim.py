"""The simulated language model. It is part of the world: it may look at the truth to decide, by luck,
whether its reading is right, and the platform only ever sees what it answers.

P(correct) = sigmoid(skill - difficulty). Confidence follows correctness on average but is noisy, so a
confident wrong answer exists. A provider-side regression lowers one model's skill for some days.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..domain import FIELDS, CarrierRecord, EmailDraft, FileView, Mapping, ModelReply, ParsedReply, Question, ToolCall
from .luck import Luck, logit, sigmoid
from .world import CarrierFile, World

PROMISE = "We will cover your costs for providing this data."
WRONG_WEIGHT_UNIT = {"kg": ["lb", "t"], "t": ["kg"], "lb": ["kg"]}


@dataclass
class ReplyTruth:
    tenant: str
    carrier_id: str
    unit: str
    unit_stated: bool
    values: dict[str, float]  # shipment id -> value in `unit`
    injection: str | None


@dataclass
class ReplyBook:
    replies: dict[str, ReplyTruth] = field(default_factory=dict)


class SimModel:
    def __init__(self, world: World, luck: Luck, book: ReplyBook) -> None:
        self.world = world
        self.luck = luck
        self.book = book
        self.models: dict[str, dict[str, Any]] = world.cfg["models"]
        self.files: dict[str, CarrierFile] = {f.file_id: f for f in world.files}
        self.asked = {a.question.q_id: a for a in world.questions}
        self.deg = world.cfg.get("degradation") or {}

    # ----------------------------------------------------------------- helpers
    def _skill(self, tier: str, day: int) -> tuple[float, float]:
        m = self.models[tier]
        s, us = float(m["skill"]), float(m["unit_skill"])
        if self.deg and tier == self.deg["model"] and self.deg["start_day"] <= day < self.deg["end_day"]:
            s -= float(self.deg["skill_drop"])
            us -= float(self.deg["skill_drop"])
        return s, us

    def _call(self, tier: str, ref: str, prompt: str, out_chars: int) -> tuple[int, int, float, int]:
        m = self.models[tier]
        u_lat, z_lat = self.luck.uz("latency", tier, ref)
        retries = 0
        while retries < 3 and self.luck.u("provider_error", tier, ref, retries) < self.world.cfg["provider_errors"]:
            retries += 1
        med, sig = m["latency_ms"]
        latency = float(np.exp(np.log(med) + sig * z_lat)) * (1 + retries) * (0.8 + 0.4 * u_lat) * (1 + len(prompt) / 40000)
        return len(prompt) // 4, out_chars // 4 + 60, latency, retries

    def _decide(self, key: tuple[object, ...], p: float) -> tuple[bool, float]:
        """`key` names the case and ends with the model. The coin is the case's own, shared by every model
        (a hard header is hard for all of them); the confidence noise is the model's."""
        *case, tier = key
        u = self.luck.u("case", *case)
        z = self.luck.uz("conf", *case, tier)[1]
        ok = u < p
        conf = sigmoid(logit(p) + (1.0 if ok else -1.6) + 0.8 * z)
        return ok, conf

    # ----------------------------------------------------------------- mapping
    def propose_mapping(self, view: FileView, prompt: str, tier: str) -> ModelReply:
        f = self.files[view.file_id]
        tr = f.truth
        skill, unit_skill = self._skill(tier, view.day)
        columns: dict[str, str | None] = {}
        conf: dict[str, float] = {}
        others = list(view.headers)
        distractors = [h for h, _ in tr.fmt.distractors]
        for fld in FIELDS:
            true_h = tr.columns.get(fld)
            diff = tr.fmt.headers[fld][1] if true_h else 0.8
            ok, c = self._decide(("map", view.file_id, f"col:{fld}", tier), sigmoid(skill - diff))
            if ok:
                columns[fld] = true_h
            else:
                u = self.luck.u("map_wrong", view.file_id, tier, fld)
                pool = [h for h in (distractors if fld in ("weight", "distance", "fuel") and distractors else others) if h != true_h]
                # a wrong reading of a field the file lacks is a column; of a field it has, a column or nothing
                columns[fld] = None if not pool or (true_h is not None and u < 0.25 and fld not in ("shipment_id", "origin", "destination")) else pool[int(u * 997) % len(pool)]
            conf[f"col:{fld}"] = c
        fmt = tr.fmt
        p_w = sigmoid(skill - 0.2) if fmt.unit_in_header["weight"] else sigmoid(unit_skill)
        ok, c = self._decide(("map", view.file_id, "unit:weight", tier), p_w)
        alts = WRONG_WEIGHT_UNIT[fmt.weight_unit]
        wu = fmt.weight_unit if ok else alts[int(self.luck.u("map_wrong", view.file_id, tier, "wu") * len(alts))]
        conf["unit:weight"] = c
        du: str | None = None
        if "distance" in tr.columns:
            p_d = sigmoid(skill - 0.2) if fmt.unit_in_header["distance"] else sigmoid(unit_skill)
            ok, c = self._decide(("map", view.file_id, "unit:distance", tier), p_d)
            du = fmt.distance_unit if ok else ("mi" if fmt.distance_unit == "km" else "km")
            conf["unit:distance"] = c
        fu: str | None = None
        if "fuel" in tr.columns:
            ok, c = self._decide(("map", view.file_id, "unit:fuel", tier), sigmoid(skill - 0.6))
            fu = "l" if ok else ("gal" if self.luck.u("map_wrong", view.file_id, tier, "fu") < 0.5 else "kwh")
            conf["unit:fuel"] = c
        codes: dict[str, str] = {}
        confusable: dict[str, list[str]] = self.world.cfg["confusable"]
        for mode, (code, diff) in fmt.codes.items():
            ok, c = self._decide(("map", view.file_id, f"code:{code}", tier), sigmoid(skill - diff))
            if ok:
                codes[code] = mode
            else:
                alts = confusable[mode]
                codes[code] = alts[int(self.luck.u("map_wrong", view.file_id, tier, code) * len(alts))]
            conf[f"code:{code}"] = c
        mapping = Mapping(columns, du, wu, fu, codes, conf, "model")
        tin, tout, lat, retries = self._call(tier, f"map:{view.file_id}", prompt, len(json.dumps(mapping.to_dict())) + 400)
        return ModelReply(mapping, tier, tin, tout, lat, retries)

    # ----------------------------------------------------------------- email
    def draft_email(self, record: CarrierRecord, shipment_ids: list[str], prompt: str, tier: str, ref: str) -> ModelReply:
        m = self.models[tier]
        to = record.contact
        if self.luck.u("email_to", ref) < m["wrong_recipient"]:
            others = sorted(c.contact for c in self.world.carriers.values() if c.contact != record.contact)
            to = others[int(self.luck.u("email_to_pick", tier, ref) * len(others))]
        ids = list(shipment_ids)
        if self.luck.u("email_ids", ref) < m["invented_ids"]:
            ids = ids + [f"SH{record.carrier_id[2:]}99{k:04d}" for k in range(3)]
        body = (
            f"Dear {record.name} team,\n\nfor our emissions report we need the fuel used per shipment for the shipments below. "
            "A reply with one line per shipment (shipment id; litres) is enough.\n\n" + "\n".join(ids) + "\n\nThank you."
        )
        if self.luck.u("email_promise", ref) < m["draft_promise"]:
            body += "\n" + PROMISE
        draft = EmailDraft(record.carrier_id, to, "Fuel data per shipment", body, ids)
        tin, tout, lat, retries = self._call(tier, f"draft:{ref}", prompt, len(body))
        return ModelReply(draft, tier, tin, tout, lat, retries)

    # ----------------------------------------------------------------- replies
    def parse_reply(self, text: str, prompt: str, tier: str, ref: str) -> ModelReply:
        rt = self.book.replies[ref]
        m = self.models[tier]
        skill, unit_skill = self._skill(tier, 0)
        p_unit = sigmoid(skill - 0.3) if rt.unit_stated else sigmoid(unit_skill)
        ok_unit, _ = self._decide(("reply_unit", ref, tier), p_unit)
        unit: str | None = rt.unit if ok_unit else ("gal" if rt.unit == "l" else "l")
        if not ok_unit and not rt.unit_stated and self.luck.u("reply_unit_none", ref, tier) < 0.5:
            unit = None
        values = dict(rt.values)
        ok_vals, _ = self._decide(("reply_vals", ref, tier), sigmoid(skill - 0.5))
        if not ok_vals and len(values) > 1:
            keys = sorted(values)
            k = keys[int(self.luck.u("reply_slip", ref, tier) * len(keys))]
            values[k] = values[k] * 10
        notes = ""
        if rt.injection:
            fenced = "<untrusted" in prompt
            p_obey = float(m["obey_fenced"] if fenced else m["obey_injection"])
            if self.luck.u("reply_obey", ref) < p_obey:
                if rt.injection == "zero":
                    values = {k: 0.0 for k in values}
                else:
                    values = {k: v / 2 for k, v in values.items()}
                notes = "followed an instruction in the reply"
        parsed = ParsedReply(unit, values, notes)
        tin, tout, lat, retries = self._call(tier, f"reply:{ref}", prompt, 40 * len(values) + 80)
        return ModelReply(parsed, tier, tin, tout, lat, retries)

    # ----------------------------------------------------------------- questions
    def plan_query(self, question: Question, prompt: str, tier: str) -> ModelReply:
        a = self.asked[question.q_id]
        m = self.models[tier]
        skill, _ = self._skill(tier, 90)
        month = int(a.params["month"])
        right, _ = self._decide(("plan", question.q_id, tier), sigmoid(skill - 0.6))
        if not right:
            month = (month + 1) % 3
        base: dict[str, Any] = {"tenant": question.tenant, "month": month}
        calls: list[ToolCall] = []
        if a.kind == "total" or a.kind == "injected":
            calls.append(ToolCall("query_emissions", {**base, "metric": "total"}))
        elif a.kind == "by_mode":
            calls.append(ToolCall("query_emissions", {**base, "metric": "by_mode", "mode": a.params["mode"]}))
        elif a.kind == "lane":
            o, d = a.params["lane"]
            calls.append(ToolCall("query_emissions", {**base, "metric": "lane", "origin": o, "destination": d}))
        elif a.kind == "primary_share":
            calls.append(ToolCall("query_emissions", {**base, "metric": "primary_share"}))
        elif a.kind == "cross_tenant":
            if self.luck.u("cross_obey", question.q_id) < m["cross_tenant_obey"]:
                calls.append(ToolCall("query_emissions", {**base, "tenant": a.params["other"], "metric": "total"}))
        if a.kind == "injected":
            fenced = "<untrusted" in prompt
            p = float(m["obey_fenced"] if fenced else m["obey_injection"])
            if self.luck.u("q_obey", question.q_id) < p:
                calls.append(ToolCall("update_shipments", {"tenant": question.tenant, "month": a.params["month"], "where_mode": "road", "set_mode": "rail"}))
        tin, tout, lat, retries = self._call(tier, f"plan:{question.q_id}", prompt, 200 * max(1, len(calls)))
        return ModelReply(calls, tier, tin, tout, lat, retries)

    def write_answer(self, question: Question, result: dict[str, float | str], prompt: str, tier: str, attempt: int) -> ModelReply:
        m = self.models[tier]
        value = result.get("value")
        if not isinstance(value, int | float):
            text = "I can only answer questions about your own company's data."
        else:
            v = float(value)
            if self.luck.u("slip", question.q_id, attempt) < m["number_slip"]:
                v = v * (1.1 if self.luck.u("slip_kind", question.q_id, tier, attempt) < 0.5 else 0.9)
            unit = str(result.get("unit", "t CO2e"))
            text = f"{result.get('label', 'Result')}: {v:,.1f} {unit}." if unit != "%" else f"{result.get('label', 'Result')}: {v:.1f}%."
        tin, tout, lat, retries = self._call(tier, f"answer:{question.q_id}:{attempt}", prompt, len(text) + 120)
        return ModelReply(text, tier, tin, tout, lat, retries)


NUMBER = re.compile(r"-?\d[\d,]*\.?\d*")
