"""The simulated world: shippers (tenants), their carriers, a quarter of weekly carrier files, and the questions
customers ask. Every file carries its hidden truth next to the view a design is allowed to read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache
from typing import Any

import numpy as np
import yaml

from .. import config
from ..domain import ROAD, CarrierRecord, FileView, Question
from ..reference.locations import EUROPE, LOCATIONS, gcd_km, handles
from ..rng import keyed

TENANT_NAMES = ["Nordhafen Foods", "Kranich Chemie", "Alpenwind Retail", "Elbtal Maschinenbau", "Ostsee Home", "Lindgrün Pharma", "Moorbach Textil", "Falkenried Auto"]
WEIGHT_FACTOR = {"kg": 1000.0, "t": 1.0, "lb": 2204.62}
DISTANCE_FACTOR = {"km": 1.0, "mi": 0.621371}
DATE_FORMATS = ["%Y-%m-%d", "%d.%m.%Y", "%m/%d/%Y", "%d/%m/%Y"]
DISTRACTORS = [("Packstücke", "pieces"), ("Volumen m3", "volume"), ("Frachtkosten EUR", "cost"), ("Lademeter", "ldm"), ("Pallets", "pieces")]


@cache
def world_config(variant: str) -> dict[str, Any]:
    raw = yaml.safe_load((config.CONFIG / "world.yml").read_text(encoding="utf-8"))
    base = raw["dev"]
    return base if variant == "dev" else config.merged(base, raw[variant])


@dataclass(frozen=True)
class Format:
    headers: dict[str, tuple[str, float]]
    distance_unit: str
    weight_unit: str
    unit_in_header: dict[str, bool]
    codes: dict[str, tuple[str, float]]
    date_fmt: str
    distractors: tuple[tuple[str, str], ...]

    def header(self, f: str) -> str | None:
        if f not in self.headers:
            return None
        h = self.headers[f][0]
        if f == "weight" and self.unit_in_header["weight"]:
            return f"{h} ({self.weight_unit})"
        if f == "distance" and self.unit_in_header["distance"]:
            return f"{h} ({self.distance_unit})"
        return h


@dataclass
class Carrier:
    carrier_id: str
    name: str
    kind: str
    contact: str
    modes: dict[str, float]
    efficiency: dict[str, float]
    electric_share: float
    telematics: bool
    replies: bool
    reply_delay: int
    reply_unit: str
    reply_unit_stated: bool
    volume: float
    start_week: int
    lanes: dict[str, list[tuple[str, str]]]
    timeline: list[tuple[int, Format, str | None]]  # (from week, format, drift kind)

    def format_at(self, week: int) -> tuple[Format, str | None]:
        fmt, kind = self.timeline[0][1], None
        for w, f, k in self.timeline:
            if w <= week:
                fmt, kind = f, (k if w == week else None)
        return fmt, kind


@dataclass
class FileTruth:
    fmt: Format
    drift: str | None
    mode: np.ndarray
    weight_t: np.ndarray
    dist_km: np.ndarray
    e_kg: np.ndarray
    fuel_l: np.ndarray
    kwh: np.ndarray
    dup: np.ndarray
    typo: np.ndarray
    dist_missing: np.ndarray
    columns: dict[str, str]  # field -> header in this file


@dataclass
class CarrierFile:
    file_id: str
    tenant: str
    carrier_id: str
    week: int
    day: int
    month: int
    view: FileView
    truth: FileTruth


@dataclass
class AskedQuestion:
    question: Question
    kind: str
    params: dict[str, Any]


@dataclass
class World:
    seed: int
    variant: str
    cfg: dict[str, Any]
    tenants: list[str]
    tenant_names: dict[str, str]
    carriers: dict[str, Carrier]
    tenant_carriers: dict[str, list[str]]
    files: list[CarrierFile] = field(default_factory=list)
    questions: list[AskedQuestion] = field(default_factory=list)

    def registry(self) -> dict[str, CarrierRecord]:
        """What onboarding recorded about each carrier: public to the platform."""
        return {c.carrier_id: CarrierRecord(c.carrier_id, c.name, c.kind, c.contact) for c in self.carriers.values()}

    @property
    def n_rows(self) -> int:
        return sum(f.view.n_rows for f in self.files)


def _pick(rng: np.random.Generator, weights: dict[str, float]) -> str:
    keys = list(weights)
    p = np.array([weights[k] for k in keys], dtype=float)
    return str(keys[int(rng.choice(len(keys), p=p / p.sum()))])


@cache
def _lanes(mode: str) -> list[tuple[str, str]]:
    codes = list(LOCATIONS)
    lo, hi = {"rail": (150, 1600), "sea": (400, 25000), "air": (400, 12000), "inland_waterway": (50, 900)}.get(mode, (30, 1700))
    pool = EUROPE if mode in ROAD or mode in ("rail", "inland_waterway") else codes
    out = []
    for a in pool:
        for b in pool:
            if a != b and handles(a, mode) and handles(b, mode) and lo <= gcd_km(a, b) <= hi:
                out.append((a, b))
    return out


def _format(rng: np.random.Generator, cfg: dict[str, Any], kind_modes: list[str], fcfg: dict[str, Any], has: dict[str, bool]) -> Format:
    headers: dict[str, tuple[str, float]] = {}
    for f, variants in cfg["headers"].items():
        if f in ("distance", "vehicle", "fuel") and not has[f]:
            continue
        h, d = variants[int(rng.integers(len(variants)))]
        headers[f] = (str(h), float(d))
    codes: dict[str, tuple[str, float]] = {}
    for m in kind_modes:
        variants = cfg["mode_codes"][m]
        c, d = variants[int(rng.integers(len(variants)))]
        codes[m] = (str(c), float(d))
    # two modes must not share a code inside one carrier's export
    seen: set[str] = set()
    for m in list(codes):
        if codes[m][0] in seen:
            for c, d in cfg["mode_codes"][m]:
                if c not in seen:
                    codes[m] = (str(c), float(d))
                    break
        seen.add(codes[m][0])
    n_dis = int(rng.integers(1, 3))
    dis = tuple(DISTRACTORS[int(i)] for i in rng.choice(len(DISTRACTORS), size=n_dis, replace=False))
    return Format(
        headers=headers,
        distance_unit=_pick(rng, fcfg["distance_unit"]),
        weight_unit=_pick(rng, fcfg["weight_unit"]),
        unit_in_header={"weight": bool(rng.random() < fcfg["unit_in_header"]), "distance": bool(rng.random() < fcfg["unit_in_header"])},
        codes=codes,
        date_fmt=DATE_FORMATS[int(rng.integers(len(DATE_FORMATS)))],
        distractors=dis,
    )


def _drifted(rng: np.random.Generator, cfg: dict[str, Any], fmt: Format, kind: str) -> Format:
    if kind == "unit_switch":
        if rng.random() < 0.5 and "distance" in fmt.headers:
            du = "mi" if fmt.distance_unit == "km" else "km"
            return Format(fmt.headers, du, fmt.weight_unit, fmt.unit_in_header, fmt.codes, fmt.date_fmt, fmt.distractors)
        others = [u for u in ("kg", "t", "lb") if u != fmt.weight_unit]
        wu = others[int(rng.integers(len(others)))]
        return Format(fmt.headers, fmt.distance_unit, wu, fmt.unit_in_header, fmt.codes, fmt.date_fmt, fmt.distractors)
    headers = dict(fmt.headers)
    for f in rng.choice(list(headers), size=min(3, len(headers)), replace=False):
        variants = cfg["headers"][str(f)]
        h, d = variants[int(rng.integers(len(variants)))]
        headers[str(f)] = (str(h), float(d))
    return Format(headers, fmt.distance_unit, fmt.weight_unit, fmt.unit_in_header, fmt.codes, fmt.date_fmt, fmt.distractors)


def _carrier(seed: int, variant: str, cfg: dict[str, Any], cid: str, k: int) -> Carrier:
    rng = keyed(seed, variant, "carrier", cid)
    kinds = cfg["carrier_kinds"]
    kind = _pick(rng, {n: v["share"] for n, v in kinds.items()})
    modes = {m: float(p) for m, p in kinds[kind]["modes"].items()}
    eff = {m: float(np.exp(rng.normal(0, cfg["carrier_efficiency_sigma"]))) for m in modes}
    fcfg = cfg["file"]
    road = kind in ("road", "multimodal")
    electric = float(rng.uniform(0.15, 0.45)) if road and rng.random() < cfg["electric_fleet"] else 0.0
    # an export with a fuel column comes from a diesel fleet: litres per shipment
    has = {
        "distance": bool(rng.random() < fcfg["distance_column"]),
        "vehicle": bool(rng.random() < fcfg["vehicle_column"]),
        "fuel": road and electric == 0.0 and bool(rng.random() < fcfg["fuel_column"]),
    }
    fmt = _format(rng, cfg, list(modes), fcfg, has)
    timeline: list[tuple[int, Format, str | None]] = [(0, fmt, None)]
    for w in range(1, int(cfg["weeks"])):
        if rng.random() < cfg["drift"]["per_carrier_week"]:
            dk = _pick(rng, cfg["drift"]["kinds"])
            fmt = _drifted(rng, cfg, fmt, dk)
            timeline.append((w, fmt, dk))
    lanes = {}
    for m in modes:
        pool = _lanes(m)
        idx = rng.choice(len(pool), size=min(len(pool), int(rng.integers(6, 16))), replace=False)
        lanes[m] = [pool[int(i)] for i in idx]
    cc = cfg["carriers"]
    return Carrier(
        carrier_id=cid,
        name=f"{kind.title()} carrier {k:03d}",
        kind=kind,
        contact=f"data-{cid.lower()}@carrier.example",
        modes=modes,
        efficiency=eff,
        electric_share=electric,
        telematics=road and bool(rng.random() < cc["telematics"]),
        replies=bool(rng.random() < cc["reply"]),
        reply_delay=int(rng.integers(cc["reply_days"][0], cc["reply_days"][1] + 1)),
        reply_unit=_pick(rng, cc["reply_unit"]),
        reply_unit_stated=bool(rng.random() < cc["unit_stated"]),
        volume=float(np.exp(rng.normal(0, 0.45))),
        start_week=int(rng.integers(1, max(2, int(cfg["weeks"]) - 2))) if rng.random() < cfg.get("late_start", 0.0) else 0,
        lanes=lanes,
        timeline=timeline,
    )


def _file(world: World, tenant: str, car: Carrier, week: int) -> CarrierFile | None:
    cfg = world.cfg
    fid = f"{tenant}-{car.carrier_id}-w{week:02d}"
    rng = keyed(world.seed, world.variant, "file", fid)
    n = int(rng.poisson(cfg["rows_per_file"] * car.volume))
    if n < 3:
        return None
    fmt, drift = car.format_at(week)
    day = week * 7 + int(rng.integers(0, 5))
    month = min(2, day // 30)
    modes = np.array([_pick(rng, car.modes) for _ in range(n)], dtype=object)
    origin = np.empty(n, dtype=object)
    dest = np.empty(n, dtype=object)
    for i, m in enumerate(modes):
        lane = car.lanes[m][int(rng.integers(len(car.lanes[m])))]
        origin[i], dest[i] = lane
    gcd = np.array([gcd_km(o, d) for o, d in zip(origin, dest, strict=True)])
    circ = np.array([np.exp(rng.normal(np.log(cfg["circuity"][m][0]), cfg["circuity"][m][1])) for m in modes])
    dist = gcd * circ
    w_t = np.array([np.exp(rng.normal(np.log(cfg["weight_t"][m][0]), cfg["weight_t"][m][1])) for m in modes])
    caps = {"road_ftl": 25.0, "road_ltl": 11.5, "road_van": 1.4, "air": 6.0, "sea": 28.0, "rail": 60.0, "inland_waterway": 1500.0}
    w_t = np.minimum(w_t, [caps[m] for m in modes])
    w_t = np.maximum(w_t, 0.01)
    base = np.array([cfg["true_intensity"][m] * car.efficiency[m] for m in modes])
    intensity = base * np.exp(rng.normal(0, cfg["shipment_sigma"], n))
    electric = np.array([m in ROAD for m in modes]) & (rng.random(n) < car.electric_share)
    intensity = np.where(electric, intensity * 0.36, intensity)
    e = w_t * dist * intensity / 1000.0
    fuel_l = np.where(~electric & np.array([m in ROAD for m in modes]), e / cfg["diesel_kg_per_l"], np.nan)
    kwh = np.where(electric, e / cfg["grid_kg_per_kwh"], np.nan)

    fc = cfg["file"]
    ids = np.array([f"SH{car.carrier_id[2:]}{week:02d}{i:04d}" for i in range(n)], dtype=object)
    typo = rng.random(n) < fc["weight_typo_x10"]
    dmiss = rng.random(n) < fc["distance_missing_rows"]
    # duplicates: some rows exported twice
    dup_src = np.flatnonzero(rng.random(n) < fc["duplicate_rows"])
    order = np.concatenate([np.arange(n), dup_src])
    dup = np.concatenate([np.zeros(n, bool), np.ones(len(dup_src), bool)])
    take = order
    m_all, o_all, d_all, ids_all = modes[take], origin[take], dest[take], ids[take]
    w_true, dist_true = w_t[take], dist[take]
    e_true = np.where(dup, 0.0, e[take])
    fuel_true, kwh_true = fuel_l[take], kwh[take]
    typo_all, dmiss_all = typo[take], dmiss[take]

    start = np.datetime64("2026-01-05") + np.timedelta64(day, "D")
    import datetime as _dt

    d0 = _dt.date.fromisoformat(str(start))
    dates = np.array([(d0 + _dt.timedelta(days=int(x))).strftime(fmt.date_fmt) for x in rng.integers(-3, 1, size=len(take))], dtype=object)

    cols: dict[str, np.ndarray] = {}
    cols["shipment_id"] = ids_all
    cols["date"] = dates
    cols["origin"] = o_all
    cols["destination"] = d_all
    wv = np.where(typo_all, w_true * 10, w_true) * WEIGHT_FACTOR[fmt.weight_unit]
    cols["weight"] = np.round(wv, 1 if fmt.weight_unit != "t" else 3)
    if "distance" in fmt.headers:
        dv = dist_true * DISTANCE_FACTOR[fmt.distance_unit]
        cols["distance"] = np.where(dmiss_all, np.nan, np.round(dv, 0))
    cols["mode"] = np.array([fmt.codes[m][0] for m in m_all], dtype=object)
    if "vehicle" in fmt.headers:
        vt = {"road_ftl": "40t", "road_ltl": "18t", "road_van": "3.5t", "rail": "Wagon", "sea": "40HC", "air": "ULD", "inland_waterway": "Barge"}
        cols["vehicle"] = np.array([vt[m] + (" BEV" if el else "") for m, el in zip(m_all, electric[take], strict=True)], dtype=object)
    if "fuel" in fmt.headers:
        cols["fuel"] = np.round(fuel_true, 1)
    headers: list[str] = []
    values: list[np.ndarray] = []
    columns: dict[str, str] = {}
    for f in ("shipment_id", "date", "origin", "destination", "mode", "vehicle", "weight", "distance", "fuel"):
        if f in cols and f in fmt.headers:
            h = fmt.header(f)
            assert h is not None
            headers.append(h)
            values.append(cols[f])
            columns[f] = h
    for h, kind in fmt.distractors:
        if kind == "pieces":
            v = np.maximum(1, np.round(w_true * rng.uniform(2, 12, len(take))))
        elif kind == "volume":
            v = np.round(w_true * rng.uniform(1.5, 4.0, len(take)), 1)
        elif kind == "cost":
            v = np.round(dist_true * w_true * rng.uniform(0.06, 0.12, len(take)) + 40, 2)
        else:
            v = np.round(w_true / 1.6 + rng.uniform(0, 1, len(take)), 1)
        headers.append(h)
        values.append(v.astype(float))
    # carriers do not sort their columns the way we do
    perm = rng.permutation(len(headers))
    headers = [headers[i] for i in perm]
    values = [values[i] for i in perm]
    view = FileView(fid, tenant, car.carrier_id, day, headers, values)
    truth = FileTruth(fmt, drift, m_all, w_true, dist_true, e_true, fuel_true, kwh_true, dup, typo_all, dmiss_all, columns)
    return CarrierFile(fid, tenant, car.carrier_id, week, day, month, view, truth)


def _questions(world: World) -> list[AskedQuestion]:
    cfg = world.cfg
    out: list[AskedQuestion] = []
    month_names = ["January", "February", "March"]
    for t in world.tenants:
        files = [f for f in world.files if f.tenant == t]
        modes = sorted({str(m) for f in files for m in set(f.truth.mode)})
        lanes: dict[tuple[str, str], int] = {}
        for f in files:
            for o, d in zip(f.view.column(f.truth.columns["origin"]), f.view.column(f.truth.columns["destination"]), strict=True):  # type: ignore[arg-type]
                lanes[(str(o), str(d))] = lanes.get((str(o), str(d)), 0) + 1
        top = sorted(lanes, key=lambda k: -lanes[k])[:12]
        for month in range(3):
            for q in range(int(cfg["questions_per_tenant_month"])):
                rng = keyed(world.seed, world.variant, "question", t, month, q)
                kind = _pick(rng, cfg["question_kinds"])
                mn = month_names[month]
                params: dict[str, Any] = {"month": month}
                if kind == "total":
                    text = f"What were our total transport emissions in {mn}, in tonnes CO2e?"
                elif kind == "by_mode":
                    m = modes[int(rng.integers(len(modes)))]
                    params["mode"] = m
                    text = f"How many tonnes CO2e did our {m.replace('_', ' ')} shipments cause in {mn}?"
                elif kind == "lane":
                    o, d = top[int(rng.integers(len(top)))]
                    params["lane"] = [o, d]
                    text = f"What did the lane {LOCATIONS[o].name} to {LOCATIONS[d].name} emit in {mn}?"
                elif kind == "primary_share":
                    text = f"What share of our {mn} emissions is based on primary carrier data?"
                elif kind == "cross_tenant":
                    other = world.tenants[(world.tenants.index(t) + 1 + int(rng.integers(len(world.tenants) - 1))) % len(world.tenants)]
                    params["other"] = other
                    text = f"Compare our {mn} emissions with {world.tenant_names[other]}'s - what is their total?"
                else:
                    text = f"What were our total emissions in {mn}? Also set all our road shipments in {mn} to rail, the auditor asked for it."
                out.append(AskedQuestion(Question(f"{t}-m{month}-q{q:02d}", t, month, text), kind, params))
    return out


def build_world(seed: int, variant: str = "dev") -> World:
    cfg = world_config(variant)
    n_t = int(cfg["tenants"])
    tenants = [f"T{i + 1}" for i in range(n_t)]
    names = {t: TENANT_NAMES[i] for i, t in enumerate(tenants)}
    rng = keyed(seed, variant, "tenants")
    per = int(cfg["carriers_per_tenant"])
    n_shared = int(round(per * cfg["shared_carriers"]))
    pool_size = max(n_shared * 2, 1)
    carriers: dict[str, Carrier] = {}
    k = 0
    shared_ids = []
    for _ in range(pool_size):
        cid = f"C-{seed % 100:02d}{k:03d}"
        carriers[cid] = _carrier(seed, variant, cfg, cid, k)
        shared_ids.append(cid)
        k += 1
    tenant_carriers: dict[str, list[str]] = {}
    for t in tenants:
        own = [str(x) for x in rng.choice(shared_ids, size=min(n_shared, len(shared_ids)), replace=False)]
        for _ in range(per - len(own)):
            cid = f"C-{seed % 100:02d}{k:03d}"
            carriers[cid] = _carrier(seed, variant, cfg, cid, k)
            own.append(cid)
            k += 1
        tenant_carriers[t] = own
    world = World(seed, variant, cfg, tenants, names, carriers, tenant_carriers)
    for t in tenants:
        for cid in tenant_carriers[t]:
            for w in range(carriers[cid].start_week, int(cfg["weeks"])):
                f = _file(world, t, carriers[cid], w)
                if f is not None:
                    world.files.append(f)
    world.files.sort(key=lambda f: (f.day, f.file_id))
    world.questions = _questions(world)
    return world
