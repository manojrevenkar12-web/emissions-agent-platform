"""The emissions calculation, in code: ISO 14083-style, shipment by shipment.

Primary data (fuel the carrier measured) wins when it passes the plausibility check; otherwise tonne-km
times the default intensity of the mode. Every row keeps its data-quality label and where its number came
from, so a report can say how much of it rests on primary data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..domain import ROAD
from .checks import Parsed


@dataclass
class FileRows:
    file_id: str
    tenant: str
    carrier_id: str
    month: int
    day: int
    ids: np.ndarray
    origin: np.ndarray
    dest: np.ndarray
    mode: np.ndarray
    weight_t: np.ndarray
    dist_km: np.ndarray
    e_kg: np.ndarray
    primary: np.ndarray  # bool: number rests on measured fuel
    source: np.ndarray  # "file" | "reply" | "invented" | ""
    kept: np.ndarray  # False for dropped duplicates


def planned_distance(p: Parsed, factors: dict[str, Any]) -> np.ndarray:
    adj = np.array([factors["distance_adjustment"].get(x, 1.2) for x in p.mode])
    planned = p.gcd * adj + np.where(p.mode == "air", factors["air_extra_km"], 0.0)
    return np.where(np.isfinite(p.dist_km) & (p.dist_km > 0), p.dist_km, planned)


def default_kg(weight_t: np.ndarray, dist_km: np.ndarray, mode: np.ndarray, factors: dict[str, Any]) -> np.ndarray:
    g = np.array([factors["default_intensity_g_tkm"].get(x, 0.0) for x in mode])
    return weight_t * dist_km * g / 1000.0


def plausible_fuel(litres: np.ndarray, weight_t: np.ndarray, dist_km: np.ndarray, mode: np.ndarray, cfg: dict[str, Any]) -> np.ndarray:
    f = cfg["factors"]
    lo, hi = cfg["checks"]["intensity_ratio"]
    d = default_kg(weight_t, dist_km, mode, f)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = litres * f["diesel_kg_per_l"] / d
    return np.isfinite(r) & (r >= lo) & (r <= hi) & np.isin(mode, ROAD)


def calculate(file_id: str, tenant: str, carrier_id: str, month: int, day: int, p: Parsed, cfg: dict[str, Any], fuel_ok: bool) -> FileRows:
    f = cfg["factors"]
    dist = np.nan_to_num(planned_distance(p, f), nan=0.0)
    weight = np.nan_to_num(p.weight_t, nan=0.0)
    e = default_kg(weight, dist, p.mode, f)
    primary = np.zeros(p.n, dtype=bool)
    source = np.full(p.n, "", dtype=object)
    if fuel_ok:
        good = np.isfinite(p.fuel) & plausible_fuel(p.fuel, weight, dist, p.mode, cfg) & ~p.dup
        e = np.where(good, p.fuel * f["diesel_kg_per_l"], e)
        primary = good
        source = np.where(good, "file", "").astype(object)
    kept = ~p.dup
    e = np.where(kept, np.nan_to_num(e, nan=0.0), 0.0)
    return FileRows(file_id, tenant, carrier_id, month, day, p.ids, p.origin, p.dest, p.mode.copy(), weight, dist, e, primary, source, kept)


@dataclass
class Ledger:
    files: dict[str, FileRows] = field(default_factory=dict)
    _by_carrier: dict[tuple[str, str], list[str]] = field(default_factory=dict)

    def add(self, rows: FileRows) -> None:
        self.files[rows.file_id] = rows
        self._by_carrier.setdefault((rows.tenant, rows.carrier_id), []).append(rows.file_id)

    def carrier_rows(self, tenant: str, carrier_id: str) -> list[FileRows]:
        return [self.files[i] for i in self._by_carrier.get((tenant, carrier_id), [])]

    def missing_fuel(self, tenant: str, carrier_id: str, month: int) -> list[str]:
        out: list[str] = []
        for r in self.carrier_rows(tenant, carrier_id):
            if r.month == month:
                need = r.kept & ~r.primary & np.isin(r.mode, ROAD)
                out.extend(str(x) for x in r.ids[need])
        return out

    def set_primary(self, tenant: str, carrier_id: str, litres: dict[str, float], cfg: dict[str, Any], source: str, check: bool = True, dry_run: bool = False) -> tuple[int, int]:
        """Use measured fuel for these shipments. Returns (rows updated, rows refused by the check).
        With dry_run nothing changes: the caller learns how much of a reply the check would refuse."""
        f = cfg["factors"]
        done = refused = 0
        for r in self.carrier_rows(tenant, carrier_id):
            idx = {str(s): i for i, s in enumerate(r.ids) if r.kept[i]}
            hits = [(idx[s], v) for s, v in litres.items() if s in idx]
            if not hits:
                continue
            rows = np.array([i for i, _ in hits])
            vals = np.array([v for _, v in hits], dtype=float)
            ok = plausible_fuel(vals, r.weight_t[rows], r.dist_km[rows], r.mode[rows], cfg) if check else np.isin(r.mode[rows], ROAD)
            done += int(ok.sum())
            refused += int((~ok).sum())
            if dry_run:
                continue
            r.e_kg[rows[ok]] = vals[ok] * f["diesel_kg_per_l"]
            r.primary[rows[ok]] = True
            r.source[rows[ok]] = source
        return done, refused

    def query(self, tenant: str, month: int, metric: str, mode: str | None = None, origin: str | None = None, destination: str | None = None) -> dict[str, float | str]:
        e = 0.0
        prim = 0.0
        for r in self.files.values():
            if r.tenant != tenant or r.month != month:
                continue
            sel = r.kept.copy()
            if metric == "by_mode" and mode:
                sel &= r.mode == mode
            if metric == "lane":
                sel &= (r.origin == origin) & (r.dest == destination)
            e += float(r.e_kg[sel].sum())
            prim += float(r.e_kg[sel & r.primary].sum())
        if metric == "primary_share":
            return {"value": round(100 * prim / e, 1) if e else 0.0, "unit": "%", "label": "Share based on primary data"}
        label = {"total": "Total", "by_mode": f"{(mode or '').replace('_', ' ')}", "lane": f"{origin} to {destination}"}.get(metric, metric)
        return {"value": round(e / 1000.0, 1), "unit": "t CO2e", "label": label}

    def update_mode(self, tenant: str, month: int, where: str, to: str, cfg: dict[str, Any]) -> int:
        n = 0
        for r in self.files.values():
            if r.tenant == tenant and r.month == month:
                sel = r.kept & np.isin(r.mode, ROAD if where == "road" else (where,)) & ~r.primary
                r.mode[sel] = to
                r.e_kg[sel] = default_kg(r.weight_t[sel], r.dist_km[sel], r.mode[sel], cfg["factors"])
                n += int(sel.sum())
        return n
