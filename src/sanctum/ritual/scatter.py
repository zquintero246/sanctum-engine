"""Scatter — one Sigil that fans out over a dynamic list, in parallel.

Map-reduce for the ritual. Static fan-out (several edges from one
source) covers a *known* number of branches; ``scatter`` covers the
dynamic case — N items discovered at invocation time, worked
concurrently, results gathered in item order. It is deliberately a
Sigil factory rather than a scheduler extension: the BSP contract stays
untouched (one activation, one delta), determinism is preserved (results
land in item order, not completion order), and the reduce step is simply
whatever Sigil comes next.

    ritual.add_sigil("survey", scatter(scout, over="leads", into="reports"))

Compared to LangGraph's ``Send`` API: same capability (dynamic parallel
map), but the fan-out lives inside one node instead of multiplying
scheduler activations — which keeps Seals, resumption and the frontier
model exactly as simple as they are.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from typing import Any

from sanctum.aether import Aether


def scatter(
    fn: Callable[..., Any],
    *,
    over: str,
    into: str,
    concurrency: int = 8,
    on_item_error: str = "raise",
) -> Callable[[Aether], Any]:
    """Build a Sigil that maps `fn` over the list at Aether[`over`].

    Every item is worked concurrently (bounded by `concurrency`, a
    semaphore) and the results are written to `into` as a list in item
    order — deterministic regardless of completion order. `fn` may be
    sync or async; declare a second parameter to also receive the full
    Aether (read-only copy): ``fn(item)`` or ``fn(item, aether)``.

    `on_item_error` decides what a failing item does:

    - ``"raise"`` (default): the first failure cancels the remaining
      items and the whole Sigil fails (its SigilPolicy applies).
    - ``"collect"``: failures become ``{"__scatter_error__": repr}``
      entries in the result list, in position, and the rite continues.

    Raises (at build time):
        ValueError: If `concurrency` < 1 or `on_item_error` is unknown.
    """
    if concurrency < 1:
        raise ValueError(f"concurrency must be >= 1, got {concurrency}.")
    if on_item_error not in ("raise", "collect"):
        raise ValueError(
            f"on_item_error must be 'raise' or 'collect', got {on_item_error!r}."
        )
    wants_aether = _positional_parameters(fn) >= 2

    async def perform(aether: Aether) -> Aether:
        items = aether.get(over)
        if not isinstance(items, list):
            raise ValueError(
                f"scatter expected a list at Aether['{over}'], got "
                f"{type(items).__name__}; put the items there before this "
                "Sigil runs."
            )
        gate = asyncio.Semaphore(concurrency)

        async def work(item: Any) -> Any:
            async with gate:
                try:
                    result = fn(item, dict(aether)) if wants_aether else fn(item)
                    if inspect.isawaitable(result):
                        result = await result
                    return result
                except Exception as error:
                    if on_item_error == "collect":
                        return {"__scatter_error__": repr(error)}
                    raise

        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(work(item)) for item in items]
        return {into: [task.result() for task in tasks]}

    perform.__name__ = f"scatter_{over}_into_{into}"
    return perform


def _positional_parameters(fn: Callable[..., Any]) -> int:
    """Count `fn`'s positional parameters (0 when uninspectable)."""
    try:
        parameters = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return 1
    return sum(
        1
        for parameter in parameters
        if parameter.kind
        in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)
    )
