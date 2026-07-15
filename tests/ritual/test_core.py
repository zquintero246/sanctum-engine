"""Tests for the minimal Ritual/Rite core.

Covers linear execution, mixed sync/async Sigils, compile-time validation
errors, and equivalence of the sync and async entry points.
"""

import asyncio
from typing import Any

import pytest

from sanctum import END, Ritual, RitualValidationError

Aether = dict[str, Any]


def make_linear_ritual() -> Ritual:
    """Three Sigils in a line: cleanse -> transmute -> seal."""
    ritual = Ritual()
    ritual.add_sigil("cleanse", lambda aether: {"text": aether["text"].strip()})
    ritual.add_sigil("transmute", lambda aether: {"text": aether["text"].upper()})
    ritual.add_sigil(
        "seal", lambda aether: {"length": len(aether["text"]), "sealed": True}
    )
    ritual.set_entry_point("cleanse")
    ritual.add_edge("cleanse", "transmute")
    ritual.add_edge("transmute", "seal")
    ritual.add_edge("seal", END)
    return ritual


async def test_linear_ritual_transforms_aether() -> None:
    rite = make_linear_ritual().compile()
    result = await rite.ainvoke({"text": "  lux aeterna  "})
    assert result == {"text": "LUX AETERNA", "length": 11, "sealed": True}


async def test_mixed_sync_and_async_sigils() -> None:
    async def divine(aether: Aether) -> Aether:
        await asyncio.sleep(0)
        return {"omens": aether["omens"] + 1}

    def inscribe(aether: Aether) -> Aether:
        return {"inscription": aether["omens"] * 2}

    ritual = Ritual()
    ritual.add_sigil("divine", divine)
    ritual.add_sigil("inscribe", inscribe)
    ritual.set_entry_point("divine")
    ritual.add_edge("divine", "inscribe")
    ritual.add_edge("inscribe", END)

    result = await ritual.compile().ainvoke({"omens": 1})
    assert result == {"omens": 2, "inscription": 4}


def test_compile_fails_without_entry_point() -> None:
    ritual = Ritual()
    ritual.add_sigil("lone", lambda aether: {})
    ritual.add_edge("lone", END)
    with pytest.raises(RitualValidationError, match="no entry point"):
        ritual.compile()


def test_compile_fails_on_edge_to_unknown_sigil() -> None:
    ritual = Ritual()
    ritual.add_sigil("real", lambda aether: {})
    ritual.set_entry_point("real")
    ritual.add_edge("real", "phantom")
    with pytest.raises(RitualValidationError, match="unknown Sigil 'phantom'"):
        ritual.compile()


def test_compile_fails_on_unreachable_sigil() -> None:
    ritual = Ritual()
    ritual.add_sigil("bound", lambda aether: {})
    ritual.add_sigil("orphan", lambda aether: {})
    ritual.set_entry_point("bound")
    ritual.add_edge("bound", END)
    ritual.add_edge("orphan", END)
    with pytest.raises(RitualValidationError, match="Unreachable Sigil.*orphan"):
        ritual.compile()


def test_compile_fails_on_sigil_without_outgoing_edge() -> None:
    ritual = Ritual()
    ritual.add_sigil("first", lambda aether: {})
    ritual.add_sigil("dead_end", lambda aether: {})
    ritual.set_entry_point("first")
    ritual.add_edge("first", "dead_end")
    with pytest.raises(
        RitualValidationError, match="without an outgoing edge.*dead_end"
    ):
        ritual.compile()


def test_invoke_and_ainvoke_return_same_result() -> None:
    rite = make_linear_ritual().compile()
    sync_result = rite.invoke({"text": "  fiat lux  "})
    async_result = asyncio.run(rite.ainvoke({"text": "  fiat lux  "}))
    assert sync_result == async_result == {
        "text": "FIAT LUX",
        "length": 8,
        "sealed": True,
    }
