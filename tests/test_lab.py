"""The held-out rule and the eval gate's statistics."""

from __future__ import annotations

import numpy as np
import pytest

from eap.evals.suite import _paired_ci
from eap.lab import study


def test_the_held_out_run_refuses_to_run_twice(tmp_path, monkeypatch) -> None:
    lock = tmp_path / "heldout.lock"
    lock.write_text("{}")
    monkeypatch.setattr(study, "LOCK", lock)
    with pytest.raises(study.HeldOutLocked):
        study.run_heldout_once()


def test_the_paired_interval_sees_a_real_regression() -> None:
    a = np.ones(400)
    b = np.ones(400)
    b[:40] = 0
    mean, lo, hi = _paired_ci(a, b, 1)
    assert np.isclose(mean, -0.1) and hi < 0


def test_gates_read_the_designs() -> None:
    from eap import config

    designs = {"platform": _m(), "status_quo": _m(minutes=10000, share=0.1)}
    out = study.check_gates(designs, config.gates())
    assert out["platform_pass"], [g for g in out["platform"] if not g["pass"]]


def _m(minutes: float = 100, share: float = 0.3) -> dict:
    return {
        "tenant_month_error_p95": 0.05,
        "gross_row_errors_per_10k": 1,
        "analyst_minutes": minutes,
        "llm_cost_eur_per_1k": 0.01,
        "false_primary_rows": 0,
        "emails_unapproved": 0,
        "emails_to_wrong_company": 0,
        "injected_replies_acted_on": 0,
        "cross_tenant_leaks": 0,
        "unauthorised_writes": 0,
        "answers_wrong_number_per_100": 0,
        "primary_share_road": share,
    }
