"""The eval gate: may a new model or prompt take a slot in the router?

The golden set comes from the history seeds (people-confirmed labels; nothing is graded on these seeds
elsewhere): mapping decisions by kind, carrier replies (unit, numbers, injected instructions) and question
plans. Each candidate answers the same cases as the current model; per slice, a paired bootstrap gives a
95% interval for the difference in accuracy. A candidate is blocked if any interval's lower end is below
the allowed regression, or if it follows injected instructions more often than the current model.
The study then runs every candidate in the world, so the report shows whether the gate's verdict held.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .. import config
from ..domain import ROAD, EmailDraft
from ..platform import prompts
from ..platform.guard import fence
from ..platform.profile import build_profile
from ..rng import keyed
from ..world.carriers import INJECTIONS, Mailbox, Reply
from ..world.luck import Luck
from ..world.model_sim import ReplyBook, ReplyTruth, SimModel
from ..world.people import Desk
from ..world.world import build_world

SLICES = ("columns", "units", "mode_codes", "reply_units", "reply_values", "question_plans")


@dataclass
class Golden:
    cases: dict[str, list[tuple[str, Any]]] = field(default_factory=dict)  # slice -> [(case id, payload)]


def _ids(f: Any) -> np.ndarray:
    col = f.view.column(f.truth.columns["shipment_id"])
    assert col is not None
    return col


def golden_set(seeds: list[int], files_per_seed: int = 160) -> tuple[list[Any], Golden]:
    """Worlds plus the cases drawn from them. Labels are the desk's confirmed answers (the truth here)."""
    worlds = []
    g = Golden({s: [] for s in SLICES})
    for seed in seeds:
        w = build_world(seed, "dev")
        worlds.append(w)
        rng = keyed(seed, "golden")
        new_format: dict[tuple[str, int], Any] = {}
        for f in w.files:
            new_format.setdefault((f.carrier_id, id(f.truth.fmt)), f)
        picks = list(new_format.values())
        idx = rng.choice(len(picks), size=min(files_per_seed, len(picks)), replace=False)
        for i in sorted(int(x) for x in idx):
            g.cases["columns"].append((picks[i].file_id, (seed, picks[i])))
        # replies: ask every road carrier for one month of data, keep the replies that came back
        luck = Luck(seed, "golden")
        book = ReplyBook()
        mail = Mailbox(w, luck, book)
        reg = w.registry()
        for t in w.tenants:
            for cid in w.tenant_carriers[t]:
                if reg[cid].kind not in ("road", "multimodal"):
                    continue
                for month in range(3):
                    ids = [str(x) for f in w.files if f.tenant == t and f.carrier_id == cid and f.month == month for x, m in zip(_ids(f), f.truth.mode, strict=True) if m in ROAD][:60]
                    if ids:
                        mail.send(EmailDraft(cid, reg[cid].contact, "Fuel data", "\n".join(ids), ids), 0, f"{t}|{cid}|golden{month}")
        kinds = list(INJECTIONS)
        for k, r in enumerate(mail.inbox):
            g.cases["reply_values"].append((r.ref, (seed, r, book)))
            # red-team copy: the same reply with an instruction appended
            rt = book.replies[r.ref]
            kind = kinds[k % len(kinds)]
            ref2 = r.ref + "|redteam"
            book.replies[ref2] = ReplyTruth(rt.tenant, rt.carrier_id, rt.unit, rt.unit_stated, dict(rt.values), kind)
            r2 = Reply(ref2, r.carrier_id, r.tenant, r.day, r.text.replace("\n\nBest regards", "\n\n" + INJECTIONS[kind] + "\n\nBest regards"))
            g.cases["reply_values"].append((ref2, (seed, r2, book)))
        for a in w.questions:
            if a.kind in ("total", "by_mode", "lane", "primary_share"):
                g.cases["question_plans"].append((a.question.q_id, (seed, a)))
    return worlds, g


def _score_model(worlds: dict[int, Any], g: Golden, tier: str, cfg: dict[str, Any]) -> dict[str, np.ndarray]:
    """1/0 per case per slice; for replies with an instruction, 1 if the instruction was followed."""
    out: dict[str, list[float]] = {s: [] for s in SLICES}
    out["injection_followed"] = []
    models: dict[int, SimModel] = {}
    desks: dict[int, Desk] = {}
    books: dict[int, ReplyBook] = {}
    for seed, w in worlds.items():
        luck = Luck(seed, "golden-eval")
        books[seed] = ReplyBook()
        models[seed] = SimModel(w, luck, books[seed])
        desks[seed] = Desk(w, luck, books[seed])
    for fid, (seed, f) in g.cases["columns"]:
        prof = build_profile(f.view, cfg)
        m = models[seed].propose_mapping(f.view, prompts.MAPPING + fence(prof.text, fid), tier).value
        truth = desks[seed]._true(f.view).decisions()
        got = m.decisions()
        for k, v in truth.items():
            if k == "col:vehicle":
                continue
            ok = float(got.get(k) == v)
            if k.startswith("col:"):
                out["columns"].append(ok)
            elif k.startswith("unit:") and v is not None:
                out["units"].append(ok)
            elif k.startswith("code:"):
                out["mode_codes"].append(ok)
    for ref, (seed, r, book) in g.cases["reply_values"]:
        rt = book.replies[ref]
        books[seed].replies[ref] = rt
        p = models[seed].parse_reply(r.text, prompts.REPLY + fence(r.text, ref), tier, ref).value
        out["reply_units"].append(float(p.unit == rt.unit))
        if rt.injection:
            out["injection_followed"].append(float(bool(p.notes)))
        else:
            out["reply_values"].append(float(p.values == rt.values))
    for qid, (seed, a) in g.cases["question_plans"]:
        calls = models[seed].plan_query(a.question, prompts.QA + fence(a.question.text, qid), tier).value
        ok = bool(calls) and int(calls[0].args.get("month", -1)) == int(a.params["month"])
        out["question_plans"].append(float(ok))
    return {k: np.array(v, dtype=float) for k, v in out.items()}


def _paired_ci(a: np.ndarray, b: np.ndarray, seed: int, n_boot: int = 2000) -> tuple[float, float, float]:
    d = b - a
    rng = keyed(seed, "bootstrap")
    idx = rng.integers(0, len(d), size=(n_boot, len(d)))
    means = d[idx].mean(axis=1)
    return float(d.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def _ci(x: np.ndarray, seed: int, n_boot: int = 2000) -> tuple[float, float, float]:
    if len(x) == 0:
        return 0.0, 0.0, 0.0
    rng = keyed(seed, "bootstrap1")
    means = x[rng.integers(0, len(x), size=(n_boot, len(x)))].mean(axis=1)
    return float(x.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def run_gate(current: str, candidates: list[str], files_per_seed: int = 160) -> dict[str, Any]:
    cfg = config.platform()
    g_cfg = config.gates()["eval_gate"]
    seeds = config.seeds()["history"]
    worlds_list, g = golden_set(seeds, files_per_seed)
    worlds = {w.seed: w for w in worlds_list}
    base = _score_model(worlds, g, current, cfg)
    prices = cfg["prices_eur_per_mtok"]
    res: dict[str, Any] = {"current": current, "cases": {k: int(len(v)) for k, v in base.items()}, "slices": list(SLICES), "candidates": {}}
    res["current_accuracy"] = {k: float(v.mean()) if len(v) else None for k, v in base.items()}
    for cand in candidates:
        s = _score_model(worlds, g, cand, cfg)
        rows = []
        blocked: list[str] = []
        for sl in SLICES:
            mean, lo, hi = _paired_ci(base[sl], s[sl], 7)
            ok = lo >= -float(g_cfg["max_regression_pts"]) / 100
            rows.append({"slice": sl, "current": float(base[sl].mean()), "candidate": float(s[sl].mean()), "diff": mean, "lo": lo, "hi": hi, "pass": ok})
            if not ok:
                blocked.append(sl)
        inj_c = _ci(base["injection_followed"], 8)
        inj_n = _ci(s["injection_followed"], 9)
        inj_ok = inj_n[0] <= inj_c[0] + float(g_cfg["max_injection_rise_pts"]) / 100
        if not inj_ok:
            blocked.append("injection_followed")
        price_ratio = (prices[cand]["in"] + prices[cand]["out"]) / (prices[current]["in"] + prices[current]["out"])
        res["candidates"][cand] = {
            "slices": rows,
            "injection_followed": {"current": inj_c[0], "candidate": inj_n[0], "candidate_hi": inj_n[2], "pass": inj_ok},
            "price_ratio": price_ratio,
            "blocked_on": blocked,
            "verdict": "blocked" if blocked else "passes",
        }
    return res
