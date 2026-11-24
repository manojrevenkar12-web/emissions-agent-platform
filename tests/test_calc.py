"""The calculation in code: defaults, primary data, duplicates."""

from __future__ import annotations

import numpy as np

from eap.domain import FileView, Mapping
from eap.platform.calc import Ledger, calculate
from eap.platform.checks import apply_mapping

CSV = "Ref,Von,Nach,Gewicht (t),Mode,Datum\nSHa1,DEHAM,DEMUC,10,FTL,2026-01-05\nSHa2,DEHAM,DEMUC,10,FTL,2026-01-05\nSHa2,DEHAM,DEMUC,10,FTL,2026-01-05\n"


def _rows(cfg):
    v = FileView.from_csv(CSV, file_id="f", tenant="T1", carrier_id="C", day=0)
    m = Mapping({"shipment_id": "Ref", "date": "Datum", "origin": "Von", "destination": "Nach", "weight": "Gewicht (t)", "mode": "Mode"}, None, "t", None, {"FTL": "road_ftl"})
    p = apply_mapping(v, m, cfg["factors"])
    return calculate("f", "T1", "C", 0, 0, p, cfg, False)


def test_default_emissions_are_tonne_km_times_the_mode_factor(cfg) -> None:
    r = _rows(cfg)
    f = cfg["factors"]
    expected = 10 * r.dist_km[0] * f["default_intensity_g_tkm"]["road_ftl"] / 1000
    assert np.isclose(r.e_kg[0], expected)
    assert 600 < r.dist_km[0] < 800  # Hamburg-Munich great circle ~612 km x 1.2


def test_a_duplicate_row_counts_once(cfg) -> None:
    r = _rows(cfg)
    assert r.kept.tolist() == [True, True, False] and r.e_kg[2] == 0


def test_measured_fuel_replaces_the_default_only_when_plausible(cfg) -> None:
    led = Ledger()
    r = _rows(cfg)
    led.add(r)
    default = r.e_kg[0]
    plausible = default / cfg["factors"]["diesel_kg_per_l"] * 1.1
    done, refused = led.set_primary("T1", "C", {"SHa1": plausible, "SHa2": 0.0}, cfg, "reply")
    assert (done, refused) == (1, 1)
    assert r.primary[0] and not r.primary[1]
    assert np.isclose(r.e_kg[0], plausible * cfg["factors"]["diesel_kg_per_l"])
    assert led.query("T1", 0, "primary_share")["value"] > 0
