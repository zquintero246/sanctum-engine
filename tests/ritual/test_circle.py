"""Tests for Circles (``circle(rite)`` — a compiled Rite as one Sigil).

Covers input/output projection, echoed inner Omens (CircleEchoed), a
summoned Entity mounted as a node of a larger pipeline, and failure
propagation into the outer Sigil's error handling.
"""

from typing import Any

import pytest

from sanctum import (
    END,
    AetherSchema,
    Conduit,
    Ritual,
    SigilExecutionError,
    Tome,
    circle,
    spell,
    summon,
)
from sanctum.omens import CircleEchoed, RiteManifested
from sanctum.oracle import OracleResponse, ScriptedOracle, SpellCall

Aether = dict[str, Any]


def _inner_doubler():
    inner = Ritual()
    inner.add_sigil("double", lambda aether: {"doubled": aether["n"] * 2})
    inner.set_entry_point("double")
    inner.add_edge("double", END)
    return inner.compile()


def _outer_with(circle_fn):
    outer = Ritual(AetherSchema({"x": Conduit(), "y": Conduit()}))
    outer.add_sigil("prepare", lambda aether: {"x": aether["x"] + 1})
    outer.add_sigil("sub", circle_fn)
    outer.set_entry_point("prepare")
    outer.add_edge("prepare", "sub")
    outer.add_edge("sub", END)
    return outer.compile()


async def test_circle_projects_input_and_output() -> None:
    rite = _outer_with(
        circle(
            _inner_doubler(),
            name="doubler",
            input_map={"n": "x"},
            output_map={"y": "doubled"},
        )
    )
    result = await rite.ainvoke({"x": 20})
    # prepare: x=21; circle: n=21 -> doubled=42 -> projected to y.
    assert result == {"x": 21, "y": 42}


async def test_circle_echoes_inner_omens() -> None:
    rite = _outer_with(
        circle(
            _inner_doubler(),
            name="doubler",
            input_map={"n": "x"},
            output_map={"y": "doubled"},
        )
    )
    echoed = []
    async for omen in rite.astream({"x": 1}, mode="omens"):
        if isinstance(omen, CircleEchoed):
            echoed.append(omen)
    assert echoed and all(o.circle == "doubler" for o in echoed)
    # The inner lifecycle is visible, including its manifestation.
    assert any(isinstance(o.omen, RiteManifested) for o in echoed)


async def test_summoned_entity_as_a_node() -> None:
    @spell
    def scry(topic: str) -> str:
        """Reveal one fact about a topic."""
        return f"the {topic} bears seven seals"

    tome = Tome()
    tome.register(scry)
    oracle = ScriptedOracle(
        script=[
            OracleResponse(
                text="",
                spell_calls=[SpellCall(spell="scry", arguments={"topic": "door"})],
            ),
            "Report: the door bears seven seals.",
        ]
    )
    entity = summon(oracle, tome, role="You are a scryer.")

    outer = Ritual(AetherSchema({"quest": Conduit(), "report": Conduit()}))
    outer.add_sigil(
        "scryer",
        circle(
            entity,
            name="scryer",
            input_map=lambda aether: {
                "messages": [{"role": "user", "content": aether["quest"]}]
            },
            output_map=lambda final: {
                "report": final["messages"][-1]["content"]
            },
        ),
    )
    outer.set_entry_point("scryer")
    outer.add_edge("scryer", END)

    result = await outer.compile().ainvoke({"quest": "study the door"})
    assert result["report"] == "Report: the door bears seven seals."
    assert len(oracle.calls) == 2  # think -> cast -> conclude


async def test_inner_failure_surfaces_as_outer_sigil_error() -> None:
    def explode(aether: Aether) -> Aether:
        raise RuntimeError("the inner circle broke")

    inner = Ritual()
    inner.add_sigil("explode", explode)
    inner.set_entry_point("explode")
    inner.add_edge("explode", END)

    outer = Ritual()
    outer.add_sigil("sub", circle(inner.compile(), name="doomed"))
    outer.set_entry_point("sub")
    outer.add_edge("sub", END)

    with pytest.raises(SigilExecutionError) as caught:
        await outer.compile().ainvoke({})
    # Attributed to the Circle's own Sigil (so its policy governs), while
    # the message still names the inner culprit.
    assert caught.value.sigil == "sub"
    assert "inner Sigil 'explode'" in str(caught.value.__cause__)
