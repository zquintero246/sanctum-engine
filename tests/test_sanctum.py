"""Smoke tests: the Sanctum stands and every chamber is reachable.

Verifies the package and each submodule import cleanly, with no engine
logic exercised.
"""

import importlib

import pytest

import sanctum

SUBMODULES = [
    "sanctum.ritual",
    "sanctum.aether",
    "sanctum.codex",
    "sanctum.omens",
    "sanctum.oracle",
    "sanctum.grimoire",
    "sanctum.wards",
]


def test_version() -> None:
    assert sanctum.__version__ == "0.2.0"


@pytest.mark.parametrize("name", SUBMODULES)
def test_submodule_imports(name: str) -> None:
    assert importlib.import_module(name) is not None
