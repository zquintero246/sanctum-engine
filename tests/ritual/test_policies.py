"""Tests for SigilPolicy resilience: timeout, retries, retry_on, on_error.

Covers the documented precedence (timeout -> retries -> on_error ->
SigilExecutionError), the SigilRetried Omens, the reserved "__errors__"
Conduit, and the Seal interaction on definitive failure.
"""

import asyncio
import time
from typing import Any

import pytest

from sanctum import (
    END,
    Ritual,
    RitualValidationError,
    SigilExecutionError,
    SigilPolicy,
    SigilTimeoutError,
)
from sanctum.codex import MemoryCodex
from sanctum.omens import RiteManifested, SigilRetried

Aether = dict[str, Any]

INSTANT = SigilPolicy(retries=3, backoff=lambda attempt: 0)


async def test_slow_sigil_hits_timeout_quickly() -> None:
    async def slow(aether: Aether) -> Aether:
        await asyncio.sleep(0.5)
        return {}

    ritual = Ritual()
    ritual.add_sigil("slow", slow, policy=SigilPolicy(timeout=0.1))
    ritual.set_entry_point("slow")
    ritual.add_edge("slow", END)
    rite = ritual.compile()

    started = time.perf_counter()
    with pytest.raises(SigilTimeoutError) as excinfo:
        await rite.ainvoke({})
    elapsed = time.perf_counter() - started

    assert elapsed < 0.35  # cancelled at ~0.1s, not after the full 0.5s
    error = excinfo.value
    assert error.sigil == "slow"
    assert error.timeout == 0.1
    assert "0.1" in str(error)
    assert isinstance(error, SigilExecutionError)  # subclass contract


async def test_flaky_sigil_succeeds_with_retries_and_emits_omens() -> None:
    attempts: list[int] = []

    async def flaky(aether: Aether) -> Aether:
        attempts.append(1)
        if len(attempts) < 3:
            raise ValueError("misfire")
        return {"done": True}

    ritual = Ritual()
    ritual.add_sigil("flaky", flaky, policy=INSTANT)
    ritual.set_entry_point("flaky")
    ritual.add_edge("flaky", END)
    rite = ritual.compile()

    omens = [omen async for omen in rite.astream({}, mode="omens")]

    retried = [omen for omen in omens if isinstance(omen, SigilRetried)]
    assert [omen.attempt for omen in retried] == [1, 2]
    assert all("misfire" in omen.cause for omen in retried)
    assert len(attempts) == 3
    manifested = omens[-1]
    assert isinstance(manifested, RiteManifested)
    assert manifested.aether == {"done": True}


async def test_retry_on_is_selective() -> None:
    policy = SigilPolicy(retries=3, retry_on=(ValueError,), backoff=lambda a: 0)

    recoverable_attempts: list[int] = []

    def recoverable(aether: Aether) -> Aether:
        recoverable_attempts.append(1)
        if len(recoverable_attempts) < 2:
            raise ValueError("transient")
        return {"ok": True}

    ritual = Ritual()
    ritual.add_sigil("recoverable", recoverable, policy=policy)
    ritual.set_entry_point("recoverable")
    ritual.add_edge("recoverable", END)
    assert (await ritual.compile().ainvoke({}))["ok"] is True
    assert len(recoverable_attempts) == 2

    fatal_attempts: list[int] = []

    def fatal(aether: Aether) -> Aether:
        fatal_attempts.append(1)
        raise TypeError("not retryable")

    other = Ritual()
    other.add_sigil("fatal", fatal, policy=policy)
    other.set_entry_point("fatal")
    other.add_edge("fatal", END)
    with pytest.raises(SigilExecutionError) as excinfo:
        await other.compile().ainvoke({})
    assert isinstance(excinfo.value.__cause__, TypeError)
    assert len(fatal_attempts) == 1  # TypeError was not retried


async def test_on_error_jumps_to_fallback_with_readable_error() -> None:
    def doomed(aether: Aether) -> Aether:
        raise RuntimeError("the seal cracked")

    def mend(aether: Aether) -> Aether:
        failure = aether["__errors__"][-1]
        return {"mended": f"recovered from {failure['sigil']}: {failure['error']}"}

    codex = MemoryCodex()
    ritual = Ritual()
    ritual.add_sigil("doomed", doomed, policy=SigilPolicy(on_error="mend"))
    ritual.add_sigil("mend", mend)
    ritual.set_entry_point("doomed")
    ritual.add_edge("doomed", END)
    ritual.add_edge("mend", END)
    rite = ritual.compile(codex=codex)

    result = await rite.ainvoke({}, invocation_id="inv-mend")

    assert result["mended"] == "recovered from doomed: the seal cracked"
    failure = result["__errors__"][0]
    assert failure["sigil"] == "doomed"
    assert failure["type"] == "RuntimeError"
    # Seal interaction: the failed superstep wrote NO Seal; the fallback's
    # superstep did (and the reserved Conduit serialized fine).
    seals = await codex.list("inv-mend")
    assert [seal.superstep for seal in seals] == [2]
    assert seals[0].aether["__errors__"][0]["sigil"] == "doomed"


async def test_definitive_failure_leaves_no_corrupt_seal_and_resume_works() -> None:
    def prepare(aether: Aether) -> Aether:
        return {"ready": True}

    def explode(aether: Aether) -> Aether:
        if not aether.get("defused"):
            raise RuntimeError("boom")
        return {"boom": False}

    codex = MemoryCodex()
    ritual = Ritual()
    ritual.add_sigil("prepare", prepare)
    ritual.add_sigil("explode", explode)
    ritual.set_entry_point("prepare")
    ritual.add_edge("prepare", "explode")
    ritual.add_edge("explode", END)
    rite = ritual.compile(codex=codex)

    with pytest.raises(SigilExecutionError):
        await rite.ainvoke({"ready": False}, invocation_id="inv-crash")

    # Only the successful superstep left a Seal; the failed one wrote none.
    seals = await codex.list("inv-crash")
    assert len(seals) == 1
    assert seals[0].frontier == ["explode"]
    assert seals[0].aether["ready"] is True

    # Resuming from the last valid Seal (injecting the fix) completes.
    resumed = await rite.ainvoke(invocation_id="inv-crash", updates={"defused": True})
    assert resumed["boom"] is False
    assert resumed["ready"] is True


def test_compile_rejects_unknown_on_error_target() -> None:
    ritual = Ritual()
    ritual.add_sigil("lone", lambda aether: {}, policy=SigilPolicy(on_error="ghost"))
    ritual.set_entry_point("lone")
    ritual.add_edge("lone", END)
    with pytest.raises(RitualValidationError, match="on_error.*'ghost'"):
        ritual.compile()


def test_compile_rejects_self_fallback() -> None:
    ritual = Ritual()
    ritual.add_sigil("ouro", lambda aether: {}, policy=SigilPolicy(on_error="ouro"))
    ritual.set_entry_point("ouro")
    ritual.add_edge("ouro", END)
    with pytest.raises(RitualValidationError, match="its own on_error"):
        ritual.compile()
