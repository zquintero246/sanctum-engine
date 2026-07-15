"""How new energy folds into each Conduit of the Aether.

Built-in reducers. A reducer is any callable ``(current, update) -> new``
that merges a Sigil's delta value into a Conduit's current value:
`overwrite` (the default) replaces, `append` concatenates lists, `add` sums
numbers, and `merge_dict` shallow-merges dicts. Any custom callable with
the same signature is a valid reducer. Reducers are only called when the
Conduit already holds a value; a delta to a missing key sets it directly.
"""

from collections.abc import Callable
from typing import Any

Reducer = Callable[[Any, Any], Any]
"""A Conduit's merge function: ``(current, update) -> new value``."""


def overwrite(current: Any, update: Any) -> Any:
    """Replace the current value with the update (the default reducer)."""
    return update


def append(current: list[Any], update: list[Any]) -> list[Any]:
    """Concatenate the update list after the current list.

    The delta value must be a list of items to append (wrap single items).
    Returns a new list; neither input is mutated.
    """
    return list(current) + list(update)


def add(current: Any, update: Any) -> Any:
    """Sum the update into the current value (numeric accumulation)."""
    return current + update


def merge_dict(current: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    """Shallow-merge the update dict over the current dict.

    Keys present in both take the update's value. Returns a new dict;
    neither input is mutated.
    """
    return {**current, **update}
