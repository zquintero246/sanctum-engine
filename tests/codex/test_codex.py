"""Tests for Seals and Codices.

Covers per-superstep Seal writing, interrupt/resume (human-in-the-loop),
time-travel from a historic Seal, and SQLite persistence across object
recreation.
"""

from pathlib import Path
from typing import Any

import pytest

from sanctum import END, Interrupt, Rite, Ritual, interrupt
from sanctum.codex import MemoryCodex, Seal, SealError, SqliteCodex

Aether = dict[str, Any]


def build_publishing_rite(codex: MemoryCodex) -> tuple[Rite, dict[str, int]]:
    """draft -> confirm (interrupts until approved) -> publish."""
    runs = {"draft": 0}

    def draft(aether: Aether) -> Aether:
        runs["draft"] += 1
        return {"draft": aether["question"] + "?"}

    def confirm(aether: Aether) -> Aether:
        if not aether["approved"]:
            interrupt("awaiting approval")
        return {"confirmed": True}

    def publish(aether: Aether) -> Aether:
        return {"published": aether["draft"].upper()}

    ritual = Ritual()
    ritual.add_sigil("draft", draft)
    ritual.add_sigil("confirm", confirm)
    ritual.add_sigil("publish", publish)
    ritual.set_entry_point("draft")
    ritual.add_edge("draft", "confirm")
    ritual.add_edge("confirm", "publish")
    ritual.add_edge("publish", END)
    return ritual.compile(codex=codex), runs


async def test_codex_writes_one_seal_per_superstep() -> None:
    codex = MemoryCodex()
    ritual = Ritual()
    ritual.add_sigil("cleanse", lambda aether: {"text": aether["text"].strip()})
    ritual.add_sigil("transmute", lambda aether: {"text": aether["text"].upper()})
    ritual.add_sigil("seal_it", lambda aether: {"sealed": True})
    ritual.set_entry_point("cleanse")
    ritual.add_edge("cleanse", "transmute")
    ritual.add_edge("transmute", "seal_it")
    ritual.add_edge("seal_it", END)

    await ritual.compile(codex=codex).ainvoke(
        {"text": "  lux  "}, invocation_id="inv-seals"
    )

    seals = await codex.list("inv-seals")
    assert len(seals) == 3
    assert [seal.superstep for seal in seals] == [1, 2, 3]
    assert seals[0].aether == {"text": "lux"}
    assert seals[0].frontier == ["transmute"]
    assert seals[-1].frontier == [END]
    latest = await codex.get("inv-seals")
    assert latest is not None and latest.seal_id == seals[-1].seal_id


async def test_interrupt_then_resume_matches_uninterrupted_run() -> None:
    # Reference: the same graph, approved from the start, never interrupted.
    reference_rite, _ = build_publishing_rite(MemoryCodex())
    reference = await reference_rite.ainvoke(
        {"question": "ready", "approved": True}, invocation_id="inv-reference"
    )

    codex = MemoryCodex()
    rite, runs = build_publishing_rite(codex)
    with pytest.raises(Interrupt) as excinfo:
        await rite.ainvoke(
            {"question": "ready", "approved": False}, invocation_id="inv-hitl"
        )
    assert excinfo.value.sigil == "confirm"
    assert excinfo.value.reason == "awaiting approval"

    interrupt_seal = await codex.get("inv-hitl")
    assert interrupt_seal is not None
    assert interrupt_seal.metadata["interrupted"] is True
    assert interrupt_seal.frontier == ["confirm"]

    # Resume, injecting the human approval into the Aether.
    resumed = await rite.ainvoke(
        invocation_id="inv-hitl", updates={"approved": True}
    )
    assert resumed == reference | {"approved": True}
    assert resumed["published"] == "READY?"
    # It continued exactly where it left off: draft never re-executed.
    assert runs["draft"] == 1


async def test_time_travel_resumes_from_historic_seal() -> None:
    codex = MemoryCodex()
    ritual = Ritual()
    ritual.add_sigil("advance", lambda aether: {"count": aether["count"] + 1})
    ritual.set_entry_point("advance")
    ritual.add_conditional_edge(
        "advance", lambda aether: END if aether["count"] >= 5 else "advance"
    )
    rite = ritual.compile(codex=codex)

    original = await rite.ainvoke({"count": 0}, invocation_id="inv-time")
    assert original == {"count": 5}
    history = await codex.list("inv-time")
    assert len(history) == 5

    second = history[1]
    assert second.superstep == 2
    assert second.aether == {"count": 2}

    replay = await rite.ainvoke(invocation_id="inv-time", seal_id=second.seal_id)
    assert replay == original
    # Time-travel appends the replayed supersteps (3, 4, 5) to the history.
    assert len(await codex.list("inv-time")) == 8


async def test_sqlite_codex_survives_recreating_the_object(tmp_path: Path) -> None:
    path = tmp_path / "codex.db"
    codex = SqliteCodex(path)
    seal = Seal(
        aether={"text": "lux"},
        frontier=["transmute"],
        superstep=1,
        metadata={"phase": "test"},
    )
    await codex.put("inv-sqlite", seal)

    reopened = SqliteCodex(path)
    restored = await reopened.get("inv-sqlite")
    assert restored == seal
    assert await reopened.list("inv-sqlite") == [seal]


async def test_sqlite_codex_rejects_non_serializable_aether(tmp_path: Path) -> None:
    codex = SqliteCodex(tmp_path / "codex.db")
    seal = Seal(aether={"handle": object()}, frontier=[], superstep=1)
    with pytest.raises(SealError, match="JSON"):
        await codex.put("inv-bad", seal)


async def test_sqlite_codex_end_to_end_with_engine(tmp_path: Path) -> None:
    path = tmp_path / "rite.db"
    ritual = Ritual()
    ritual.add_sigil("cleanse", lambda aether: {"text": aether["text"].strip()})
    ritual.add_sigil("transmute", lambda aether: {"text": aether["text"].upper()})
    ritual.set_entry_point("cleanse")
    ritual.add_edge("cleanse", "transmute")
    ritual.add_edge("transmute", END)

    rite = ritual.compile(codex=SqliteCodex(path))
    result = await rite.ainvoke({"text": "  fiat lux  "}, invocation_id="inv-e2e")
    assert result == {"text": "FIAT LUX"}

    reopened = SqliteCodex(path)
    seals = await reopened.list("inv-e2e")
    assert [seal.superstep for seal in seals] == [1, 2]
    assert seals[-1].aether == {"text": "FIAT LUX"}
    assert seals[-1].frontier == [END]
