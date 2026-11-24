"""Writes the demo fixtures the service loads (data/demo): a carrier registry and one month of files from a
few carriers of the development world (seed 5). The service itself never imports the world."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from eap.domain import FileView
from eap.world.world import build_world

OUT = Path(__file__).resolve().parents[1] / "data" / "demo"


def main() -> None:
    w = build_world(5, "dev")
    shutil.rmtree(OUT / "files", ignore_errors=True)
    (OUT / "files").mkdir(parents=True)
    tenants = w.tenants[:2]
    used = {c for t in tenants for c in w.tenant_carriers[t]}
    reg = {k: v for k, v in w.registry().items() if k in used}
    (OUT / "registry.json").write_text(json.dumps([r.__dict__ for r in reg.values()], indent=1) + "\n", encoding="utf-8")
    n = 0
    for t in tenants:
        carriers = sorted(w.tenant_carriers[t], key=lambda c: (reg[c].kind not in ("road", "multimodal"), c))[:5]
        for cid in carriers:
            files = [f for f in w.files if f.tenant == t and f.carrier_id == cid and f.month == 0]
            if not files:
                continue
            first = files[0].view
            same = [f.view for f in files if f.view.headers == first.headers]
            import numpy as np

            cols = [np.concatenate([v.columns[i] for v in same]) for i in range(len(first.headers))]
            view = FileView(f"{t}__{cid}__0", t, cid, 0, first.headers, cols)
            (OUT / "files" / f"{t}__{cid}__0.csv").write_text(view.to_csv(), encoding="utf-8")
            n += 1
    print(f"wrote {n} files and {len(reg)} carriers")


if __name__ == "__main__":
    main()
