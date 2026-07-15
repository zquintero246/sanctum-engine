"""Tests for AetherSchema, Conduits, and reducers.

Covers accumulation through append across Sigils and supersteps,
deterministic same-superstep delta ordering, schema enforcement naming the
offending Sigil, custom reducers, and the Annotated declaration sugar.
"""

from typing import Annotated, Any

import pytest

from sanctum import END, AetherSchema, AetherValidationError, Conduit, Ritual
from sanctum.aether import add, append, merge_dict, overwrite

Aether = dict[str, Any]


async def test_append_accumulates_across_sigils_and_supersteps() -> None:
    schema = AetherSchema(
        {
            "messages": Conduit(reducer=append),
            "turns": Conduit(reducer=add),
        }
    )
    ritual = Ritual(schema)
    ritual.add_sigil("call", lambda aether: {"messages": ["called"], "turns": 1})
    ritual.add_sigil("answer", lambda aether: {"messages": ["answered"], "turns": 1})
    ritual.set_entry_point("call")
    ritual.add_edge("call", "answer")
    ritual.add_conditional_edge(
        "answer", lambda aether: END if aether["turns"] >= 4 else "call"
    )

    result = await ritual.compile().ainvoke({"messages": [], "turns": 0})
    assert result["messages"] == ["called", "answered", "called", "answered"]
    assert result["turns"] == 4


def test_same_superstep_deltas_apply_in_sigil_insertion_order() -> None:
    """Simulates a parallel superstep: two Sigils write to the same Conduits.

    apply_deltas receives the deltas in Sigil insertion order (as the
    engine will pass them once supersteps run Sigils in parallel) and must
    fold them deterministically: append keeps both in order, overwrite
    keeps the last.
    """
    schema = AetherSchema(
        {
            "messages": Conduit(reducer=append),
            "verdict": Conduit(),  # overwrite by default
        }
    )
    aether = {"messages": ["opening"], "verdict": "pending"}
    deltas = [
        ("first_bound", {"messages": ["from first"], "verdict": "first"}),
        ("second_bound", {"messages": ["from second"], "verdict": "second"}),
    ]

    merged = schema.apply_deltas(aether, deltas)
    assert merged["messages"] == ["opening", "from first", "from second"]
    assert merged["verdict"] == "second"
    # The source aether is never mutated.
    assert aether == {"messages": ["opening"], "verdict": "pending"}


async def test_delta_outside_schema_names_offending_sigil() -> None:
    schema = AetherSchema({"sanctioned": Conduit()})
    ritual = Ritual(schema)
    ritual.add_sigil("wayward", lambda aether: {"forbidden": True})
    ritual.set_entry_point("wayward")
    ritual.add_edge("wayward", END)

    with pytest.raises(AetherValidationError, match="'wayward'.*'forbidden'"):
        await ritual.compile().ainvoke({"sanctioned": 0})


async def test_input_outside_schema_is_rejected() -> None:
    schema = AetherSchema({"sanctioned": Conduit()})
    ritual = Ritual(schema)
    ritual.add_sigil("noop", lambda aether: {})
    ritual.set_entry_point("noop")
    ritual.add_edge("noop", END)

    with pytest.raises(AetherValidationError, match="input.*'?intruder'?"):
        await ritual.compile().ainvoke({"sanctioned": 0, "intruder": 1})


async def test_custom_reducer_keeps_maximum() -> None:
    schema = AetherSchema(
        {"peak": Conduit(reducer=lambda current, update: max(current, update))}
    )
    ritual = Ritual(schema)
    ritual.add_sigil("measure_low", lambda aether: {"peak": 3})
    ritual.add_sigil("measure_high", lambda aether: {"peak": 7})
    ritual.add_sigil("measure_mid", lambda aether: {"peak": 5})
    ritual.set_entry_point("measure_low")
    ritual.add_edge("measure_low", "measure_high")
    ritual.add_edge("measure_high", "measure_mid")
    ritual.add_edge("measure_mid", END)

    result = await ritual.compile().ainvoke({"peak": 0})
    assert result["peak"] == 7


def test_merge_dict_reducer_shallow_merges() -> None:
    schema = AetherSchema({"profile": Conduit(reducer=merge_dict)})
    merged = schema.apply_deltas(
        {"profile": {"kept": 1, "replaced": 1}},
        [("scribe", {"profile": {"replaced": 2, "added": 3}})],
    )
    assert merged["profile"] == {"kept": 1, "replaced": 2, "added": 3}


def test_annotated_sugar_builds_conduits() -> None:
    class ChantAether:
        messages: Annotated[list, append]
        turns: Annotated[int, add]
        verdict: str  # plain annotation -> overwrite

    schema = AetherSchema.from_class(ChantAether)
    assert schema.conduits["messages"].reducer is append
    assert schema.conduits["turns"].reducer is add
    assert schema.conduits["verdict"].reducer is overwrite


def test_annotated_values_accepted_in_constructor() -> None:
    schema = AetherSchema({"messages": Annotated[list, append], "verdict": str})
    assert schema.conduits["messages"].reducer is append
    assert schema.conduits["verdict"].reducer is overwrite
