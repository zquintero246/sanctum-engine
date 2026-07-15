"""Tests for builder-time validation and resumption error paths.

Covers add_sigil/add_edge/add_conditional_edge rejections, compile()
argument validation, and every SealError branch of fresh/resume handling.
"""

import pytest

from sanctum import (
    END,
    START,
    Rite,
    Ritual,
    RitualValidationError,
    SealError,
)
from sanctum.codex import MemoryCodex


def build_minimal(codex=None) -> Rite:
    ritual = Ritual()
    ritual.add_sigil("lone", lambda aether: {"done": True})
    ritual.set_entry_point("lone")
    ritual.add_edge("lone", END)
    return ritual.compile(codex=codex)


def test_add_sigil_rejects_reserved_names() -> None:
    with pytest.raises(RitualValidationError, match="reserved"):
        Ritual().add_sigil(START, lambda aether: {})


def test_add_sigil_rejects_duplicates() -> None:
    ritual = Ritual()
    ritual.add_sigil("one", lambda aether: {})
    with pytest.raises(RitualValidationError, match="already bound"):
        ritual.add_sigil("one", lambda aether: {})


def test_add_sigil_rejects_non_callable() -> None:
    with pytest.raises(RitualValidationError, match="callable"):
        Ritual().add_sigil("stone", 42)


def test_add_edge_rejects_end_source_and_start_target() -> None:
    ritual = Ritual()
    with pytest.raises(RitualValidationError, match="END"):
        ritual.add_edge(END, "anywhere")
    with pytest.raises(RitualValidationError, match="START"):
        ritual.add_edge("anywhere", START)


def test_add_edge_rejects_duplicate_edge() -> None:
    ritual = Ritual()
    ritual.add_sigil("a", lambda aether: {})
    ritual.add_edge("a", END)
    with pytest.raises(RitualValidationError, match="already traced"):
        ritual.add_edge("a", END)


def test_static_and_conditional_edges_are_mutually_exclusive() -> None:
    ritual = Ritual()
    ritual.add_sigil("a", lambda aether: {})
    ritual.add_edge("a", END)
    with pytest.raises(RitualValidationError, match="cannot share a source"):
        ritual.add_conditional_edge("a", lambda aether: END)

    other = Ritual()
    other.add_sigil("a", lambda aether: {})
    other.add_conditional_edge("a", lambda aether: END)
    with pytest.raises(RitualValidationError, match="cannot share a source"):
        other.add_edge("a", END)
    with pytest.raises(RitualValidationError, match="conditional edge"):
        other.add_conditional_edge("a", lambda aether: END)


def test_conditional_edge_rejects_start_end_and_non_callable_router() -> None:
    ritual = Ritual()
    with pytest.raises(RitualValidationError, match="set_entry_point"):
        ritual.add_conditional_edge(START, lambda aether: END)
    with pytest.raises(RitualValidationError, match="END"):
        ritual.add_conditional_edge(END, lambda aether: END)
    with pytest.raises(RitualValidationError, match="callable"):
        ritual.add_conditional_edge("a", 42)


def test_compile_rejects_non_positive_recursion_limit() -> None:
    ritual = Ritual()
    ritual.add_sigil("lone", lambda aether: {})
    ritual.set_entry_point("lone")
    ritual.add_edge("lone", END)
    with pytest.raises(RitualValidationError, match="positive"):
        ritual.compile(recursion_limit=0)


def test_compile_rejects_edge_from_unknown_sigil() -> None:
    ritual = Ritual()
    ritual.add_sigil("real", lambda aether: {})
    ritual.set_entry_point("real")
    ritual.add_edge("real", END)
    ritual.add_edge("ghost", END)
    with pytest.raises(RitualValidationError, match="unknown Sigil 'ghost'"):
        ritual.compile()


async def test_resume_without_codex_raises() -> None:
    rite = build_minimal()
    with pytest.raises(SealError, match="Codex"):
        await rite.ainvoke(invocation_id="inv-x")


async def test_resume_requires_invocation_id() -> None:
    rite = build_minimal(codex=MemoryCodex())
    with pytest.raises(SealError, match="invocation_id"):
        await rite.ainvoke()


async def test_resume_with_no_seals_raises() -> None:
    rite = build_minimal(codex=MemoryCodex())
    with pytest.raises(SealError, match="No Seals"):
        await rite.ainvoke(invocation_id="inv-ghost")


async def test_unknown_seal_id_raises() -> None:
    rite = build_minimal(codex=MemoryCodex())
    await rite.ainvoke({"x": 1}, invocation_id="inv-known")
    with pytest.raises(SealError, match="not found"):
        await rite.ainvoke(invocation_id="inv-known", seal_id="no-such-seal")


async def test_updates_on_fresh_run_raises() -> None:
    rite = build_minimal()
    with pytest.raises(SealError, match="updates"):
        await rite.ainvoke({"x": 1}, updates={"y": 2})


async def test_input_and_seal_id_together_raise() -> None:
    rite = build_minimal(codex=MemoryCodex())
    with pytest.raises(SealError, match="either"):
        await rite.ainvoke({"x": 1}, invocation_id="inv-x", seal_id="some-seal")
