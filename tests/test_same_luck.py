"""Same luck for every design: a draw depends on its key only, and a run is deterministic."""

from __future__ import annotations

import numpy as np

from eap import config
from eap.sim.designs import run_design
from eap.sim.evaluate import design_metrics


def test_designs_that_make_the_same_call_get_the_same_draw(world, cfg) -> None:
    d = config.designs()["designs"]
    a = run_design(world, "platform", d["platform"], cfg).luck.record()
    b = run_design(world, "no_memory", d["no_memory"], cfg).luck.record()
    common = set(a) & set(b)
    assert len(common) > 50
    assert all(np.array_equal(a[k], b[k]) for k in common)


def test_a_run_is_deterministic(world, cfg) -> None:
    d = config.designs()["designs"]
    m1 = design_metrics(world, run_design(world, "platform", d["platform"], cfg))
    m2 = design_metrics(world, run_design(world, "platform", d["platform"], cfg))
    assert m1 == m2


def test_a_stronger_model_is_right_whenever_a_weaker_one_is(world) -> None:
    from eap.platform.profile import build_profile
    from eap.world.luck import Luck
    from eap.world.model_sim import ReplyBook, SimModel
    from eap.world.people import Desk

    luck = Luck(world.seed, world.variant)
    model, desk = SimModel(world, luck, ReplyBook()), Desk(world, luck, ReplyBook())
    for f in world.files[:30]:
        truth = desk._true(f.view).decisions()
        p = build_profile(f.view, config.platform()).text
        weak = model.propose_mapping(f.view, p, "fast").value.decisions()
        strong = model.propose_mapping(f.view, p, "frontier").value.decisions()
        for k, v in truth.items():
            if weak.get(k) == v and f.day >= 0 and not (world.cfg["degradation"]["start_day"] <= f.day < world.cfg["degradation"]["end_day"]):
                assert strong.get(k) == v, (f.file_id, k)
