"""Runs every design on a split's seeds, grades them, checks the gates and writes reports/<split>.json."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from .. import config
from ..evals.suite import run_gate
from ..sim.designs import DesignRun, run_design
from ..sim.evaluate import default_floor, design_metrics
from ..world.world import World, build_world

REPORTS = config.REPORTS
LOCK = REPORTS / "heldout.lock"
SUMMED = {
    "shipments",
    "files",
    "duplicates_counted",
    "false_primary_rows",
    "invented_rows",
    "carrier_pairs",
    "analyst_minutes",
    "llm_cost_eur",
    "held_rows",
    "accepted_failing_checks",
    "emails_sent",
    "emails_unapproved",
    "emails_to_wrong_company",
    "emails_with_invented_ids",
    "emails_with_promises",
    "replies",
    "replies_to_a_person",
    "reply_rows_refused",
    "injected_replies",
    "injected_replies_acted_on",
    "questions",
    "answers_fallback",
    "cross_tenant_questions",
    "cross_tenant_leaks",
    "unauthorised_writes",
    "write_attempts_blocked",
    "degradation_rows",
    "monitor_false_alarms",
    "audit_entries",
}


class HeldOutLocked(RuntimeError):
    pass


def _round(x: Any) -> Any:
    if isinstance(x, np.bool_):
        return bool(x)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.floating):
        x = float(x)
    if isinstance(x, float):
        if x != x or x in (float("inf"), float("-inf")):
            return None
        return round(x, 5)
    if isinstance(x, dict):
        return {k: _round(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_round(v) for v in x]
    return x


def config_hash() -> str:
    h = hashlib.sha256()
    for p in sorted(config.CONFIG.glob("*.yml")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def _samples(world: World, run: DesignRun) -> dict[str, Any]:
    """What the dashboard shows from the first seed's platform run."""
    files = {f.file_id: f for f in world.files}
    caught = [o for o in run.outcomes if o.first.get("failed") and o.reviewed and o.first.get("second")]
    pick = max(caught, key=lambda o: (len(o.first["failed"]), o.file_id)) if caught else run.outcomes[0]
    f = files[pick.file_id]
    view = f.view
    trace = [
        {"name": s.name, "start_ms": s.start_ms, "duration_ms": s.duration_ms, "model": s.model, "tokens_in": s.tokens_in, "tokens_out": s.tokens_out, "cost_eur": s.cost_eur, "status": s.status}
        for s in run.recorder.traces.get(pick.file_id, [])
    ]
    answers = []
    for kind in ("total", "lane", "cross_tenant", "injected", "primary_share"):
        q = next((x for x in run.qa if x.kind == kind), None)
        if q:
            text = next(a.question.text for a in world.questions if a.question.q_id == q.q_id)
            answers.append({"kind": kind, "question": text, "answer": q.text, "shown": q.shown, "expected": q.expected})
    inj = None
    for ref, rt in run.mailbox.book.replies.items():
        rep = next((r for r in run.mailbox.inbox if r.ref == ref), None)
        if rt.injection and rep:
            from ..world.carriers import INJECTIONS

            lines = rep.text.split("\n")
            inj = {"carrier": rt.carrier_id, "text": "\n".join(lines[:6]), "instruction": INJECTIONS[rt.injection], "kind": rt.injection, "values": len(rt.values)}
            break
    audit = run.audit.entries[:6]
    return {
        "file": {
            "file_id": view.file_id,
            "carrier_kind": world.carriers[view.carrier_id].kind,
            "rows": view.n_rows,
            "headers": view.headers,
            "sample": [[_cell(c[i]) for c in view.columns] for i in range(min(6, view.n_rows))],
            "first": pick.first,
            "final": pick.mapping.to_dict(),
            "reviewed": pick.reviewed,
            "minutes": pick.minutes,
            "trace": trace,
        },
        "answers": answers,
        "injected_reply": inj,
        "audit": {"entries": audit, "verified": run.audit.verify(), "count": run.audit.count},
        "monitor": {**run.monitor, "h": config.platform()["monitor"]["h"], "baseline_obs": config.platform()["monitor"]["baseline_obs"]},
        "degradation": world.cfg.get("degradation"),
        "spans": run.recorder.summary(),
    }


def _cell(x: Any) -> str:
    if isinstance(x, float | np.floating):
        return "" if np.isnan(x) else f"{float(x):.6g}"
    return str(x)


def _seed_job(args: tuple[int, str, bool]) -> dict[str, Any]:
    seed, variant, first = args
    world = build_world(seed, variant)
    cfg = config.platform()
    dcfg = config.designs()
    out: dict[str, Any] = {
        "seed": seed,
        "designs": {},
        "floor": default_floor(world, cfg),
        "world": {
            "files": len(world.files),
            "shipments": int(sum(int((~f.truth.dup).sum()) for f in world.files)),
            "carriers": len(world.carriers),
            "tenants": len(world.tenants),
            "questions": len(world.questions),
        },
    }
    for name, d in dcfg["designs"].items():
        keep = {f.file_id for f in world.files} if (first and name == "platform") else None
        run = run_design(world, name, d, cfg, keep_traces=keep)
        out["designs"][name] = design_metrics(world, run)
        if first and name == "platform":
            out["samples"] = _samples(world, run)
    for name, swap in dcfg["model_swap"].items():
        run = run_design(world, name, {"kind": "platform"}, cfg, model_override={swap["replaces"]: name})
        out["designs"][f"swap:{name}"] = design_metrics(world, run)
    return _round(out)


def _aggregate(per_seed: list[dict[str, Any]]) -> dict[str, Any]:
    names = list(per_seed[0]["designs"])
    agg: dict[str, Any] = {}
    for n in names:
        rows = [s["designs"][n] for s in per_seed]
        m: dict[str, Any] = {}
        for k in rows[0]:
            vals = [r[k] for r in rows]
            if isinstance(vals[0], dict):
                keys = set().union(*[set(v) for v in vals])
                m[k] = {kk: sum(v.get(kk, 0) for v in vals) for kk in sorted(keys)}
            elif k in SUMMED:
                m[k] = sum(v or 0 for v in vals)
            elif k == "monitor_detect_days":
                m[k] = vals
            else:
                xs = [v for v in vals if v is not None]
                m[k] = float(np.mean(xs)) if xs else None
        # pooled rates recomputed from sums
        m["analyst_minutes_per_1k"] = 1000.0 * m["analyst_minutes"] / m["shipments"]
        m["llm_cost_eur_per_1k"] = 1000.0 * m["llm_cost_eur"] / m["shipments"]
        agg[n] = m
    return agg


def check_gates(designs: dict[str, Any], g: dict[str, Any]) -> dict[str, Any]:
    p = designs["platform"]
    s = designs["status_quo"]
    gp = g["platform"]
    rows = [
        ("Monthly total within this error in 95% of tenant-months", p["tenant_month_error_p95"], gp["tenant_month_error_p95_max"], "max"),
        ("Shipments with a unit or column error, per 10k", p["gross_row_errors_per_10k"], gp["gross_row_errors_per_10k_max"], "max"),
        ("Analyst time, share of status quo", p["analyst_minutes"] / s["analyst_minutes"], gp["analyst_minutes_share_of_status_quo_max"], "max"),
        ("Model cost per 1,000 shipments, EUR", p["llm_cost_eur_per_1k"], gp["llm_cost_eur_per_1k_max"], "max"),
        ("Rows labelled primary that are not measured", p["false_primary_rows"], gp["false_primary_rows_max"], "max"),
        ("Carrier emails sent without a person's approval", p["emails_unapproved"], gp["emails_unapproved_max"], "max"),
        ("Carrier emails sent to the wrong company", p["emails_to_wrong_company"], gp["emails_to_wrong_company_max"], "max"),
        ("Injected instructions in replies acted on", p["injected_replies_acted_on"], gp["injected_replies_acted_on_max"], "max"),
        ("Answers that showed another tenant's data", p["cross_tenant_leaks"], gp["cross_tenant_leaks_max"], "max"),
        ("Rows changed by a question", p["unauthorised_writes"], gp["unauthorised_writes_max"], "max"),
        ("Answers with a wrong number, per 100", p["answers_wrong_number_per_100"], gp["answers_wrong_number_per_100_max"], "max"),
        ("Road emissions on primary data, points over status quo (min)", 100 * (p["primary_share_road"] - s["primary_share_road"]), gp["primary_share_road_min_over_status_quo_pts"], "min"),
    ]
    out = [{"gate": n, "value": v, "limit": lim, "kind": k, "pass": (v <= lim) if k == "max" else (v >= lim)} for n, v, lim, k in rows]
    return {"platform": out, "platform_pass": all(r["pass"] for r in out)}


def run_split(split: str, workers: int = 3, eval_gate: dict[str, Any] | None = None) -> dict[str, Any]:
    seeds: list[int] = config.seeds()[split]
    variant = "heldout" if split == "heldout" else "dev"
    jobs = [(s, variant, i == 0) for i, s in enumerate(seeds)]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=min(workers, len(jobs))) as ex:
            per_seed = list(ex.map(_seed_job, jobs))
    else:
        per_seed = [_seed_job(j) for j in jobs]
    designs = _aggregate(per_seed)
    dcfg = config.designs()
    gate = eval_gate if eval_gate is not None else run_gate("balanced", list(dcfg["model_swap"]))
    paired = []
    for s in per_seed:
        d = s["designs"]
        paired.append(
            {
                "seed": s["seed"],
                "platform_p95": d["platform"]["tenant_month_error_p95"],
                "status_quo_p95": d["status_quo"]["tenant_month_error_p95"],
                "platform_minutes": d["platform"]["analyst_minutes"],
                "status_quo_minutes": d["status_quo"]["analyst_minutes"],
            }
        )
    res: dict[str, Any] = {
        "split": split,
        "variant": variant,
        "seeds": seeds,
        "designs": designs,
        "labels": {n: d["label"] for n, d in dcfg["designs"].items()} | {f"swap:{n}": d["label"] for n, d in dcfg["model_swap"].items()},
        "order": list(dcfg["designs"]),
        "ablations": dcfg["ablations"],
        "swaps": [f"swap:{n}" for n in dcfg["model_swap"]],
        "per_seed": paired,
        "floor": {k: float(np.mean([s["floor"][k] for s in per_seed])) for k in ("median", "p95")},
        "world": {k: int(sum(s["world"][k] for s in per_seed)) for k in per_seed[0]["world"]},
        "eval_gate": gate,
        "samples": per_seed[0].get("samples", {}),
    }
    res["gates"] = check_gates(designs, config.gates())
    return _round(res)


def write(split: str, res: dict[str, Any]) -> Path:
    REPORTS.mkdir(exist_ok=True)
    path = REPORTS / f"{split}.json"
    path.write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def run_heldout_once(workers: int = 3) -> dict[str, Any]:
    if LOCK.exists():
        raise HeldOutLocked(f"{LOCK} exists: the held-out seeds have been run. Add new seeds under a new name and an ADR.")
    REPORTS.mkdir(exist_ok=True)
    LOCK.write_text(json.dumps({"seeds": config.seeds()["heldout"], "config_sha256": config_hash()}, indent=1) + "\n", encoding="utf-8")
    dev = REPORTS / "dev.json"
    gate = json.loads(dev.read_text(encoding="utf-8"))["eval_gate"] if dev.exists() else None
    res = run_split("heldout", workers, eval_gate=gate)
    write("heldout", res)
    return res
