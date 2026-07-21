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


async def test_sigil_receives_invocation_context() -> None:
    from sanctum import InvocationContext

    seen: list[Any] = []

    def observer(aether: Aether, invocation=None) -> Aether:
        seen.append(invocation)
        return {}

    ritual = Ritual()
    ritual.add_sigil("observer", observer)
    ritual.set_entry_point("observer")
    ritual.add_edge("observer", END)
    await ritual.compile().ainvoke({}, invocation_id="inv-ctx")

    assert seen and isinstance(seen[0], InvocationContext)
    assert seen[0].invocation_id == "inv-ctx"
    assert seen[0].superstep == 1


async def test_inner_interrupt_resumes_inside_the_circle() -> None:
    from sanctum import Interrupt, interrupt
    from sanctum.codex import MemoryCodex

    prelude_runs: list[str] = []

    def prelude(aether: Aether) -> Aether:
        prelude_runs.append("ran")
        return {"prepared": True}

    def gate(aether: Aether) -> Aether:
        if aether.get("approved"):
            return {"verdict": "blessed"}
        interrupt("the gate awaits approval")

    inner = Ritual()
    inner.add_sigil("prelude", prelude)
    inner.add_sigil("gate", gate)
    inner.set_entry_point("prelude")
    inner.add_edge("prelude", "gate")
    inner.add_edge("gate", END)
    inner_rite = inner.compile(codex=MemoryCodex())

    outer = Ritual()
    outer.add_sigil(
        "chamber",
        circle(
            inner_rite,
            name="chamber",
            output_map={"verdict": "verdict"},
            resume_map={"approved": "approved"},
        ),
    )
    outer.set_entry_point("chamber")
    outer.add_edge("chamber", END)
    outer_rite = outer.compile(codex=MemoryCodex())

    with pytest.raises(Interrupt) as caught:
        await outer_rite.ainvoke({}, invocation_id="outer-1")
    # The pause names the full path into the circle.
    assert caught.value.sigil == "chamber:gate"

    result = await outer_rite.ainvoke(
        invocation_id="outer-1", updates={"approved": True}
    )
    assert result["verdict"] == "blessed"
    # The inner Invocation RESUMED: its prelude did not run a second time.
    assert prelude_runs == ["ran"]


async def test_completed_inner_invocations_start_fresh_next_activation() -> None:
    from sanctum.codex import MemoryCodex

    runs: list[int] = []

    def work(aether: Aether) -> Aether:
        runs.append(aether["round"])
        return {"echo": aether["round"]}

    inner = Ritual()
    inner.add_sigil("work", work)
    inner.set_entry_point("work")
    inner.add_edge("work", END)
    inner_rite = inner.compile(codex=MemoryCodex())

    outer = Ritual()
    outer.add_sigil("tick", lambda aether: {"round": aether.get("round", 0) + 1})
    outer.add_sigil(
        "sub",
        circle(inner_rite, name="sub", input_map={"round": "round"},
               output_map={"echo": "echo"}),
    )
    outer.set_entry_point("tick")
    outer.add_edge("tick", "sub")
    outer.add_conditional_edge(
        "sub", lambda aether: END if aether["round"] >= 2 else "tick"
    )
    result = await outer.compile().ainvoke({}, invocation_id="outer-loop")

    # Two activations, each a FRESH inner run (no stale resumption).
    assert runs == [1, 2]
    assert result["echo"] == 2
