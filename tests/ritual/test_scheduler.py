"""Tests for the BSP scheduler.

Covers static fan-out, fan-in with "any" semantics (coalesced execution),
real concurrency within a superstep, and failure wrapping in
SigilExecutionError.
"""

import asyncio
import time
from typing import Any

import pytest

from sanctum import END, AetherSchema, Conduit, Ritual, SigilExecutionError
from sanctum.aether import append

Aether = dict[str, Any]


async def test_fan_out_and_fan_in_collect_all_results() -> None:
    gather_runs: list[str] = []

    def scry(omen: str):
        def sigil(aether: Aether) -> Aether:
            return {"scryings": [omen]}

        return sigil

    def gather(aether: Aether) -> Aether:
        gather_runs.append("gather")
        return {"summary": "|".join(aether["scryings"])}

    schema = AetherSchema(
        {"scryings": Conduit(reducer=append), "summary": Conduit()}
    )
    ritual = Ritual(schema)
    ritual.add_sigil("split", lambda aether: {})
    ritual.add_sigil("scry_air", scry("air"))
    ritual.add_sigil("scry_salt", scry("salt"))
    ritual.add_sigil("scry_flame", scry("flame"))
    ritual.add_sigil("gather", gather)
    ritual.set_entry_point("split")
    ritual.add_edge("split", "scry_air")
    ritual.add_edge("split", "scry_salt")
    ritual.add_edge("split", "scry_flame")
    ritual.add_edge("scry_air", "gather")
    ritual.add_edge("scry_salt", "gather")
    ritual.add_edge("scry_flame", "gather")
    ritual.add_edge("gather", END)

    result = await ritual.compile().ainvoke({"scryings": []})
    # Deltas apply in Sigil insertion order, so the appended order is fixed.
    assert result["scryings"] == ["air", "salt", "flame"]
    assert result["summary"] == "air|salt|flame"
    # Fan-in "any" semantics: three activations in the same superstep
    # coalesce into a single execution of the gathering Sigil.
    assert gather_runs == ["gather"]


async def test_parallel_sigils_run_concurrently() -> None:
    async def linger(aether: Aether) -> Aether:
        await asyncio.sleep(0.1)
        return {"marks": ["done"]}

    schema = AetherSchema({"marks": Conduit(reducer=append)})
    ritual = Ritual(schema)
    for name in ("first", "second", "third"):
        ritual.add_sigil(name, linger)
        ritual.set_entry_point(name)
        ritual.add_edge(name, END)

    rite = ritual.compile()
    started = time.perf_counter()
    result = await rite.ainvoke({"marks": []})
    elapsed = time.perf_counter() - started

    assert result["marks"] == ["done", "done", "done"]
    # Three 0.1s Sigils in one superstep must overlap, not run back to back.
    assert elapsed < 0.25


async def test_sigil_failure_wraps_in_sigil_execution_error() -> None:
    async def steady(aether: Aether) -> Aether:
        await asyncio.sleep(0.05)
        return {"steady": True}

    def doomed(aether: Aether) -> Aether:
        raise ValueError("the stars are wrong")

    ritual = Ritual()
    ritual.add_sigil("steady", steady)
    ritual.add_sigil("doomed", doomed)
    ritual.set_entry_point("steady")
    ritual.set_entry_point("doomed")
    ritual.add_edge("steady", END)
    ritual.add_edge("doomed", END)

    with pytest.raises(SigilExecutionError) as excinfo:
        await ritual.compile().ainvoke({"omens": 0}, invocation_id="inv-doom")

    error = excinfo.value
    assert error.sigil == "doomed"
    # The superstep was cancelled: no delta (not even steady's) was applied.
    assert error.aether == {"omens": 0}
    assert isinstance(error.__cause__, ValueError)
    assert "doomed" in str(error)
    assert "inv-doom" in str(error)
