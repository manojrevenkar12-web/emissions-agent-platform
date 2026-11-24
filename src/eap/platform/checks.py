"""Code checks a proposed mapping against the file and public reference data before any number is kept.

A check never asks the model. It reads what the mapping implies (weights, distances, modes on lanes,
fuel per tonne-km) and names the decisions that cannot be right, so a person looks at exactly those.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..domain import KIND_MODES, ROAD, FileView, Mapping
from ..reference.locations import LOCATIONS, gcd_array, handles

TO_TONNES = {"kg": 1e-3, "t": 1.0, "lb": 0.000453592}
TO_KM = {"km": 1.0, "mi": 1.609344}
TO_LITRES = {"l": 1.0, "gal": 3.785, "kwh": 1.0}
DATE_FORMATS = ["%Y-%m-%d", "%d.%m.%Y", "%m/%d/%Y", "%d/%m/%Y"]


@dataclass
class Parsed:
    n: int
    ids: np.ndarray
    origin: np.ndarray
    dest: np.ndarray
    weight_t: np.ndarray
    dist_km: np.ndarray
    mode: np.ndarray
    fuel: np.ndarray
    gcd: np.ndarray
    dup: np.ndarray
    dates_ok: float


@dataclass
class CheckResult:
    failed: dict[str, str] = field(default_factory=dict)
    holds: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=bool))
    stats: dict[str, float] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.failed


def _num(col: np.ndarray | None, n: int) -> np.ndarray:
    if col is None or col.dtype.kind != "f":
        return np.full(n, np.nan)
    return col.astype(float)


def _dates_ok(col: np.ndarray | None) -> float:
    if col is None or col.dtype.kind == "f" or len(col) == 0:
        return 0.0
    sample = col[: min(len(col), 40)]
    best = 0
    for fmt in DATE_FORMATS:
        ok = 0
        for x in sample:
            try:
                dt.datetime.strptime(str(x), fmt)
                ok += 1
            except ValueError:
                pass
        best = max(best, ok)
    return best / len(sample)


def apply_mapping(view: FileView, m: Mapping, factors: dict[str, Any]) -> Parsed:
    n = view.n_rows
    ids_col = view.column(m.columns.get("shipment_id"))
    ids = ids_col.astype(str) if ids_col is not None else np.array([f"row{i}" for i in range(n)], dtype=object)
    o = view.column(m.columns.get("origin"))
    d = view.column(m.columns.get("destination"))
    origin = o.astype(str) if o is not None else np.full(n, "", dtype=object)
    dest = d.astype(str) if d is not None else np.full(n, "", dtype=object)
    weight = _num(view.column(m.columns.get("weight")), n) * TO_TONNES[m.weight_unit]
    dist = _num(view.column(m.columns.get("distance")), n) * TO_KM.get(m.distance_unit or "km", 1.0)
    mc = view.column(m.columns.get("mode"))
    mode = np.array([m.mode_codes.get(str(x), "") for x in mc], dtype=object) if mc is not None else np.full(n, "", dtype=object)
    fuel = _num(view.column(m.columns.get("fuel")), n) * TO_LITRES.get(m.fuel_unit or "l", 1.0)
    gcd = gcd_array(origin, dest)
    _, first = np.unique(ids, return_index=True)
    dup = np.ones(n, dtype=bool)
    dup[first] = False
    return Parsed(n, ids, origin, dest, weight, dist, mode, fuel, gcd, dup, _dates_ok(view.column(m.columns.get("date"))))


def check_mapping(view: FileView, m: Mapping, p: Parsed, carrier_kind: str, cfg: dict[str, Any]) -> CheckResult:
    c = cfg["checks"]
    f = cfg["factors"]
    res = CheckResult(holds=np.zeros(p.n, dtype=bool))
    used = [h for h in m.columns.values() if h]
    for fld, h in m.columns.items():
        if h and used.count(h) > 1:
            res.failed[f"col:{fld}"] = "two fields read from the same column"
    ids_col = view.column(m.columns.get("shipment_id"))
    if ids_col is None or ids_col.dtype.kind == "f":
        res.failed["col:shipment_id"] = "shipment ids are numbers or missing"
    elif p.dup.mean() > 0.2:
        res.failed["col:shipment_id"] = f"{p.dup.mean():.0%} repeated ids"
    if p.dates_ok < 0.95:
        res.failed["col:date"] = "dates do not parse"
    for fld, arr in (("origin", p.origin), ("destination", p.dest)):
        known = np.mean([x in LOCATIONS for x in arr]) if p.n else 0.0
        if known < 0.95:
            res.failed[f"col:{fld}"] = f"only {known:.0%} known locations"
    known_mode = p.mode != ""
    if p.n and known_mode.mean() < 0.95:
        res.failed["col:mode"] = f"{1 - known_mode.mean():.0%} rows with an unmapped mode code"
    allowed = set(KIND_MODES.get(carrier_kind, ()))
    mc = view.column(m.columns.get("mode"))
    if mc is not None and "col:mode" not in res.failed and "col:origin" not in res.failed and "col:destination" not in res.failed:
        codes = mc.astype(str)
        for code in np.unique(codes):
            rows = codes == code
            mode = m.mode_codes.get(str(code), "")
            if not mode:
                continue
            feasible = np.array([handles(a, mode) and handles(b, mode) for a, b in zip(p.origin[rows], p.dest[rows], strict=True)])
            if mode == "air":
                feasible &= p.gcd[rows] >= c["air_min_km"]
            if feasible.mean() < 0.9 or mode not in allowed:
                res.failed[f"code:{code}"] = f"{mode} is not possible on {1 - feasible.mean():.0%} of these lanes" if mode in allowed else f"{mode} is not something this carrier moves"
    # weights
    if np.isfinite(p.weight_t).mean() < 0.95:
        res.failed["col:weight"] = "weights missing or not numbers"
    elif known_mode.any():
        lo = np.array([c["weight_t"].get(x, [0, np.inf])[0] for x in p.mode])
        hi = np.array([c["weight_t"].get(x, [0, np.inf])[1] for x in p.mode])
        out = known_mode & ((p.weight_t < lo) | (p.weight_t > hi))
        w = p.weight_t[known_mode]
        median_out = bool(np.median(w / hi[known_mode]) > 1.0 or np.median(w / np.maximum(lo[known_mode], 1e-9)) < 1.0)
        for mode, (mlo, mhi) in c.get("median_weight_t", {}).items():
            sel = p.mode == mode
            if sel.sum() >= 10 and not mlo <= float(np.median(p.weight_t[sel])) <= mhi:
                median_out = True
        res.stats["weight_out_share"] = float(out.mean())
        if (out.mean() > c["rows_out_of_range_max"] and out.sum() > c["rows_out_of_range_min"]) or (c["median_out_of_range"] and median_out):
            res.failed["col:weight"] = f"{out.mean():.0%} weights outside the mode's range"
            res.failed["unit:weight"] = "weight unit does not fit the loads"
        else:
            res.holds |= out
    # distances
    have = np.isfinite(p.dist_km) & (p.gcd > 0)
    if m.columns.get("distance") and have.sum() >= 5:
        ratio = p.dist_km[have] / p.gcd[have]
        modes = p.mode[have]
        lo = np.array([c["distance_ratio"].get(x, [0, np.inf])[0] for x in modes])
        hi = np.array([c["distance_ratio"].get(x, [0, np.inf])[1] for x in modes])
        out = (ratio < lo) | (ratio > hi)
        res.stats["distance_ratio_median"] = float(np.median(ratio))
        if out.mean() > c["rows_out_of_range_max"] and out.sum() > c["rows_out_of_range_min"]:
            res.failed["col:distance"] = f"{out.mean():.0%} distances do not fit the lanes (median ratio {np.median(ratio):.2f})"
            res.failed["unit:distance"] = "distance unit does not fit the lanes"
    # fuel
    if m.columns.get("fuel"):
        road = np.isin(p.mode, ROAD) & np.isfinite(p.fuel) & np.isfinite(p.weight_t)
        if road.sum() >= 5:
            dist = np.where(np.isfinite(p.dist_km), p.dist_km, p.gcd * np.array([f["distance_adjustment"].get(x, 1.2) for x in p.mode]))
            per = f["grid_kg_per_kwh"] if m.fuel_unit == "kwh" else f["diesel_kg_per_l"]
            implied = p.fuel[road] * per * 1000 / np.maximum(p.weight_t[road] * dist[road], 1e-9)
            default = np.array([f["default_intensity_g_tkm"][x] for x in p.mode[road]])
            r = float(np.median(implied / default))
            res.stats["fuel_intensity_ratio"] = r
            lo, hi = c["intensity_ratio"]
            if not lo <= r <= hi:
                res.failed["col:fuel"] = f"fuel per tonne-km is {r:.2f}x the default"
                res.failed["unit:fuel"] = "fuel unit does not fit"
    return res


def low_confidence(m: Mapping, cfg: dict[str, Any]) -> list[str]:
    lim = float(cfg["checks"]["confidence_min"])
    return sorted(k for k, v in m.confidence.items() if v < lim and k in m.decisions())
