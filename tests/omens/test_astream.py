"""Tests for astream and the Omen event stream.

Covers per-Sigil updates ordering, live token delivery through the
injected writer (tokens reach the consumer before the Sigil finishes),
and SealWritten Omens when streaming with a Codex attached.
"""

import asyncio
from typing import Any

import pytest

from sanctum import END, Ritual
from sanctum.codex import MemoryCodex
from sanctum.omens import (
    RiteBegan,
    RiteManifested,
    SealWritten,
    SigilCompleted,
    TokenEmitted,
)

Aether = dict[str, Any]


def build_linear_ritual() -> Ritual:
    ritual = Ritual()
    ritual.add_sigil("cleanse", lambda aether: {"text": aether["text"].strip()})
    ritual.add_sigil("transmute", lambda aether: {"text": aether["text"].upper()})
    ritual.add_sigil("seal_it", lambda aether: {"sealed": True})
    ritual.set_entry_point("cleanse")
    ritual.add_edge("cleanse", "transmute")
    ritual.add_edge("transmute", "seal_it")
    ritual.add_edge("seal_it", END)
    return ritual


async def test_updates_mode_emits_one_omen_per_sigil_in_order() -> None:
    rite = build_linear_ritual().compile()
    omens = [omen async for omen in rite.astream({"text": "  lux  "})]

    assert all(isinstance(omen, SigilCompleted) for omen in omens)
    assert [omen.sigil for omen in omens] == ["cleanse", "transmute", "seal_it"]
    assert omens[0].delta == {"text": "lux"}
    assert omens[1].delta == {"text": "LUX"}
    assert omens[2].delta == {"sealed": True}
    assert [omen.superstep for omen in omens] == [1, 2, 3]


async def test_tokens_reach_consumer_before_sigil_finishes() -> None:
    timeline: list[str] = []

    async def chant(aether: Aether, writer) -> Aether:
        for index in range(5):
            await writer(f"syllable-{index}")
            await asyncio.sleep(0)  # yield so the consumer can drain the queue
        timeline.append("sigil_finished")
        return {"chanted": True}

    ritual = Ritual()
    ritual.add_sigil("chant", chant)
    ritual.set_entry_point("chant")
    ritual.add_edge("chant", END)
    rite = ritual.compile()

    tokens: list[str] = []
    async for omen in rite.astream({"verse": 1}, mode="tokens"):
        assert isinstance(omen, TokenEmitted)
        assert omen.sigil == "chant"
        timeline.append(f"consumed:{omen.token}")
        tokens.append(omen.token)

    assert tokens == [f"syllable-{index}" for index in range(5)]
    # Every token was consumed while the Sigil was still running.
    finished_at = timeline.index("sigil_finished")
    consumed_before = [
        entry for entry in timeline[:finished_at] if entry.startswith("consumed:")
    ]
    assert consumed_before == [f"consumed:syllable-{index}" for index in range(5)]


async def test_streaming_with_codex_emits_seal_written() -> None:
    codex = MemoryCodex()
    rite = build_linear_ritual().compile(codex=codex)

    omens = [
        omen
        async for omen in rite.astream(
            {"text": "  lux  "}, invocation_id="inv-stream", mode="omens"
        )
    ]

    assert isinstance(omens[0], RiteBegan)
    assert omens[0].invocation_id == "inv-stream"
    assert isinstance(omens[-1], RiteManifested)
    assert omens[-1].aether == {"text": "LUX", "sealed": True}

    seal_omens = [omen for omen in omens if isinstance(omen, SealWritten)]
    assert [omen.superstep for omen in seal_omens] == [1, 2, 3]
    seals = await codex.list("inv-stream")
    assert [seal.seal_id for seal in seals] == [omen.seal_id for omen in seal_omens]


async def test_combined_modes_yield_union() -> None:
    async def chant(aether: Aether, writer) -> Aether:
        await writer("only-syllable")
        return {"chanted": True}

    ritual = Ritual()
    ritual.add_sigil("chant", chant)
    ritual.set_entry_point("chant")
    ritual.add_edge("chant", END)
    rite = ritual.compile()

    omens = [
        omen
        async for omen in rite.astream({"verse": 1}, mode={"updates", "tokens"})
    ]
    assert [type(omen) for omen in omens] == [TokenEmitted, SigilCompleted]


async def test_unknown_mode_raises_value_error() -> None:
    rite = build_linear_ritual().compile()
    with pytest.raises(ValueError, match="portents"):
        async for _ in rite.astream({"text": "x"}, mode="portents"):
            pass


def test_empty_mode_iterable_raises_value_error() -> None:
    from sanctum.omens import resolve_modes

    with pytest.raises(ValueError, match="at least one"):
        resolve_modes([])
