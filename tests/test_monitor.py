from __future__ import annotations

from eap.platform.monitor import Cusum


def test_no_alarm_at_the_baseline_rate_and_an_alarm_after_a_rise() -> None:
    m = Cusum(delta=0.22, h=2.5, baseline_obs=80, pin_days=10)
    pattern = [True, True, False] * 60  # 67% failures, the normal rate
    for i, x in enumerate(pattern):
        m.observe(i // 3, x)
    assert m.alarms == []
    for i in range(30):
        m.observe(60 + i // 2, True)
    assert m.alarms and m.pinned(m.alarms[0] + 1)
