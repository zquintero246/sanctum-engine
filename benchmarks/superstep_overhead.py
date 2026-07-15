"""Measure the engine's per-superstep overhead with no-op Sigils.

Thesis-support benchmark: quantifies what the orchestrator itself costs
per superstep — scheduling, delta merging, edge evaluation, Seal writing —
using Sigils that do no real work. The figures are meant to be compared
against LLM inference latency (tens of milliseconds to seconds per call)
to show that orchestration overhead is negligible in the pipeline's total.

Scenarios:
  1. sequential (bare):        1 Sigil cycling via a conditional edge.
  2. sequential + AetherSchema: same cycle, deltas through Conduit reducers.
  3. sequential + MemoryCodex:  same cycle, one Seal written per superstep.
  4. parallel x8:               spread -> 8 no-op Sigils -> gate -> ...

Run:  python benchmarks/superstep_overhead.py
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

from sanctum import END, AetherSchema, Conduit, Rite, Ritual, Ward
from sanctum.aether import add
from sanctum.codex import Codex, MemoryCodex
from sanctum.omens import TraceRecorder

SUPERSTEPS = 1_000
ROUNDS = 200  # parallel scenario: 3 supersteps per round
REPEATS = 3


def build_sequential(
    supersteps: int,
    schema: AetherSchema | None = None,
    codex: Codex | None = None,
    increment_delta: bool = False,
    wards: list[Ward] | None = None,
) -> Rite:
    """One no-op Sigil cycling on itself for `supersteps` supersteps.

    With `increment_delta` the Sigil emits ``{"count": 1}`` — the shape an
    `add` reducer expects — instead of the running total.
    """
    ritual = Ritual(schema)
    if increment_delta:
        ritual.add_sigil("tick", lambda aether: {"count": 1})
    else:
        ritual.add_sigil("tick", lambda aether: {"count": aether["count"] + 1})
    ritual.set_entry_point("tick")
    ritual.add_conditional_edge(
        "tick", lambda aether: END if aether["count"] >= supersteps else "tick"
    )
    return ritual.compile(
        recursion_limit=supersteps + 1, codex=codex, wards=wards
    )


def build_parallel(rounds: int, width: int = 8) -> Rite:
    """spread -> `width` parallel no-op Sigils -> gate, cycled `rounds` times."""
    ritual = Ritual()
    ritual.add_sigil("spread", lambda aether: {})
    ritual.set_entry_point("spread")
    for index in range(width):
        name = f"worker_{index}"
        ritual.add_sigil(name, lambda aether: {})
        ritual.add_edge("spread", name)
        ritual.add_edge(name, "gate")
    ritual.add_sigil("gate", lambda aether: {"round": aether["round"] + 1})
    ritual.add_conditional_edge(
        "gate", lambda aether: END if aether["round"] >= rounds else "spread"
    )
    return ritual.compile(recursion_limit=rounds * 3 + 1)


def measure(label: str, rite: Rite, input: dict, supersteps: int) -> None:
    """Time the invocation (best of REPEATS) and print µs per superstep."""
    best = min(
        _timed(rite, dict(input)) for _ in range(REPEATS)
    )
    per_superstep_us = best / supersteps * 1_000_000
    print(
        f"{label:<34} {supersteps:>10} {best * 1000:>10.1f} {per_superstep_us:>14.1f}"
    )


def _timed(rite: Rite, input: dict) -> float:
    started = time.perf_counter()
    asyncio.run(rite.ainvoke(input))
    return time.perf_counter() - started


def main() -> None:
    print(f"Sanctum superstep overhead — no-op Sigils, best of {REPEATS}")
    print(f"{'scenario':<34} {'supersteps':>10} {'total ms':>10} {'us/superstep':>14}")
    measure(
        "sequential (bare)",
        build_sequential(SUPERSTEPS),
        {"count": 0},
        SUPERSTEPS,
    )
    measure(
        "sequential + AetherSchema",
        build_sequential(
            SUPERSTEPS,
            schema=AetherSchema({"count": Conduit(reducer=add)}),
            increment_delta=True,
        ),
        {"count": 0},
        SUPERSTEPS,
    )
    measure(
        "sequential + MemoryCodex",
        build_sequential(SUPERSTEPS, codex=MemoryCodex()),
        {"count": 0},
        SUPERSTEPS,
    )
    measure(
        "parallel x8 (spread/work/gate)",
        build_parallel(ROUNDS),
        {"round": 0},
        ROUNDS * 3,
    )
    # TraceRecorder is opt-in; a fresh recorder per run keeps traces clean.
    trace_dir = Path(tempfile.mkdtemp(prefix="sanctum-bench-"))
    best_trace = min(
        _timed(
            build_sequential(
                SUPERSTEPS,
                wards=[TraceRecorder(trace_dir / f"run-{index}.sanctum-trace.json")],
            ),
            {"count": 0},
        )
        for index in range(REPEATS)
    )
    print(
        f"{'sequential + TraceRecorder':<34} {SUPERSTEPS:>10} "
        f"{best_trace * 1000:>10.1f} {best_trace / SUPERSTEPS * 1_000_000:>14.1f}"
    )
    print(
        "\nReference: local LLM inference latency is typically 10^4-10^6 us "
        "per call,\nso per-superstep orchestration overhead is negligible."
    )


if __name__ == "__main__":
    main()
