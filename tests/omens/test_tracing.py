"""Tests for TraceRecorder and render_trace.

Covers trace completeness for a summon run with spell calls, the
self-contained HTML viewer, and that recording never alters results.
"""

import json
from pathlib import Path

from sanctum import Tome, spell, summon
from sanctum.omens import TraceRecorder, render_trace
from sanctum.oracle import OracleResponse, ScriptedOracle, SpellCall


@spell
def word_count(text: str) -> int:
    """Count the words in a text."""
    return len(text.split())


@spell
def shout(text: str) -> str:
    """Uppercase a text and add an exclamation mark."""
    return text.upper() + "!"


def build_script() -> list[OracleResponse]:
    return [
        OracleResponse(
            text="Consulting my Spells.",
            spell_calls=[
                SpellCall(
                    spell="word_count",
                    arguments={"text": "lux aeterna"},
                    call_id="call-1",
                ),
                SpellCall(spell="shout", arguments={"text": "fiat"}, call_id="call-2"),
            ],
            usage={"prompt_tokens": 100, "completion_tokens": 20},
        ),
        OracleResponse(text="Two words; FIAT!."),
    ]


USER_INPUT = {"messages": [{"role": "user", "content": "Count and shout."}]}


async def run_traced(tmp_path: Path) -> tuple[dict, Path]:
    trace_path = tmp_path / "run.sanctum-trace.json"
    recorder = TraceRecorder(trace_path)
    entity = summon(
        ScriptedOracle(build_script()), Tome([word_count, shout]), wards=[recorder]
    )
    await entity.ainvoke(USER_INPUT, invocation_id="inv-traced")
    return json.loads(trace_path.read_text(encoding="utf-8")), trace_path


async def test_trace_contains_graph_supersteps_and_spell_calls(
    tmp_path: Path,
) -> None:
    trace, _ = await run_traced(tmp_path)

    assert trace["format"] == "sanctum-trace/1"
    assert trace["invocation_id"] == "inv-traced"

    graph = trace["graph"]
    assert set(graph["sigils"]) == {"oracle", "spells"}
    assert graph["edges"]["__start__"] == ["oracle"]
    assert graph["conditional_edges"]["oracle"] == ["*"]

    supersteps = trace["supersteps"]
    assert len(supersteps) == 3  # oracle -> spells -> oracle
    assert supersteps[0]["frontier"] == ["oracle"]
    assert all(
        sigil.get("duration_ms", 0) >= 0
        for entry in supersteps
        for sigil in entry["sigils"]
    )

    calls = {call["spell"]: call for call in trace["spell_calls"]}
    assert set(calls) == {"word_count", "shout"}
    assert calls["word_count"]["arguments"] == {"text": "lux aeterna"}
    assert calls["word_count"]["result"] == "2"
    assert calls["shout"]["result"] == "FIAT!"
    assert trace["result"]["messages"][-1]["content"] == "Two words; FIAT!."


async def test_render_trace_produces_self_contained_html(tmp_path: Path) -> None:
    _, trace_path = await run_traced(tmp_path)

    html_path = render_trace(trace_path)
    assert html_path.suffix == ".html"
    content = html_path.read_text(encoding="utf-8")

    assert content.lstrip().startswith("<!DOCTYPE html")
    assert "</html>" in content
    assert "<svg" in content  # static graph view
    assert "oracle" in content and "spells" in content
    assert "word_count" in content  # spell-call table
    # Self-contained: no external requests of any kind.
    assert "http://" not in content
    assert "https://" not in content


async def test_recorder_does_not_alter_the_result(tmp_path: Path) -> None:
    tome = Tome([word_count, shout])

    bare = summon(ScriptedOracle(build_script()), tome)
    without_recorder = await bare.ainvoke(USER_INPUT)

    recorder = TraceRecorder(tmp_path / "check.sanctum-trace.json")
    traced = summon(ScriptedOracle(build_script()), tome, wards=[recorder])
    with_recorder = await traced.ainvoke(USER_INPUT)

    assert with_recorder == without_recorder
