"""The truth stays in the world, and the world does not read the platform's settings."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "eap"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            out.add("." * node.level + mod)
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
    return out


def _files(*dirs: str) -> list[Path]:
    return [p for d in dirs for p in (SRC / d).rglob("*.py")]


def test_platform_service_and_agents_never_import_the_world_or_the_simulation() -> None:
    for path in _files("platform", "service", "agents"):
        for imp in _imports(path):
            assert "world" not in imp and "sim" not in imp.split("."), f"{path.name} imports {imp}"


def test_the_world_does_not_read_platform_settings() -> None:
    for path in _files("world"):
        text = path.read_text(encoding="utf-8")
        assert "platform.yml" not in text and "config.platform(" not in text, path.name
        for imp in _imports(path):
            assert "platform" not in imp, f"{path.name} imports {imp}"


def test_only_world_sim_and_evals_touch_truth_fields() -> None:
    for path in _files("platform", "service", "agents", "lab"):
        text = path.read_text(encoding="utf-8")
        assert ".truth." not in text or path.parent.name == "lab", path.name
