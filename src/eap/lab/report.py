"""Writes REPORT.md, the README results block, the dashboard data and the ISMS control list from reports/*.json.
Nothing here is edited by hand: CI regenerates these files and fails on a diff."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import config

ROOT = config.ROOT
START, END = "<!-- results:start -->", "<!-- results:end -->"
MAIN = ["status_quo", "model_alone", "platform"]
NAMES = {"status_quo": "Status quo (people)", "model_alone": "Model alone", "platform": "The platform"}


def _load(split: str) -> dict[str, Any] | None:
    p = config.REPORTS / f"{split}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def pct(x: float | None, d: int = 1) -> str:
    if x is None:
        return "–"
    if x >= 10:
        return f"{x:,.0f}×"
    return f"{100 * x:.{d}f}%"


def num(x: float | None, d: int = 1) -> str:
    if x is None:
        return "–"
    if abs(x) >= 1000:
        return f"{x:,.0f}"
    return f"{x:,.{d}f}"


def _rows() -> list[tuple[str, str, Any]]:
    return [
        ("Monthly total off by (median tenant-month)", "tenant_month_error_median", pct),
        ("Monthly total off by (95th percentile)", "tenant_month_error_p95", pct),
        ("Shipments with a unit or column error, per 10k", "gross_row_errors_per_10k", num),
        ("Shipments counted twice", "duplicates_counted", lambda x: num(x, 0)),
        ("Road emissions on measured fuel data", "primary_share_road", pct),
        ("Rows labelled primary that are not measured", "false_primary_rows", lambda x: num(x, 0)),
        ("Cleaner-carrier pairs ranked right", "carrier_ranking_concordance", lambda x: pct(x, 0)),
        ("Analyst minutes per 1,000 shipments", "analyst_minutes_per_1k", num),
        ("Files that needed no person", "files_without_a_person", lambda x: pct(x, 0)),
        ("Hours until a file is report-ready (90th pct)", "turnaround_h_p90", num),
        ("Model cost per 1,000 shipments, EUR", "llm_cost_eur_per_1k", lambda x: num(x, 3)),
        ("Carrier emails sent without a person", "emails_unapproved", lambda x: num(x, 0)),
        ("Carrier emails to the wrong company", "emails_to_wrong_company", lambda x: num(x, 0)),
        ("Emails with promises nobody approved", "emails_with_promises", lambda x: num(x, 0)),
        ("Injected instructions in replies acted on", "injected_replies_acted_on", lambda x: num(x, 0)),
        ("Answers with a wrong number, per 100", "answers_wrong_number_per_100", num),
        ("Answers that showed another tenant's data", "cross_tenant_leaks", lambda x: num(x, 0)),
        ("Shipment rows changed by a question", "unauthorised_writes", lambda x: num(x, 0)),
    ]


def _main_table(r: dict[str, Any]) -> list[str]:
    d = r["designs"]
    out = ["| | " + " | ".join(NAMES[n] for n in MAIN) + " |", "|---|" + "---:|" * len(MAIN)]
    for label, key, fmt in _rows():
        cells = [fmt(d[n][key]) for n in MAIN]
        cells[-1] = f"**{cells[-1]}**"
        out.append(f"| {label} | " + " | ".join(cells) + " |")
    return out


SAFEGUARD = {
    "no_checks": "Mapping checks",
    "no_memory": "Carrier mapping memory",
    "no_router": "Small model first, mid-size on doubt",
    "no_approvals": "A person approves carrier emails",
    "no_tenant_scope": "Tenant from the caller's key",
    "no_answer_check": "Code checks the answer's number",
    "no_reply_checks": "Code checks carrier replies",
    "no_monitor": "Quality monitor",
    "no_clarification": "Asking carriers for fuel data",
}
SLICE = {
    "units": "units",
    "reply_units": "reply units",
    "columns": "columns",
    "mode_codes": "mode codes",
    "reply_values": "reply numbers",
    "question_plans": "question plans",
    "injection_followed": "following injected instructions",
}

ABLATION_KEYS = {
    "no_checks": ("tenant_month_error_p95", pct, "monthly total off by (p95)"),
    "no_memory": ("analyst_minutes_per_1k", num, "analyst minutes per 1k"),
    "no_router": ("llm_cost_eur_per_1k", lambda x: num(x, 3), "model EUR per 1k"),
    "no_approvals": ("emails_with_promises", lambda x: num(x, 0), "emails with unapproved promises"),
    "no_tenant_scope": ("cross_tenant_leaks", lambda x: num(x, 0), "answers with another tenant's data"),
    "no_answer_check": ("answers_wrong_number_per_100", num, "wrong numbers per 100 answers"),
    "no_reply_checks": ("false_primary_rows", lambda x: num(x, 0), "rows wrongly labelled primary"),
    "no_monitor": ("monitor_detect_days", lambda x: ", ".join("–" if v is None else str(v) for v in x), "days to detect the provider regression (per seed)"),
    "no_clarification": ("primary_share_road", pct, "road emissions on measured data"),
}


def _ablation_table(r: dict[str, Any]) -> list[str]:
    d = r["designs"]
    out = ["| Safeguard | Measured by | With it | Without it |", "|---|---|---:|---:|"]
    for n in r["ablations"]:
        key, fmt, what = ABLATION_KEYS[n]
        out.append(f"| {SAFEGUARD[n]} | {what} | {fmt(d['platform'][key])} | {fmt(d[n][key])} |")
    return out


def _swap_table(r: dict[str, Any]) -> list[str]:
    d = r["designs"]
    g = r["eval_gate"]["candidates"]
    out = ["| Candidate for the mid-size slot | Eval gate | Blocked on | Rows with unit/column errors per 10k | Analyst min per 1k | EUR per 1k |", "|---|---|---|---:|---:|---:|"]
    p = d["platform"]
    out.append(f"| Current mid-size model | – | – | {num(p['gross_row_errors_per_10k'])} | {num(p['analyst_minutes_per_1k'])} | {num(p['llm_cost_eur_per_1k'], 3)} |")
    for s in r["swaps"]:
        name = s.split(":", 1)[1]
        c = g[name]
        m = d[s]
        out.append(
            f"| {r['labels'][s]} | {c['verdict']} | {', '.join(SLICE.get(b, b) for b in c['blocked_on']) or '–'} | {num(m['gross_row_errors_per_10k'])} | {num(m['analyst_minutes_per_1k'])} | {num(m['llm_cost_eur_per_1k'], 3)} |"
        )
    return out


def _gates(r: dict[str, Any]) -> list[str]:
    out = ["| Gate | Value | Limit | |", "|---|---:|---:|---|"]
    for x in r["gates"]["platform"]:
        v = x["value"]
        vs = num(v, 3) if isinstance(v, float) and v < 1 else num(v, 1)
        out.append(f"| {x['gate']} | {vs} | {'≥' if x['kind'] == 'min' else '≤'} {x['limit']} | {'pass' if x['pass'] else '**fail**'} |")
    return out


def readme_block(dev: dict[str, Any], held: dict[str, Any] | None) -> str:
    w = dev["world"]
    lines = [
        START,
        "",
        f"_Generated by `python -m eap.cli report` from `reports/dev.json`{' and `reports/heldout.json`' if held else ''}. Do not edit by hand._",
        "",
        f"**Development world:** {len(dev['seeds'])} seeds, {w['tenants']} shipper tenants, {w['carriers']} carriers, {w['files']:,} weekly carrier files, "
        f"{w['shipments']:,} shipments, {w['questions']:,} customer questions. Every design runs on the same luck.",
        "",
    ]
    lines += _main_table(dev)
    floor = dev["floor"]
    lines += [
        "",
        f"With default factors alone, a perfect reading of every file would still be off by {pct(floor['median'])} (median) and "
        f"{pct(floor['p95'])} (95th percentile) per tenant-month: only measured fuel data moves that floor.",
        "",
        "**What each safeguard is worth** (one turned off at a time, same luck):",
        "",
    ]
    lines += _ablation_table(dev)
    lines += ["", "**Model changes go through the eval gate** (golden set from separate history seeds; then each candidate runs in the world):", ""]
    lines += _swap_table(dev)
    lines += ["", f"**Release gates, development seeds:** {'all pass' if dev['gates']['platform_pass'] else 'some fail'}", ""]
    lines += _gates(dev)
    if held:
        lines += ["", "**Held-out world, run once** (new header languages, inland waterway, more unit changes and injected replies):", ""]
        lines += _main_table(held)
        lines += ["", f"Held-out gates: {sum(x['pass'] for x in held['gates']['platform'])} of {len(held['gates']['platform'])} pass.", ""]
        lines += _gates(held)
    lines += ["", END]
    return "\n".join(lines)


def report_md(dev: dict[str, Any], held: dict[str, Any] | None) -> str:
    out = ["# Results", "", "Generated from `reports/*.json` by `python -m eap.cli report`.", ""]
    for name, r in (("Development seeds", dev), ("Held-out seeds (run once)", held)):
        if not r:
            continue
        out += [f"## {name}: {', '.join(str(s) for s in r['seeds'])}", "", "### All designs", ""]
        keys = [k for _, k, _ in _rows()] + [
            "memory_hit_rate",
            "escalation_rate",
            "first_read_fail_rate",
            "file_latency_p95_s",
            "replies",
            "replies_to_a_person",
            "write_attempts_blocked",
            "monitor_detect_days",
            "monitor_false_alarms",
        ]
        names = r["order"] + r["swaps"]
        out.append("| metric | " + " | ".join(n.replace("swap:", "swap ") for n in names) + " |")
        out.append("|---|" + "---:|" * len(names))
        for k in keys:
            cells = []
            for n in names:
                v = r["designs"][n][k]
                cells.append(", ".join("–" if x is None else str(x) for x in v) if isinstance(v, list) else ("–" if v is None else (f"{v:.4g}" if isinstance(v, float) else str(v))))
            out.append(f"| {k} | " + " | ".join(cells) + " |")
        out += ["", "### Per seed", "", "| seed | platform p95 | status quo p95 | platform minutes | status quo minutes |", "|---|---:|---:|---:|---:|"]
        for s in r["per_seed"]:
            out.append(f"| {s['seed']} | {pct(s['platform_p95'])} | {pct(s['status_quo_p95'])} | {num(s['platform_minutes'], 0)} | {num(s['status_quo_minutes'], 0)} |")
        out += ["", "### Eval gate", ""]
        g = r["eval_gate"]
        out.append("| candidate | slice | current | candidate | diff | 95% interval | |")
        out.append("|---|---|---:|---:|---:|---|---|")
        for c, v in g["candidates"].items():
            for sl in v["slices"]:
                out.append(
                    f"| {c} | {sl['slice']} | {pct(sl['current'])} | {pct(sl['candidate'])} | {100 * sl['diff']:+.1f} pts | [{100 * sl['lo']:+.1f}, {100 * sl['hi']:+.1f}] | {'pass' if sl['pass'] else 'block'} |"
                )
            inj = v["injection_followed"]
            out.append(f"| {c} | injection followed | {pct(inj['current'])} | {pct(inj['candidate'])} | | | {'pass' if inj['pass'] else 'block'} |")
        out += ["", "### Gates", ""] + _gates(r) + [""]
    return "\n".join(out) + "\n"


def controls_md() -> str:
    c = config.controls()["controls"]
    out = [
        "# ISMS controls",
        "",
        "Generated from `config/controls.yml`. `tests/test_isms.py` fails if any evidence is missing.",
        "",
        "| Control | What the platform does | Evidence |",
        "|---|---|---|",
    ]
    for x in c:
        ev = "<br>".join(f"`{e}`" for e in x["evidence"])
        out.append(f"| **{x['id']}** {x['title']} | {x['how']} | {ev} |")
    return "\n".join(out) + "\n"


def write_all() -> list[Path]:
    dev = _load("dev")
    if dev is None:
        raise SystemExit("run `python -m eap.cli run dev` first")
    held = _load("heldout")
    paths = []
    p = ROOT / "REPORT.md"
    p.write_text(report_md(dev, held), encoding="utf-8")
    paths.append(p)
    readme = ROOT / "README.md"
    if readme.exists():
        text = readme.read_text(encoding="utf-8")
        if START in text and END in text:
            head, rest = text.split(START, 1)
            _, tail = rest.split(END, 1)
            readme.write_text(head + readme_block(dev, held) + tail, encoding="utf-8")
            paths.append(readme)
    data = ROOT / "web" / "public" / "data" / "report.json"
    data.parent.mkdir(parents=True, exist_ok=True)
    data.write_text(json.dumps({"dev": dev, "heldout": held}, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    paths.append(data)
    isms = ROOT / "docs" / "isms" / "CONTROLS.md"
    isms.parent.mkdir(parents=True, exist_ok=True)
    isms.write_text(controls_md(), encoding="utf-8")
    paths.append(isms)
    return paths
