"""Tests for conditional edges, cycles, and the recursion limit.

Covers router-based branching, the canonical agentic cycle
(think -> act -> think -> ... -> END), exact recursion-limit enforcement,
and path_map translation.
"""

from typing import Any

import pytest

from sanctum import END, RecursionLimitError, Ritual, RitualValidationError

Aether = dict[str, Any]


def make_branching_ritual(path_map: dict[str, str] | None = None) -> Ritual:
    """A gate Sigil whose router sends the flow to 'bless' or 'banish'."""
    ritual = Ritual()
    ritual.add_sigil("gate", lambda aether: {"gated": True})
    ritual.add_sigil("bless", lambda aether: {"outcome": "blessed"})
    ritual.add_sigil("banish", lambda aether: {"outcome": "banished"})
    ritual.set_entry_point("gate")
    if path_map is None:
        ritual.add_conditional_edge(
            "gate", lambda aether: "bless" if aether["worthy"] else "banish"
        )
    else:
        ritual.add_conditional_edge(
            "gate",
            lambda aether: "accept" if aether["worthy"] else "reject",
            path_map=path_map,
        )
    ritual.add_edge("bless", END)
    ritual.add_edge("banish", END)
    return ritual


async def test_router_branches_on_aether_field() -> None:
    rite = make_branching_ritual().compile()
    blessed = await rite.ainvoke({"worthy": True})
    banished = await rite.ainvoke({"worthy": False})
    assert blessed == {"worthy": True, "gated": True, "outcome": "blessed"}
    assert banished == {"worthy": False, "gated": True, "outcome": "banished"}


async def test_canonical_agentic_cycle_terminates() -> None:
    def think(aether: Aether) -> Aether:
        return {"thoughts": aether["thoughts"] + 1}

    def act(aether: Aether) -> Aether:
        return {"actions": aether["actions"] + 1}

    def router(aether: Aether) -> str:
        return "act" if aether["thoughts"] < 3 else END

    ritual = Ritual()
    ritual.add_sigil("think", think)
    ritual.add_sigil("act", act)
    ritual.set_entry_point("think")
    ritual.add_conditional_edge("think", router)
    ritual.add_edge("act", "think")

    result = await ritual.compile().ainvoke({"thoughts": 0, "actions": 0})
    assert result == {"thoughts": 3, "actions": 2}


async def test_unbounded_cycle_raises_at_exact_recursion_limit() -> None:
    executions: list[int] = []

    def chant(aether: Aether) -> Aether:
        executions.append(1)
        return {"count": aether["count"] + 1}

    ritual = Ritual()
    ritual.add_sigil("chant", chant)
    ritual.set_entry_point("chant")
    ritual.add_edge("chant", "chant")

    rite = ritual.compile(recursion_limit=5)
    with pytest.raises(RecursionLimitError) as excinfo:
        await rite.ainvoke({"count": 0}, invocation_id="inv-endless")

    assert len(executions) == 5
    message = str(excinfo.value)
    assert "5" in message
    assert "inv-endless" in message
    assert "chant" in message


async def test_path_map_translates_router_result() -> None:
    rite = make_branching_ritual(
        path_map={"accept": "bless", "reject": "banish"}
    ).compile()
    assert (await rite.ainvoke({"worthy": True}))["outcome"] == "blessed"
    assert (await rite.ainvoke({"worthy": False}))["outcome"] == "banished"


async def test_router_result_missing_from_path_map_raises() -> None:
    ritual = Ritual()
    ritual.add_sigil("gate", lambda aether: {})
    ritual.add_sigil("bless", lambda aether: {})
    ritual.set_entry_point("gate")
    ritual.add_conditional_edge(
        "gate", lambda aether: "unmapped", path_map={"accept": "bless"}
    )
    ritual.add_edge("bless", END)

    with pytest.raises(ValueError, match="'unmapped'.*path_map"):
        await ritual.compile().ainvoke({})


def test_compile_fails_on_path_map_to_unknown_sigil() -> None:
    ritual = Ritual()
    ritual.add_sigil("gate", lambda aether: {})
    ritual.set_entry_point("gate")
    ritual.add_conditional_edge(
        "gate", lambda aether: "accept", path_map={"accept": "phantom"}
    )
    with pytest.raises(RitualValidationError, match="unknown Sigil 'phantom'"):
        ritual.compile()
