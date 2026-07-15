"""An Oracle that reads from a prepared script.

Deterministic Oracle for tests: answers are handed over in order from a
fixed script, never touching a real model (non-negotiable principle #4).
Records every call for assertions.
"""

from __future__ import annotations

from collections import deque
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from sanctum.oracle.core import Oracle, OracleResponse


class ScriptedOracle(Oracle):
    """The voice that only ever says what was written for it.

    `script` is a sequence of OracleResponse (or plain strings, shorthand
    for a text-only response) returned one per ``generate`` call, in
    order. Exhausting the script raises RuntimeError — a scripted test
    asked one question too many. Every call is recorded in `calls` as
    ``(messages, spells)`` for assertions.
    """

    def __init__(
        self,
        script: Sequence[OracleResponse | str],
        arcana: str = "scripted-oracle",
    ) -> None:
        self.arcana = arcana
        self.calls: list[tuple[list[dict[str, Any]], list[dict[str, Any]] | None]] = []
        self._script: deque[OracleResponse] = deque(
            entry if isinstance(entry, OracleResponse) else OracleResponse(text=entry)
            for entry in script
        )

    async def generate(
        self,
        messages: Sequence[Mapping[str, Any]],
        spells: Sequence[Mapping[str, Any]] | None = None,
    ) -> OracleResponse:
        """Return the script's next response, recording the call."""
        self.calls.append(
            (
                [dict(message) for message in messages],
                [dict(schema) for schema in spells] if spells is not None else None,
            )
        )
        if not self._script:
            raise RuntimeError(
                "ScriptedOracle's script is exhausted; the test consulted "
                f"the Oracle more times ({len(self.calls)}) than responses "
                "were written."
            )
        return self._script.popleft()

    async def stream_generate(
        self,
        messages: Sequence[Mapping[str, Any]],
        spells: Sequence[Mapping[str, Any]] | None = None,
    ) -> AsyncIterator[str]:
        """Yield the script's next response word by word."""
        response = await self.generate(messages, spells)
        words = response.text.split(" ")
        for index, word in enumerate(words):
            yield word if index == len(words) - 1 else word + " "
