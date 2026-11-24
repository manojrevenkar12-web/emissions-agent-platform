"""A deterministic, offline model behind the same port: header synonyms, units from headers and magnitudes,
a code dictionary and slot-filling for questions. It runs the service and the tests without an API key and
is the floor any hosted model must beat. Its confidence is low whenever it guesses, so code and people
look at what it is unsure of.
"""

from __future__ import annotations

import json
import re
from typing import Any

import numpy as np

from ..domain import FIELDS, CarrierRecord, EmailDraft, FileView, Mapping, ModelReply, ParsedReply, Question, ToolCall
from .guard import question_slots

SYNONYMS: dict[str, list[str]] = {
    "shipment_id": ["sendungsnummer", "shipment id", "shipment", "awb", "hbl", "auftrag", "ref", "przesylki", "expedition"],
    "date": ["datum", "date", "abholdatum", "etd", "dt", "data"],
    "origin": ["von", "origin", "abgangsort", "pol", "ladestelle", "from", "skad", "depart"],
    "destination": ["nach", "destination", "empfangsort", "pod", "entladestelle", "to", "dokad", "arrivee"],
    "weight": ["gewicht", "gross weight", "weight", "brutto", "chargeable", "gew", "waga", "poids", "masse"],
    "distance": ["entfernung", "distance", "strecke", "lastkm", "mileage", "entf", "odleglosc", "kilometrage"],
    "mode": ["verkehrstrager", "verkehrstraeger", "mode", "produkt", "service", "art", "rodzaj"],
    "vehicle": ["fahrzeug", "vehicle", "equipment", "fzg", "pojazd", "vehicule"],
    "fuel": ["diesel", "fuel", "verbrauch", "kraftstoff", "energy", "paliwo", "carburant"],
}
CODES: dict[str, str] = {
    "ftl": "road_ftl",
    "lkw": "road_ftl",
    "komplettladung": "road_ftl",
    "truck": "road_ftl",
    "kl": "road_ftl",
    "ltl": "road_ltl",
    "sammelgut": "road_ltl",
    "stuckgut": "road_ltl",
    "stückgut": "road_ltl",
    "groupage": "road_ltl",
    "sg": "road_ltl",
    "tl": "road_ltl",
    "kurier": "road_van",
    "express": "road_van",
    "van": "road_van",
    "kep": "road_van",
    "bahn": "rail",
    "rail": "rail",
    "kv": "rail",
    "intermodal": "rail",
    "schiene": "rail",
    "fcl": "sea",
    "sea": "sea",
    "lcl": "sea",
    "seefracht": "sea",
    "ocean": "sea",
    "air": "air",
    "luftfracht": "air",
    "af": "air",
    "airfreight": "air",
    "binnenschiff": "inland_waterway",
    "barge": "inland_waterway",
    "iww": "inland_waterway",
}


def _norm(h: str) -> str:
    import unicodedata

    return unicodedata.normalize("NFKD", h).encode("ascii", "ignore").decode().lower()


def _score(header: str, words: list[str]) -> float:
    h = _norm(header)
    base = re.sub(r"\(.*?\)", "", h).strip(" .")
    if base in words:
        return 1.0
    return 0.6 if any(w in h for w in words if len(w) > 2) else 0.0


class LocalModel:
    name = "local"

    def propose_mapping(self, view: FileView, prompt: str, tier: str) -> ModelReply:
        cols: dict[str, str | None] = {}
        conf: dict[str, float] = {}
        taken: set[str] = set()
        for fld in FIELDS:
            best, score = None, 0.0
            for h in view.headers:
                if h in taken:
                    continue
                s = _score(h, SYNONYMS[fld])
                if s > score:
                    best, score = h, s
            cols[fld] = best
            if best:
                taken.add(best)
            conf[f"col:{fld}"] = 0.95 if score == 1.0 else (0.6 if best else 0.9)
        wh = cols.get("weight") or ""
        unit_w = next((u for u in ("kg", "t", "lb") if f"({u})" in wh.lower()), None)
        if unit_w is None:
            col = view.column(cols.get("weight"))
            med = float(np.nanmedian(col)) if col is not None and col.dtype.kind == "f" else 1000.0
            unit_w = "t" if med < 60 else "kg"
            conf["unit:weight"] = 0.55
        else:
            conf["unit:weight"] = 0.97
        dh = cols.get("distance") or ""
        unit_d = None
        if cols.get("distance"):
            unit_d = "mi" if "(mi)" in dh.lower() or "mileage" in dh.lower() else "km"
            conf["unit:distance"] = 0.95 if "(" in dh else 0.6
        codes: dict[str, str] = {}
        mc = view.column(cols.get("mode"))
        if mc is not None:
            for c in sorted(set(mc.astype(str))):
                codes[c] = CODES.get(_norm(c), "road_ftl")
                conf[f"code:{c}"] = 0.95 if _norm(c) in CODES else 0.3
        m = Mapping(cols, unit_d, unit_w, "l" if cols.get("fuel") else None, codes, conf, "model")
        return ModelReply(m, self.name, len(prompt) // 4, len(json.dumps(m.to_dict())) // 4, 5.0)

    def draft_email(self, record: CarrierRecord, shipment_ids: list[str], prompt: str, tier: str, ref: str) -> ModelReply:
        body = f"Dear {record.name} team,\n\nplease send the fuel used per shipment (shipment id; litres) for:\n\n" + "\n".join(shipment_ids) + "\n\nThank you."
        return ModelReply(EmailDraft(record.carrier_id, record.contact, "Fuel data per shipment", body, list(shipment_ids)), self.name, len(prompt) // 4, len(body) // 4, 3.0)

    def parse_reply(self, text: str, prompt: str, tier: str, ref: str) -> ModelReply:
        low = text.lower()
        unit = "gal" if "gallon" in low else ("l" if "litre" in low or "liter" in low else None)
        values = {m.group(1): float(m.group(2)) for m in re.finditer(r"^\s*([A-Z]{2}\w+)\s*[;:,]\s*([\d.]+)\s*$", text, flags=re.MULTILINE)}
        return ModelReply(ParsedReply(unit, values), self.name, len(prompt) // 4, 40 * len(values) // 4, 3.0)

    def plan_query(self, question: Question, prompt: str, tier: str) -> ModelReply:
        slots = question_slots(question.text)
        low = question.text.lower()
        args: dict[str, Any] = {"tenant": question.tenant, "month": slots.get("month", question.month)}
        if "primary" in low:
            args["metric"] = "primary_share"
        elif "origin" in slots:
            args.update({"metric": "lane", "origin": slots["origin"], "destination": slots["destination"]})
        elif "mode" in slots:
            args.update({"metric": "by_mode", "mode": slots["mode"]})
        else:
            args["metric"] = "total"
        return ModelReply([ToolCall("query_emissions", args)], self.name, len(prompt) // 4, 40, 2.0)

    def write_answer(self, question: Question, result: dict[str, float | str], prompt: str, tier: str, attempt: int) -> ModelReply:
        v = result.get("value")
        unit = str(result.get("unit", ""))
        text = f"{result.get('label', 'Result')}: {float(v):,.1f} {unit}." if isinstance(v, int | float) and unit != "%" else f"{result.get('label', 'Result')}: {v}%."
        return ModelReply(text, self.name, len(prompt) // 4, len(text) // 4, 1.0)
