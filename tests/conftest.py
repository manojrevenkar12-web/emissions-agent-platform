from __future__ import annotations

import pytest

from eap import config
from eap.world.world import World, build_world


@pytest.fixture(scope="session")
def world() -> World:
    return build_world(7, "tiny")


@pytest.fixture(scope="session")
def cfg() -> dict:
    return config.platform()
