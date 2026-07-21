"""Tests for wait-all fan-in (``add_sigil(..., join="all")``).

Covers the barrier over uneven branch lengths (the join runs exactly once,
after the slowest branch), join state persisted in Seal metadata and
restored on resumption, the SigilJoinError raised when a feeding branch
never arrives, and the compile-time validations that keep joins sound.
"""

from typing import Any

import pytest

from sanctum import (
    END,
    AetherSchema,
    Conduit,
    Ritual,
    RitualValidationError,
    SigilPolicy,
)
from sanctum.aether import append
from sanctum.codex import MemoryCodex
from sanctum.ritual.errors import SigilJoinError

Aether = dict[str, Any]


def writes(key: str, value: Any):
    def sigil(aether: Aether) -> Aether:
        return {key: [value]}

    return sigil


def _uneven_ritual(runs: list[str], join: str = "all") -> Ritual:
    """START -> split -> {fast, slow_1 -> slow_2} -> merge -> END."""
    schema = AetherSchema({"trail": Conduit(reducer=append)})
    ritual = Ritual(schema)
    ritual.add_sigil("split", writes("trail", "split"))
    ritual.add_sigil("fast", writes("trail", "fast"))
    ritual.add_sigil("slow_1", writes("trail", "slow_1"))
    ritual.add_sigil("slow_2", writes("trail", "slow_2"))

    def merge(aether: Aether) -> Aether:
        runs.append("merge")
        return {"trail": ["merge"]}

    ritual.add_sigil("merge", merge, join=join)
    ritual.set_entry_point("split")
    ritual.add_edge("split", "fast")
    ritual.add_edge("split", "slow_1")
    ritual.add_edge("slow_1", "slow_2")
    ritual.add_edge("fast", "merge")
    ritual.add_edge("slow_2", "merge")
    ritual.add_edge("merge", END)
    return ritual


async def test_join_all_waits_for_the_slowest_branch() -> None:
    runs: list[str] = []
    result = await _uneven_ritual(runs).compile().ainvoke({"trail": []})
    # The barrier holds: merge runs exactly once, after slow_2 arrives.
    assert runs == ["merge"]
    assert result["trail"] == ["split", "fast", "slow_1", "slow_2", "merge"]


async def test_join_any_runs_twice_on_uneven_branches() -> None:
    # The contrast case documenting why join="all" exists.
    runs: list[str] = []
    await _uneven_ritual(runs, join="any").compile().ainvoke({"trail": []})
    assert runs == ["merge", "merge"]


async def test_join_pending_survives_seal_and_resumption() -> None:
    runs: list[str] = []
    codex = MemoryCodex()
    rite = _uneven_ritual(runs).compile(codex=codex)
    await rite.ainvoke({"trail": []}, invocation_id="inv-join")

    history = await codex.list("inv-join")
    # Superstep 2 ran {fast, slow_1}: fast already signaled merge, slow_2
    # has not — the Seal records the barrier mid-gather.
    mid = history[1]
    assert mid.superstep == 2
    assert mid.metadata["__join_pending__"] == {"merge": ["fast"]}

    # Time-travel from that Seal: the barrier's progress is restored, so
    # merge still waits for slow_2 and runs exactly once more.
    runs.clear()
    result = await rite.ainvoke(invocation_id="inv-join", seal_id=mid.seal_id)
    assert runs == ["merge"]
    assert result["trail"] == ["split", "fast", "slow_1", "slow_2", "merge"]


async def test_unsatisfied_join_raises_sigil_join_error() -> None:
    # gate's router deserts the left branch, so left — a static
    # predecessor of the join — never runs and the barrier cannot close.
    ritual = Ritual()
    ritual.add_sigil("gate", lambda aether: {})
    ritual.add_sigil("left", lambda aether: {})
    ritual.add_sigil("right", lambda aether: {})
    ritual.add_sigil("merge", lambda aether: {}, join="all")
    ritual.add_sigil("elsewhere", lambda aether: {})
    ritual.set_entry_point("gate")
    ritual.set_entry_point("right")
    ritual.add_edge("left", "merge")
    ritual.add_edge("right", "merge")
    ritual.add_edge("merge", END)
    ritual.add_edge("elsewhere", END)
    ritual.add_conditional_edge("gate", lambda aether: "elsewhere")

    with pytest.raises(SigilJoinError) as caught:
        await ritual.compile().ainvoke({})
    assert caught.value.pending == {"merge": ["left"]}
    assert "'merge' still waits for ['left']" in str(caught.value)


async def test_router_may_not_target_a_join_all_sigil() -> None:
    ritual = Ritual()
    ritual.add_sigil("gate", lambda aether: {})
    ritual.add_sigil("merge", lambda aether: {}, join="all")
    ritual.add_sigil("feeder", lambda aether: {})
    ritual.set_entry_point("gate")
    ritual.set_entry_point("feeder")
    ritual.add_edge("feeder", "merge")
    ritual.add_edge("merge", END)
    ritual.add_conditional_edge("gate", lambda aether: "merge")

    with pytest.raises(ValueError, match="join='all'"):
        await ritual.compile().ainvoke({})


def test_compile_rejects_unsound_joins() -> None:
    with pytest.raises(RitualValidationError, match="join must be"):
        Ritual().add_sigil("merge", lambda aether: {}, join="most")

    # join="all" without a static incoming edge cannot ever fire.
    lonely = Ritual()
    lonely.add_sigil("alone", lambda aether: {})
    lonely.add_sigil("merge", lambda aether: {}, join="all")
    lonely.set_entry_point("alone")
    lonely.add_conditional_edge("alone", lambda aether: END, path_map={END: END})
    lonely.add_edge("merge", END)
    with pytest.raises(RitualValidationError, match="static incoming edge"):
        lonely.compile()

    # A path_map target pointing at the join is rejected at compile time.
    mapped = Ritual()
    mapped.add_sigil("gate", lambda aether: {})
    mapped.add_sigil("feeder", lambda aether: {})
    mapped.add_sigil("merge", lambda aether: {}, join="all")
    mapped.set_entry_point("gate")
    mapped.set_entry_point("feeder")
    mapped.add_edge("feeder", "merge")
    mapped.add_edge("merge", END)
    mapped.add_conditional_edge(
        "gate", lambda aether: "go", path_map={"go": "merge"}
    )
    with pytest.raises(RitualValidationError, match="wait-all"):
        mapped.compile()

    # An on_error fallback may not name a join="all" Sigil.
    fallback = Ritual()
    fallback.add_sigil(
        "risky", lambda aether: {}, policy=SigilPolicy(on_error="merge")
    )
    fallback.add_sigil("merge", lambda aether: {}, join="all")
    fallback.set_entry_point("risky")
    fallback.add_edge("risky", "merge")
    fallback.add_edge("merge", END)
    with pytest.raises(RitualValidationError, match="fallback"):
        fallback.compile()
