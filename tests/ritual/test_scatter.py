"""Tests for scatter (dynamic parallel map inside one Sigil).

Covers order preservation under concurrency, bounded parallelism, the
optional aether parameter, per-item error semantics, build-time
validation, and an end-to-end map-reduce ritual with a dynamic item
count.
"""

import asyncio
from typing import Any

import pytest

from sanctum import END, Ritual, SigilExecutionError, scatter

Aether = dict[str, Any]


async def test_results_keep_item_order_despite_completion_order() -> None:
    async def slow_double(item: int) -> int:
        await asyncio.sleep(0.05 - item * 0.01)  # later items finish first
        return item * 2

    sigil = scatter(slow_double, over="numbers", into="doubled")
    delta = await sigil({"numbers": [0, 1, 2, 3]})
    assert delta == {"doubled": [0, 2, 4, 6]}


async def test_concurrency_is_bounded() -> None:
    in_flight = 0
    peak = 0

    async def probe(item: int) -> int:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.02)
        in_flight -= 1
        return item

    sigil = scatter(probe, over="items", into="out", concurrency=3)
    await sigil({"items": list(range(10))})
    assert peak == 3


async def test_two_parameter_fn_receives_the_aether() -> None:
    def stamp(item: str, aether: Aether) -> str:
        return f"{aether['prefix']}{item}"

    sigil = scatter(stamp, over="names", into="stamped")
    delta = await sigil({"names": ["a", "b"], "prefix": ">"})
    assert delta == {"stamped": [">a", ">b"]}


async def test_missing_or_non_list_key_is_readable() -> None:
    sigil = scatter(lambda item: item, over="leads", into="out")
    with pytest.raises(ValueError, match="Aether\\['leads'\\]"):
        await sigil({})


async def test_item_error_semantics() -> None:
    def explode_on_two(item: int) -> int:
        if item == 2:
            raise RuntimeError("boom")
        return item

    collecting = scatter(
        explode_on_two, over="items", into="out", on_item_error="collect"
    )
    delta = await collecting({"items": [1, 2, 3]})
    assert delta["out"][0] == 1 and delta["out"][2] == 3
    assert "boom" in delta["out"][1]["__scatter_error__"]

    raising = scatter(explode_on_two, over="items", into="out")
    with pytest.raises(Exception):  # noqa: B017 — TaskGroup wraps it
        await raising({"items": [1, 2, 3]})


def test_build_time_validation() -> None:
    with pytest.raises(ValueError, match="concurrency"):
        scatter(lambda item: item, over="a", into="b", concurrency=0)
    with pytest.raises(ValueError, match="on_item_error"):
        scatter(lambda item: item, over="a", into="b", on_item_error="ignore")


async def test_map_reduce_ritual_with_dynamic_item_count() -> None:
    ritual = Ritual()
    ritual.add_sigil(
        "plan", lambda aether: {"leads": [f"lead_{i}" for i in range(aether["n"])]}
    )
    ritual.add_sigil(
        "survey",
        scatter(lambda lead: f"report on {lead}", over="leads", into="reports"),
    )
    ritual.add_sigil(
        "reduce", lambda aether: {"summary": " | ".join(aether["reports"])}
    )
    ritual.set_entry_point("plan")
    ritual.add_edge("plan", "survey")
    ritual.add_edge("survey", "reduce")
    ritual.add_edge("reduce", END)
    rite = ritual.compile()

    small = await rite.ainvoke({"n": 2})
    big = await rite.ainvoke({"n": 5})
    assert small["summary"] == "report on lead_0 | report on lead_1"
    assert len(big["reports"]) == 5


async def test_scatter_failure_is_attributed_to_its_sigil() -> None:
    ritual = Ritual()
    ritual.add_sigil("plan", lambda aether: {"items": [1]})
    ritual.add_sigil(
        "boom",
        scatter(lambda item: 1 / 0, over="items", into="out"),
    )
    ritual.set_entry_point("plan")
    ritual.add_edge("plan", "boom")
    ritual.add_edge("boom", END)

    with pytest.raises(SigilExecutionError) as caught:
        await ritual.compile().ainvoke({})
    assert caught.value.sigil == "boom"
