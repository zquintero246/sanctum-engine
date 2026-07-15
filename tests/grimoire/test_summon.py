"""Tests for summon: the canonical ReAct loop over the public API.

Covers the full message sequence of a scripted Entity casting two Spells,
and Spell failure surfacing as an error message the loop survives.
"""

from sanctum import Tome, spell, summon
from sanctum.oracle import OracleResponse, ScriptedOracle, SpellCall


@spell
def word_count(text: str) -> int:
    """Count the words in a text."""
    return len(text.split())


@spell
def shout(text: str) -> str:
    """Uppercase a text and add an exclamation mark."""
    return text.upper() + "!"


async def test_summoned_entity_runs_full_react_sequence() -> None:
    tome = Tome([word_count, shout])
    oracle = ScriptedOracle(
        [
            OracleResponse(
                text="Let me consult my Spells.",
                spell_calls=[
                    SpellCall(
                        spell="word_count",
                        arguments={"text": "lux aeterna"},
                        call_id="call-1",
                    ),
                    SpellCall(
                        spell="shout", arguments={"text": "fiat"}, call_id="call-2"
                    ),
                ],
            ),
            OracleResponse(text="Two words; the shout is FIAT!."),
        ]
    )
    entity = summon(oracle, tome, role="You are a scribe.")

    result = await entity.ainvoke(
        {"messages": [{"role": "user", "content": "Count and shout."}]}
    )
    messages = result["messages"]

    assert [message["role"] for message in messages] == [
        "user",
        "assistant",
        "spell",
        "spell",
        "assistant",
    ]
    assert messages[1]["content"] == "Let me consult my Spells."
    assert [call["spell"] for call in messages[1]["spell_calls"]] == [
        "word_count",
        "shout",
    ]
    assert messages[2] == {
        "role": "spell",
        "spell": "word_count",
        "call_id": "call-1",
        "content": "2",
    }
    assert messages[3] == {
        "role": "spell",
        "spell": "shout",
        "call_id": "call-2",
        "content": "FIAT!",
    }
    assert messages[4] == {
        "role": "assistant",
        "content": "Two words; the shout is FIAT!.",
    }

    # The Oracle was consulted twice: with the Spell schemas and, the
    # second time, with the system role plus the whole transcript so far.
    assert len(oracle.calls) == 2
    first_transcript, first_spells = oracle.calls[0]
    assert first_transcript[0] == {"role": "system", "content": "You are a scribe."}
    assert [schema["name"] for schema in first_spells] == ["word_count", "shout"]
    second_transcript, _ = oracle.calls[1]
    assert len(second_transcript) == 5  # system + user + assistant + 2 spell results


async def test_spell_failure_becomes_error_message_and_loop_survives() -> None:
    @spell
    def doomed(text: str) -> str:
        """Always fails."""
        raise ValueError("the stars are wrong")

    oracle = ScriptedOracle(
        [
            OracleResponse(
                text="Casting.",
                spell_calls=[
                    SpellCall(spell="doomed", arguments={"text": "x"}, call_id="call-1")
                ],
            ),
            OracleResponse(text="The Spell failed; I will answer directly."),
        ]
    )
    entity = summon(oracle, Tome([doomed]))

    result = await entity.ainvoke(
        {"messages": [{"role": "user", "content": "Try the doomed Spell."}]}
    )
    messages = result["messages"]

    assert [message["role"] for message in messages] == [
        "user",
        "assistant",
        "spell",
        "assistant",
    ]
    error_message = messages[2]
    assert error_message["error"] is True
    assert "doomed" in error_message["content"]
    assert "ValueError" in error_message["content"]
    assert messages[-1]["content"] == "The Spell failed; I will answer directly."


async def test_spell_request_without_tome_becomes_error_message() -> None:
    oracle = ScriptedOracle(
        [
            OracleResponse(
                text="Casting into the void.",
                spell_calls=[SpellCall(spell="ghost", call_id="call-1")],
            ),
            OracleResponse(text="No Spells here; answering directly."),
        ]
    )
    entity = summon(oracle)  # no Tome

    result = await entity.ainvoke(
        {"messages": [{"role": "user", "content": "Cast something."}]}
    )
    messages = result["messages"]
    assert messages[2]["error"] is True
    assert "without a Tome" in messages[2]["content"]
    assert messages[-1]["content"] == "No Spells here; answering directly."
