"""Tests for robust spell-calling.

Covers tolerant JSON extraction, the repair layer inside the summon loop
(local repair, conversational correction, surrender), the
PromptedSpellCalling strategy, and the repair Omens in astream. Every
Oracle is scripted — no real models (principle 4).
"""

import pytest

from sanctum import Tome, spell, summon
from sanctum.grimoire import SpellCallParseError
from sanctum.omens import SpellCallRejected, SpellCallRepaired
from sanctum.oracle import OracleResponse, ScriptedOracle, SpellCall
from sanctum.oracle.robust import (
    extract_json,
    inject_spell_prompt,
    parse_spell_blocks,
)


@spell
def word_count(text: str) -> int:
    """Count the words in a text."""
    return len(text.split())


def user_input(content: str) -> dict:
    return {"messages": [{"role": "user", "content": content}]}


def malformed_call(raw: str, call_id: str) -> OracleResponse:
    return OracleResponse(
        text="",
        spell_calls=[
            SpellCall(
                spell="word_count",
                arguments={"__malformed_json__": raw},
                call_id=call_id,
            )
        ],
    )


# --- tolerant extraction ----------------------------------------------------


def test_extract_json_handles_fences_quotes_and_unbalanced_braces() -> None:
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json("Sure thing: {'a': 1}") == {"a": 1}
    assert extract_json('{"a": {"b": 1}') == {"a": {"b": 1}}
    assert extract_json("no json in sight") is None


# --- repair layer inside the summon loop ------------------------------------


async def test_fenced_json_wrapped_in_text_is_extracted_and_cast() -> None:
    fenced = (
        "Sure! Here is the call:\n"
        '```json\n{"text": "lux aeterna"}\n```\n'
        "Hope that helps."
    )
    oracle = ScriptedOracle(
        [malformed_call(fenced, "c1"), OracleResponse(text="Two words.")]
    )
    entity = summon(oracle, Tome([word_count]))

    result = await entity.ainvoke(user_input("count 'lux aeterna'"))
    messages = result["messages"]
    spell_result = messages[2]
    assert spell_result["role"] == "spell"
    assert "error" not in spell_result
    assert spell_result["content"] == "2"
    assert messages[-1]["content"] == "Two words."


async def test_unknown_spell_gets_correction_and_loop_completes() -> None:
    oracle = ScriptedOracle(
        [
            OracleResponse(
                text="",
                spell_calls=[
                    SpellCall(
                        spell="ghost_count",
                        arguments={"text": "lux"},
                        call_id="c1",
                    )
                ],
            ),
            OracleResponse(
                text="",
                spell_calls=[
                    SpellCall(
                        spell="word_count", arguments={"text": "lux"}, call_id="c2"
                    )
                ],
            ),
            OracleResponse(text="One word."),
        ]
    )
    entity = summon(oracle, Tome([word_count]))

    result = await entity.ainvoke(user_input("count"))
    messages = result["messages"]
    correction = messages[2]
    assert correction["error"] is True
    assert "ghost_count" in correction["content"]
    assert "word_count" in correction["content"]  # the available-Spells list
    assert messages[4]["content"] == "1"  # the corrected call executed
    assert messages[-1]["content"] == "One word."
    # The Oracle actually saw the correction in its second consultation.
    second_transcript, _ = oracle.calls[1]
    assert any(
        "Unknown Spell" in message.get("content", "")
        for message in second_transcript
    )


async def test_irreparable_json_raises_after_max_repair_rounds() -> None:
    garbled = "count them words please"
    oracle = ScriptedOracle(
        [malformed_call(garbled, "c1"), malformed_call(garbled, "c2")]
    )
    entity = summon(oracle, Tome([word_count]), max_repair_rounds=1)

    with pytest.raises(SpellCallParseError) as excinfo:
        await entity.ainvoke(user_input("count"))

    error = excinfo.value
    assert garbled in str(error)  # original text preserved for debugging
    assert error.rejected == [garbled]
    assert error.rounds == 2


async def test_invalid_arguments_get_correction_and_loop_completes() -> None:
    oracle = ScriptedOracle(
        [
            OracleResponse(
                text="",
                spell_calls=[
                    SpellCall(
                        spell="word_count",
                        arguments={"paragraph": "lux"},  # wrong argument name
                        call_id="c1",
                    )
                ],
            ),
            OracleResponse(
                text="",
                spell_calls=[
                    SpellCall(
                        spell="word_count", arguments={"text": "lux"}, call_id="c2"
                    )
                ],
            ),
            OracleResponse(text="One word."),
        ]
    )
    entity = summon(oracle, Tome([word_count]))

    result = await entity.ainvoke(user_input("count"))
    correction = result["messages"][2]
    assert correction["error"] is True
    assert "missing required argument(s): text" in correction["content"]
    assert "unexpected argument(s): paragraph" in correction["content"]
    assert result["messages"][-1]["content"] == "One word."


# --- PromptedSpellCalling ----------------------------------------------------


def test_prompted_prompt_contains_schemas_and_call_format() -> None:
    schemas = [
        {
            "name": "word_count",
            "description": "Count the words in a text.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        }
    ]
    messages = inject_spell_prompt([{"role": "user", "content": "hi"}], schemas)
    assert messages[0]["role"] == "system"
    prompt = messages[0]["content"]
    assert "word_count" in prompt
    assert "<spell_call>" in prompt and "</spell_call>" in prompt
    assert '"text"' in prompt  # the JSON Schema is included


def test_parse_spell_blocks_extracts_calls_and_prose() -> None:
    text = (
        "I will count.\n"
        "<spell_call>\n"
        '{"spell": "word_count", "arguments": {"text": "lux aeterna"}}\n'
        "</spell_call>\n"
        "Awaiting the result."
    )
    prose, calls = parse_spell_blocks(text)
    assert "I will count." in prose
    assert "<spell_call>" not in prose
    assert len(calls) == 1
    assert calls[0].spell == "word_count"
    assert calls[0].arguments == {"text": "lux aeterna"}


def test_parse_spell_blocks_recovers_bare_json_call() -> None:
    # Observed with small models on llama-server: the delimiter format is
    # ignored and a bare JSON call object is emitted instead.
    text = (
        '{"text": "lux aeterna semper", "spell": "word_count", '
        '"arguments": {"text": "lux aeterna semper"}}'
    )
    prose, calls = parse_spell_blocks(text)
    assert prose == ""
    assert len(calls) == 1
    assert calls[0].spell == "word_count"
    assert "__malformed_json__" in calls[0].arguments  # repair layer takes over


async def test_prompted_bare_json_call_is_repaired_and_cast() -> None:
    inner = ScriptedOracle(
        [
            OracleResponse(
                text='{"spell": "word_count", "arguments": {"text": "lux aeterna"}}'
            ),
            OracleResponse(text="Two words."),
        ]
    )
    entity = summon(inner, Tome([word_count]), spell_calling="prompted")

    omens = [
        omen
        async for omen in entity.astream(user_input("count"), mode="omens")
    ]
    repaired = [omen for omen in omens if isinstance(omen, SpellCallRepaired)]
    assert repaired and repaired[0].spell == "word_count"
    messages = omens[-1].aether["messages"]
    assert messages[2]["content"] == "2"  # the Spell actually ran
    assert messages[-1]["content"] == "Two words."


async def test_prompted_strategy_end_to_end_through_summon() -> None:
    inner = ScriptedOracle(
        [
            OracleResponse(
                text=(
                    "Casting.\n<spell_call>\n"
                    '{"spell": "word_count", "arguments": {"text": "lux aeterna"}}'
                    "\n</spell_call>"
                )
            ),
            OracleResponse(text="Two words."),
        ]
    )
    entity = summon(inner, Tome([word_count]), spell_calling="prompted")

    result = await entity.ainvoke(user_input("count 'lux aeterna'"))
    messages = result["messages"]
    assert messages[2]["content"] == "2"
    assert messages[-1]["content"] == "Two words."
    # The inner Oracle received injected schemas, never native tools.
    first_transcript, native_spells = inner.calls[0]
    assert native_spells is None
    assert "<spell_call>" in first_transcript[0]["content"]
    assert "word_count" in first_transcript[0]["content"]


# --- observability -----------------------------------------------------------


async def test_repair_omens_appear_in_astream() -> None:
    fenced = '```json\n{"text": "lux aeterna"}\n```'
    oracle = ScriptedOracle(
        [
            OracleResponse(
                text="",
                spell_calls=[
                    SpellCall(
                        spell="word_count",
                        arguments={"__malformed_json__": fenced},
                        call_id="c1",
                    ),
                    SpellCall(spell="ghost", arguments={}, call_id="c2"),
                ],
            ),
            OracleResponse(text="Done."),
        ]
    )
    entity = summon(oracle, Tome([word_count]))

    omens = [omen async for omen in entity.astream(user_input("go"), mode="omens")]
    repaired = [omen for omen in omens if isinstance(omen, SpellCallRepaired)]
    rejected = [omen for omen in omens if isinstance(omen, SpellCallRejected)]
    assert repaired and repaired[0].spell == "word_count"
    assert "malformed JSON" in repaired[0].detail
    assert rejected and rejected[0].spell == "ghost"
    assert "word_count" in rejected[0].reason  # available Spells listed
