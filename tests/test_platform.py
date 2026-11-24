"""The platform end to end on the tiny world, and the switches that turn its safeguards off."""

from __future__ import annotations

from eap import config
from eap.domain import Question
from eap.platform.orchestrator import Switches
from eap.sim.designs import run_design, run_platform
from eap.sim.evaluate import design_metrics


def test_the_platform_beats_both_baselines_where_it_matters(world, cfg) -> None:
    d = config.designs()["designs"]
    plat = design_metrics(world, run_design(world, "platform", d["platform"], cfg))
    sq = design_metrics(world, run_design(world, "status_quo", d["status_quo"], cfg))
    alone = design_metrics(world, run_design(world, "model_alone", d["model_alone"], cfg))
    assert plat["analyst_minutes"] < 0.3 * sq["analyst_minutes"]
    assert plat["gross_row_errors_per_10k"] < alone["gross_row_errors_per_10k"]
    assert plat["cross_tenant_leaks"] == 0 and plat["unauthorised_writes"] == 0 and plat["emails_unapproved"] == 0
    assert alone["emails_unapproved"] > 0


def test_memory_is_used_and_turning_it_off_costs_reads(world, cfg) -> None:
    on = run_platform(world, "p", Switches.platform(), cfg)
    off = run_platform(world, "p", Switches.platform(["memory"]), cfg)
    assert sum(o.memory_hit for o in on.outcomes) > 0
    assert sum(o.reads for o in off.outcomes) > sum(o.reads for o in on.outcomes)


def test_cross_tenant_questions_are_refused_and_writes_blocked(world, cfg) -> None:
    run = run_platform(world, "p", Switches.platform(), cfg)
    for q in run.qa:
        if q.kind == "cross_tenant":
            assert q.used_tenant in (None, q.tenant)
        assert q.writes == 0


def test_an_unknown_switch_is_an_error() -> None:
    import pytest

    with pytest.raises(ValueError):
        Switches.platform(["no_such_safeguard"])


def test_the_local_model_maps_a_clean_file(cfg) -> None:
    from eap.domain import CarrierRecord, FileView
    from eap.platform.local_model import LocalModel
    from eap.platform.orchestrator import Platform
    from eap.service.api import DeskQueue, Outbox

    csv = "Sendungsnummer,Von,Nach,Gewicht (kg),Verkehrsträger,Datum,Entfernung (km)\n" + "".join(f"SH{i:04d},DEHAM,DEMUC,{12000 + i * 10},FTL,05.01.2026,{745 + i}\n" for i in range(30))
    reg = {"C1": CarrierRecord("C1", "Road one", "road", "c1@carrier.example")}
    p = Platform({**cfg, "routing": {k: "local" for k in cfg["routing"]}}, config.rbac(), reg, LocalModel(), DeskQueue(), Outbox())
    rows = p.process_file(FileView.from_csv(csv, file_id="f1", tenant="T1", carrier_id="C1"), 0)
    assert p.outcomes[-1].checks == {}
    assert 18 < rows.e_kg.sum() / 1000 < 25  # 30 x ~12 t x ~745 km x 78 g/tkm = ~21 t
    out = p.answer(Question("q1", "T1", 0, "What were our total transport emissions in January?"))
    assert out.result is not None and f"{out.result['value']:,.1f}" in out.text
