"""Weathering the imperfect speech of small local models.

Robust spell-calling. Local 7-14B models fumble tool calls in known ways:
malformed JSON, prose mixed with the payload, single quotes, unbalanced
braces, or no native tool support at all. This module treats those as
first-class inputs, not errors: ``extract_json`` recovers objects from
messy text (used by the repair layer in ``sanctum.grimoire.repair``), and
``PromptedSpellCalling`` wraps any Oracle to emulate tool calling through
the prompt — schemas are injected into the system prompt with a delimited
invocation format, and the answer's text is parsed back into SpellCalls.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from typing import Any

from sanctum.oracle.core import Oracle, OracleResponse, SpellCall
from sanctum.oracle.errors import OracleResponseError

SPELL_CALL_OPEN = "<spell_call>"
SPELL_CALL_CLOSE = "</spell_call>"

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_BLOCK = re.compile(
    re.escape(SPELL_CALL_OPEN) + r"(.*?)" + re.escape(SPELL_CALL_CLOSE), re.DOTALL
)


def extract_json(text: str) -> dict[str, Any] | None:
    """Tolerantly extract one JSON object from model output.

    Tries, in order: the first fenced ``` / ```json block, the outermost
    brace region, and the raw text. Each candidate is parsed as-is, then
    with simple mends — appending missing closing braces, and swapping
    single quotes for double quotes when the candidate contains no double
    quotes. Returns the first dict found, or None when nothing parses.
    """
    candidates: list[str] = []
    fenced = _FENCE.search(text)
    if fenced:
        candidates.append(fenced.group(1))
    start = text.find("{")
    if start != -1:
        end = text.rfind("}")
        candidates.append(text[start : end + 1] if end > start else text[start:])
    candidates.append(text)

    seen: set[str] = set()
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        for attempt in _mend_attempts(candidate):
            try:
                decoded = json.loads(attempt)
            except ValueError:
                continue
            if isinstance(decoded, dict):
                return decoded
    return None


def _mend_attempts(candidate: str) -> Iterator[str]:
    """Yield the candidate plus its simple mends, cheapest first."""
    yield candidate
    balanced = _close_braces(candidate)
    if balanced != candidate:
        yield balanced
    if '"' not in candidate:
        swapped = candidate.replace("'", '"')
        yield swapped
        yield _close_braces(swapped)


def _close_braces(candidate: str) -> str:
    """Append the closing braces a truncated object is missing (rough)."""
    difference = candidate.count("{") - candidate.count("}")
    return candidate + "}" * difference if difference > 0 else candidate


def render_spell_prompt(spells: Sequence[Mapping[str, Any]]) -> str:
    """Write the system-prompt section teaching the delimited call format.

    Lists every Spell with its JSON schema and shows the exact block the
    model must produce to cast one.
    """
    lines = ["You can cast the following Spells (tools):", ""]
    for schema in spells:
        lines.append(f"- {schema.get('name', '?')}: {schema.get('description', '')}")
        lines.append(
            f"  parameters (JSON Schema): {json.dumps(schema.get('parameters', {}))}"
        )
    lines += [
        "",
        "To cast a Spell, write a block exactly like this:",
        SPELL_CALL_OPEN,
        '{"spell": "<spell_name>", "arguments": {<arguments matching the schema>}}',
        SPELL_CALL_CLOSE,
        "Write one block per call; the results will come back as messages. "
        "When you do not need any Spell, answer the user directly and write "
        "no block.",
    ]
    return "\n".join(lines)


def inject_spell_prompt(
    messages: Sequence[Mapping[str, Any]], spells: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Fold the Spell section into the transcript's system prompt.

    Appends to the existing leading system message, or prepends a new one.
    Returns a new list; `messages` is not mutated.
    """
    section = render_spell_prompt(spells)
    prepared = [dict(message) for message in messages]
    if prepared and prepared[0].get("role") == "system":
        prepared[0]["content"] = f"{prepared[0].get('content', '')}\n\n{section}"
        return prepared
    return [{"role": "system", "content": section}, *prepared]


def parse_spell_blocks(text: str) -> tuple[str, list[SpellCall]]:
    """Split a prompted answer into prose and SpellCalls.

    Every ``<spell_call>...</spell_call>`` block is parsed with
    ``extract_json``; blocks that still refuse to parse become SpellCalls
    flagged ``"__malformed_json__"``, so the repair layer treats prompted
    failures exactly like native ones. The prose outside the blocks is
    returned as the response text.

    Small local models frequently ignore the delimiter format and emit
    the call as bare JSON instead (observed with 0.5-3B models on
    llama-server): when no blocks are present but the whole answer parses
    to an object carrying a ``"spell"`` name, it is routed through the
    repair layer as a malformed call — validated, executed, and surfaced
    as a SpellCallRepaired Omen.
    """
    calls: list[SpellCall] = []
    for block in _BLOCK.findall(text):
        data = extract_json(block)
        if (
            data is not None
            and isinstance(data.get("spell"), str)
            and isinstance(data.get("arguments", {}), dict)
        ):
            calls.append(
                SpellCall(
                    spell=data["spell"], arguments=dict(data.get("arguments") or {})
                )
            )
        else:
            calls.append(
                SpellCall(
                    spell=(data or {}).get("spell") or "",
                    arguments={"__malformed_json__": block.strip()},
                )
            )
    if not calls:
        bare = extract_json(text)
        if bare is not None and isinstance(bare.get("spell"), str) and bare["spell"]:
            return "", [
                SpellCall(
                    spell=bare["spell"],
                    arguments={"__malformed_json__": text.strip()},
                )
            ]
    prose = _BLOCK.sub("", text).strip()
    return prose, calls


def _looks_like_no_tool_support(error: OracleResponseError) -> bool:
    """Heuristic: did the endpoint reject the request because of tools?"""
    message = str(error).lower()
    return "tool" in message


class PromptedSpellCalling(Oracle):
    """A voice taught to cast Spells by instruction, not by wiring.

    Oracle wrapper emulating tool calling for models or endpoints without
    native support. With ``mode="always"`` (default) every ``generate``
    that carries Spell schemas is rewritten: schemas go into the system
    prompt (``inject_spell_prompt``) and the answer's text is parsed back
    into SpellCalls (``parse_spell_blocks``). With ``mode="auto"`` native
    tool calling is tried first, and the wrapper falls back — and stays —
    on prompted calling the first time the endpoint rejects tools
    (an OracleResponseError mentioning tools).

    ``stream_generate`` passes chunks through with the prompt injected;
    delimited blocks appear verbatim in the stream (parsing needs the full
    text), so prefer ``generate`` inside spell-calling loops.
    """

    def __init__(self, oracle: Oracle, mode: str = "always") -> None:
        if mode not in ("always", "auto"):
            raise ValueError(
                f"Unknown PromptedSpellCalling mode '{mode}'; use 'always' "
                "or 'auto'."
            )
        self._inner = oracle
        self._prompted = mode == "always"
        self.arcana = oracle.arcana

    async def generate(
        self,
        messages: Sequence[Mapping[str, Any]],
        spells: Sequence[Mapping[str, Any]] | None = None,
    ) -> OracleResponse:
        """Answer the transcript, emulating tool calls when needed."""
        if not spells:
            return await self._inner.generate(messages)
        if not self._prompted:
            try:
                return await self._inner.generate(messages, spells)
            except OracleResponseError as error:
                if not _looks_like_no_tool_support(error):
                    raise
                self._prompted = True  # remember: this endpoint has no tools
        response = await self._inner.generate(inject_spell_prompt(messages, spells))
        prose, calls = parse_spell_blocks(response.text)
        return OracleResponse(
            text=prose,
            spell_calls=[*response.spell_calls, *calls],
            usage=response.usage,
        )

    async def stream_generate(
        self,
        messages: Sequence[Mapping[str, Any]],
        spells: Sequence[Mapping[str, Any]] | None = None,
    ) -> AsyncIterator[str]:
        """Stream the inner Oracle with the Spell prompt injected."""
        prepared = inject_spell_prompt(messages, spells) if spells else messages
        async for chunk in self._inner.stream_generate(prepared):
            yield chunk
