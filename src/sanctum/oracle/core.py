"""The voice consulted during the invocation, and the shape of its answers.

Abstract LLM interface. An Oracle receives a message transcript (dicts
with ``role``/``content``) plus the JSON schemas of the Spells it may
request, and answers with an OracleResponse: free text, zero or more
SpellCalls, and usage counters. `arcana` identifies the concrete model.
All implementations are local-first — the core never assumes proprietary
APIs.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

Message = dict[str, Any]
"""One entry of the transcript: at least ``role`` and ``content``."""


@dataclass(frozen=True, slots=True)
class SpellCall:
    """The Oracle's request to cast one Spell.

    `spell` names the Spell, `arguments` matches its JSON schema, and
    `call_id` correlates the request with the result message injected back
    into the transcript.
    """

    spell: str
    arguments: dict[str, Any] = field(default_factory=dict)
    call_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass(frozen=True, slots=True)
class OracleResponse:
    """One full answer from the Oracle.

    `text` is the assistant's message; `spell_calls` the Spells it wants
    cast before continuing (empty means the answer is final); `usage`
    holds free-form counters (e.g. prompt/completion tokens).
    """

    text: str
    spell_calls: list[SpellCall] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)


class Oracle(ABC):
    """The abstract voice every Entity consults.

    Implementations must set `arcana` (the concrete model identifier) and
    provide both a complete-answer path (``generate``) and a token stream
    (``stream_generate``). Implementations: ScriptedOracle (deterministic,
    for tests), OllamaOracle (`sanctum.oracle.ollama`), and
    TransformersOracle (`sanctum.oracle.transformers`).
    """

    arcana: str
    """Identifier of the concrete model behind this Oracle."""

    @abstractmethod
    async def generate(
        self,
        messages: Sequence[Mapping[str, Any]],
        spells: Sequence[Mapping[str, Any]] | None = None,
    ) -> OracleResponse:
        """Answer the transcript in one piece.

        `messages` is the conversation so far; `spells` the JSON schemas
        (name, description, parameters) of the Spells the Oracle may
        request via `spell_calls`.
        """

    @abstractmethod
    def stream_generate(
        self,
        messages: Sequence[Mapping[str, Any]],
        spells: Sequence[Mapping[str, Any]] | None = None,
    ) -> AsyncIterator[str]:
        """Answer the transcript as an async stream of text chunks.

        Yields incremental text; pair it with a Sigil's `writer` to push
        tokens through ``astream``.
        """
