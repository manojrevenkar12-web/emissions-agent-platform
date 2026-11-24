"""Context management for the mapping agent: a compact profile of a file instead of the whole file.

The profile carries the headers, per-column statistics and a few sample rows, trimmed to a token budget.
The header fingerprint keys the carrier mapping memory; it hashes header names only, never row values,
so the memory can be shared across tenants without sharing their data.
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..domain import FileView


def _norm(h: str) -> str:
    h = unicodedata.normalize("NFKD", h).encode("ascii", "ignore").decode().lower()
    return "".join(ch for ch in h if ch.isalnum() or ch in "()")


def fingerprint(headers: list[str]) -> str:
    return hashlib.sha1("|".join(sorted(_norm(h) for h in headers)).encode()).hexdigest()[:16]


@dataclass
class Profile:
    text: str
    tokens: int
    sample_rows: int
    fingerprint: str


def _describe(name: str, col: np.ndarray, top: int) -> str:
    if col.dtype.kind == "f":
        finite = col[np.isfinite(col)]
        miss = int(len(col) - len(finite))
        if len(finite) == 0:
            return f"- {name}: number, all empty"
        q = np.percentile(finite, [0, 5, 50, 95, 100])
        return f"- {name}: number, empty {miss}, min {q[0]:.4g}, p5 {q[1]:.4g}, median {q[2]:.4g}, p95 {q[3]:.4g}, max {q[4]:.4g}"
    vals, counts = np.unique(col.astype(str), return_counts=True)
    order = np.argsort(-counts)[:top]
    shown = ", ".join(f"{vals[i]} ({counts[i]})" for i in order)
    return f"- {name}: text, {len(vals)} distinct, top: {shown}"


def build_profile(view: FileView, cfg: dict[str, Any]) -> Profile:
    pc = cfg["profile"]
    stats = "\n".join(_describe(h, c, int(pc["top_values"])) for h, c in zip(view.headers, view.columns, strict=True))
    fp = fingerprint(view.headers)
    budget = int(pc["token_budget"]) * int(pc["chars_per_token"])
    rows = int(pc["sample_rows"])
    while True:
        sample = view.to_csv(rows=rows)
        text = f"File from carrier {view.carrier_id}, {view.n_rows} rows, {len(view.headers)} columns.\nColumns:\n{stats}\nSample rows:\n{sample}"
        if len(text) <= budget or rows <= 2:
            break
        rows -= 2
    return Profile(text, len(text) // int(pc["chars_per_token"]), rows, fp)


def signature(view: FileView, mapping: Any, parsed: Any) -> dict[str, float]:
    """Medians of the raw numbers a remembered mapping reads, to notice a carrier that changed units but
    kept its headers (kg -> lb, km -> mi)."""
    out: dict[str, float] = {}
    for fld in ("weight", "distance", "fuel"):
        col = view.column(mapping.columns.get(fld))
        if col is not None and col.dtype.kind == "f" and np.isfinite(col).any():
            if fld == "distance":
                ok = np.isfinite(col) & (parsed.gcd > 0)
                if ok.any():
                    out[fld] = float(np.median(col[ok] / parsed.gcd[ok]))
            else:
                out[fld] = float(np.nanmedian(col))
    return out


def signature_drift(old: dict[str, float], new: dict[str, float], cfg: dict[str, Any]) -> str | None:
    lo, hi = cfg["memory"]["median_ratio"]
    for k, v in old.items():
        if k in new and v > 0:
            r = new[k] / v
            if not lo <= r <= hi:
                return f"{k} median moved {r:.2f}x"
    return None
