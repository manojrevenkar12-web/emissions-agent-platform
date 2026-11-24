"""The people on the customer-success desk. They see the truth only the way a careful person would: by
checking with the carrier. They are right most of the time, not always.
"""

from __future__ import annotations

import numpy as np

from ..domain import FIELDS, EmailDraft, FileView, Mapping, ParsedReply
from .luck import Luck
from .model_sim import PROMISE, ReplyBook
from .world import CarrierFile, World


class Desk:
    def __init__(self, world: World, luck: Luck, book: ReplyBook) -> None:
        self.world = world
        self.luck = luck
        self.book = book
        self.cfg = world.cfg["analysts"]
        self.files: dict[str, CarrierFile] = {f.file_id: f for f in world.files}

    def _true(self, view: FileView) -> Mapping:
        tr = self.files[view.file_id].truth
        cols = {f: tr.columns.get(f) for f in FIELDS}
        codes = {code: mode for mode, (code, _) in tr.fmt.codes.items()}
        return Mapping(cols, tr.fmt.distance_unit if "distance" in tr.columns else None, tr.fmt.weight_unit, "l" if "fuel" in tr.columns else None, codes, {}, "person")

    def _wrong(self, key: str, right: str | None, view: FileView) -> str | None:
        kind, _, name = key.partition(":")
        if kind == "col":
            pool = [h for h in view.headers if h != right]
            return pool[int(self.luck.u("desk_wrong", view.file_id, key) * len(pool))] if pool else right
        if key == "unit:weight":
            return {"kg": "lb", "t": "kg", "lb": "kg"}[right or "kg"]
        if key == "unit:distance":
            return "mi" if right == "km" else "km"
        if kind == "code":
            return {"road_ftl": "road_ltl", "road_ltl": "road_ftl", "rail": "road_ftl", "sea": "road_ltl", "air": "road_van", "road_van": "road_ltl", "inland_waterway": "rail"}.get(right or "", right)
        return right

    def review_mapping(self, view: FileView, proposal: Mapping, flagged: list[str]) -> Mapping:
        truth = self._true(view).decisions()
        out = proposal
        for key in flagged:
            right = truth.get(key)
            ok = self.luck.u("desk_review", view.file_id, key) >= self.cfg["decision_error"]
            out = out.with_decision(key, right if ok else self._wrong(key, right, view))
        # a person who opens a file also fixes codes the model never listed
        for key, right in truth.items():
            if key.startswith("code:") and key[5:] not in out.mode_codes:
                out = out.with_decision(key, right)
        out.source = "person"
        return out

    def map_by_hand(self, view: FileView, sheet: Mapping | None) -> Mapping:
        """Status quo: map a file from scratch, or reuse the sheet kept for this carrier's headers."""
        truth = self._true(view)
        if sheet is not None:
            fmt_now = self.files[view.file_id].truth.fmt
            changed = sheet.weight_unit != fmt_now.weight_unit or (sheet.distance_unit or fmt_now.distance_unit) != fmt_now.distance_unit
            # a thousandfold jump in a month's total is noticed; kg read as lb or km as miles often is not
            big = sheet.weight_unit != fmt_now.weight_unit and "lb" not in (sheet.weight_unit, fmt_now.weight_unit)
            p_notice = 0.97 if big else self.cfg["notices_drift"]
            if changed and self.luck.u("desk_drift", view.file_id) >= p_notice:
                return sheet
            if not changed:
                return sheet
        out = truth
        for key, right in truth.decisions().items():
            if right is None:
                continue
            if self.luck.u("desk_manual", view.file_id, key) < self.cfg["manual_decision_error"]:
                out = out.with_decision(key, self._wrong(key, right, view))
        out.source = "person"
        out.confidence = {}
        return out

    def review_rows(self, view: FileView, rows: np.ndarray, weight_t: np.ndarray) -> np.ndarray:
        tr = self.files[view.file_id].truth
        fixed = weight_t.copy()
        for i in rows:
            if self.luck.u("desk_row", view.file_id, int(i)) >= self.cfg["decision_error"]:
                fixed[i] = tr.weight_t[i]
        return fixed

    def review_reply(self, ref: str, text: str, parsed: ParsedReply) -> ParsedReply:
        rt = self.book.replies[ref]
        if self.luck.u("desk_reply", ref) < self.cfg["decision_error"]:
            return parsed
        return ParsedReply(rt.unit, dict(rt.values), "checked by a person")

    def review_email(self, draft: EmailDraft, valid_ids: set[str]) -> EmailDraft:
        ids = [i for i in draft.shipment_ids if i in valid_ids or self.luck.u("desk_email", draft.carrier_id, i) < 0.05]
        body = draft.body
        for i in draft.shipment_ids:
            if i not in ids:
                body = body.replace(i + "\n", "")
        if PROMISE in body and self.luck.u("desk_promise", draft.carrier_id, len(body)) < 0.95:
            body = body.replace("\n" + PROMISE, "")
        return EmailDraft(draft.carrier_id, draft.to, draft.subject, body, ids)

    def answer_by_hand(self, q_id: str, value: float) -> float:
        if self.luck.u("desk_answer", q_id) < self.cfg["answer_error"]:
            return value * 1.1
        return value
