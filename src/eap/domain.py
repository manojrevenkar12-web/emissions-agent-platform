"""Types the platform, the world and the service share. Nothing here carries hidden truth."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

FIELDS = ("shipment_id", "date", "origin", "destination", "weight", "distance", "mode", "vehicle", "fuel")
REQUIRED = ("shipment_id", "date", "origin", "destination", "weight", "mode")
MODES = ("road_ftl", "road_ltl", "road_van", "rail", "sea", "air", "inland_waterway")
ROAD = ("road_ftl", "road_ltl", "road_van")
DISTANCE_UNITS = ("km", "mi")
WEIGHT_UNITS = ("kg", "t", "lb")
FUEL_UNITS = ("l", "gal", "kwh")
DQI = Literal["primary", "default"]

# what a carrier of each kind may move, from the onboarding record
KIND_MODES: dict[str, tuple[str, ...]] = {
    "road": ROAD,
    "multimodal": (*ROAD, "rail", "inland_waterway"),
    "ocean": ("sea", "road_ftl", "road_ltl"),
    "air": ("air", "road_ltl", "road_van", "road_ftl"),
}


@dataclass
class FileView:
    """A carrier file as a CSV would show it: headers and values, nothing else."""

    file_id: str
    tenant: str
    carrier_id: str
    day: int
    headers: list[str]
    columns: list[np.ndarray]

    @property
    def n_rows(self) -> int:
        return len(self.columns[0]) if self.columns else 0

    def column(self, header: str | None) -> np.ndarray | None:
        if header is None or header not in self.headers:
            return None
        return self.columns[self.headers.index(header)]

    def to_csv(self, rows: int | None = None) -> str:
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(self.headers)
        n = self.n_rows if rows is None else min(rows, self.n_rows)
        for i in range(n):
            w.writerow([_cell(c[i]) for c in self.columns])
        return buf.getvalue()

    @classmethod
    def from_csv(cls, text: str, *, file_id: str, tenant: str, carrier_id: str, day: int = 0) -> FileView:
        rows = list(csv.reader(io.StringIO(text)))
        if not rows:
            raise ValueError("empty file")
        headers = [h.strip() for h in rows[0]]
        if len(set(headers)) != len(headers):
            raise ValueError("duplicate headers")
        body = [r for r in rows[1:] if any(x.strip() for x in r)]
        cols: list[np.ndarray] = []
        for j in range(len(headers)):
            raw = [r[j].strip() if j < len(r) else "" for r in body]
            cols.append(_typed(raw))
        return cls(file_id, tenant, carrier_id, day, headers, cols)


def _cell(x: Any) -> str:
    if isinstance(x, float | np.floating):
        return "" if np.isnan(x) else f"{float(x):.6g}"
    return str(x)


def _typed(raw: list[str]) -> np.ndarray:
    try:
        return np.array([float(x.replace(",", ".")) if x else np.nan for x in raw], dtype=float)
    except ValueError:
        return np.array(raw, dtype=object)


@dataclass
class Mapping:
    """A reading of one carrier file: which header holds which field, the units and what each mode code means."""

    columns: dict[str, str | None]
    distance_unit: str | None
    weight_unit: str
    fuel_unit: str | None
    mode_codes: dict[str, str]
    confidence: dict[str, float] = field(default_factory=dict)
    source: str = "model"  # model | memory | person

    def decisions(self) -> dict[str, str | None]:
        out: dict[str, str | None] = {f"col:{k}": v for k, v in self.columns.items()}
        out["unit:weight"] = self.weight_unit
        out["unit:distance"] = self.distance_unit
        out["unit:fuel"] = self.fuel_unit
        out.update({f"code:{c}": m for c, m in self.mode_codes.items()})
        return out

    def with_decision(self, key: str, value: str | None) -> Mapping:
        cols = dict(self.columns)
        codes = dict(self.mode_codes)
        du, wu, fu = self.distance_unit, self.weight_unit, self.fuel_unit
        kind, _, name = key.partition(":")
        if kind == "col":
            cols[name] = value
        elif kind == "code":
            codes[name] = value or ""
        elif name == "weight":
            wu = value or "kg"
        elif name == "distance":
            du = value
        elif name == "fuel":
            fu = value
        conf = dict(self.confidence)
        conf[key] = 1.0
        return Mapping(cols, du, wu, fu, codes, conf, self.source)

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": self.columns,
            "distance_unit": self.distance_unit,
            "weight_unit": self.weight_unit,
            "fuel_unit": self.fuel_unit,
            "mode_codes": self.mode_codes,
            "confidence": {k: round(v, 3) for k, v in self.confidence.items()},
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Mapping:
        cols = {f: d.get("columns", {}).get(f) for f in FIELDS}
        wu = d.get("weight_unit") or "kg"
        if wu not in WEIGHT_UNITS:
            raise ValueError(f"weight unit {wu!r}")
        du = d.get("distance_unit")
        if du is not None and du not in DISTANCE_UNITS:
            raise ValueError(f"distance unit {du!r}")
        fu = d.get("fuel_unit")
        if fu is not None and fu not in FUEL_UNITS:
            raise ValueError(f"fuel unit {fu!r}")
        codes = {str(k): str(v) for k, v in (d.get("mode_codes") or {}).items()}
        if any(v not in MODES for v in codes.values()):
            raise ValueError("unknown mode in mode_codes")
        conf = {str(k): float(v) for k, v in (d.get("confidence") or {}).items()}
        return cls(cols, du, wu, fu, codes, conf, str(d.get("source", "model")))


@dataclass(frozen=True)
class CarrierRecord:
    """What the customer-success team knows about a carrier from onboarding."""

    carrier_id: str
    name: str
    kind: str
    contact: str


@dataclass
class EmailDraft:
    carrier_id: str
    to: str
    subject: str
    body: str
    shipment_ids: list[str]


@dataclass
class ParsedReply:
    unit: str | None
    values: dict[str, float]
    notes: str = ""


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]


@dataclass
class Question:
    q_id: str
    tenant: str
    month: int
    text: str


@dataclass
class ModelReply:
    """What one model call returned plus what it cost to get it."""

    value: Any
    model: str
    tokens_in: int
    tokens_out: int
    latency_ms: float
    retries: int = 0
