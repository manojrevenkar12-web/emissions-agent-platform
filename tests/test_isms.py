"""Every ISMS control names evidence that exists: a test function, a file or a CI step."""

from __future__ import annotations

import ast
from pathlib import Path

from eap import config

ROOT = Path(__file__).resolve().parents[1]


def _functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}


def test_every_control_has_evidence_that_exists() -> None:
    controls = config.controls()["controls"]
    assert len(controls) >= 10
    for c in controls:
        assert c["evidence"], c["id"]
        for ev in c["evidence"]:
            file, _, fn = ev.partition("::")
            path = ROOT / file
            assert path.exists(), f"{c['id']}: {file} missing"
            if fn:
                assert fn in _functions(path), f"{c['id']}: {ev} missing"
