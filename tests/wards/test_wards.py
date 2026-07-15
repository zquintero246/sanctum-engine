"""Tests for the Ward middleware system.

Covers the AuditWard JSONL trail, UsageWard accounting over a summon
loop, delta transformation, WardRejection with DeltaRejected and
on_error, and pipeline ordering.
"""

import json
from pathlib import Path
from typing import Any

from sanctum import (
    END,
    Ritual,
    SigilPolicy,
    Tome,
    Ward,
    WardRejection,
    spell,
    summon,
)
from sanctum.omens import DeltaRejected, RiteManifested
from sanctum.oracle import OracleResponse, ScriptedOracle, SpellCall
from sanctum.wards import AuditWard, RedactWard, UsageWard

Aether = dict[str, Any]


def build_linear_ritual() -> Ritual:
    ritual = Ritual()
    ritual.add_sigil("cleanse", lambda aether: {"text": aether["text"].strip()})
    ritual.add_sigil("transmute", lambda aether: {"text": aether["text"].upper()})
    ritual.add_sigil("seal_it", lambda aether: {"sealed": True})
    ritual.set_entry_point("cleanse")
    ritual.add_edge("cleanse", "transmute")
    ritual.add_edge("transmute", "seal_it")
    ritual.add_edge("seal_it", END)
    return ritual


async def test_audit_ward_writes_valid_and_complete_jsonl(tmp_path: Path) -> None:
    trail = tmp_path / "audit.jsonl"
    rite = build_linear_ritual().compile(wards=[AuditWard(trail)])

    await rite.ainvoke({"text": "  lux  "})

    lines = trail.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3  # one entry per superstep's delta
    entries = [json.loads(line) for line in lines]
    assert [entry["sigil"] for entry in entries] == [
        "cleanse",
        "transmute",
        "seal_it",
    ]
    assert entries[0]["delta"] == {"text": "lux"}
    assert entries[1]["delta"] == {"text": "LUX"}
    assert entries[2]["delta"] == {"sealed": True}
    assert all(isinstance(entry["timestamp"], float) for entry in entries)


async def test_usage_ward_accumulates_oracle_usage_in_summon() -> None:
    @spell
    def word_count(text: str) -> int:
        """Count the words in a text."""
        return len(text.split())

    oracle = ScriptedOracle(
        [
            OracleResponse(
                text="",
                spell_calls=[
                    SpellCall(
                        spell="word_count",
                        arguments={"text": "lux aeterna"},
                        call_id="c1",
                    )
                ],
                usage={"prompt_tokens": 100, "completion_tokens": 20},
            ),
            OracleResponse(
                text="Two words.",
                usage={"prompt_tokens": 150, "completion_tokens": 10},
            ),
        ]
    )
    usage = UsageWard()
    entity = summon(oracle, Tome([word_count]), wards=[usage])

    await entity.ainvoke({"messages": [{"role": "user", "content": "count"}]})

    summary = usage.summary()
    assert summary["total"] == {
        "calls": 2,
        "prompt_tokens": 250,
        "completion_tokens": 30,
    }
    assert summary["by_sigil"]["oracle"]["calls"] == 2
    assert summary["by_sigil"]["oracle"]["prompt_tokens"] == 250


async def test_transforming_ward_changes_the_final_aether() -> None:
    class UppercaseWard(Ward):
        async def after_sigil(
            self, name: str, aether: Aether, delta: dict
        ) -> dict:
            if "text" in delta:
                delta = {**delta, "text": delta["text"].upper()}
            return delta

    ritual = Ritual()
    ritual.add_sigil("whisper", lambda aether: {"text": "lux aeterna"})
    ritual.set_entry_point("whisper")
    ritual.add_edge("whisper", END)
    rite = ritual.compile(wards=[UppercaseWard()])

    result = await rite.ainvoke({})
    assert result["text"] == "LUX AETERNA"


async def test_redact_ward_masks_secrets_before_the_aether() -> None:
    ritual = Ritual()
    ritual.add_sigil(
        "leaky",
        lambda aether: {"note": "the key is sk-abc123 and mail a@b.com"},
    )
    ritual.set_entry_point("leaky")
    ritual.add_edge("leaky", END)
    rite = ritual.compile(
        wards=[RedactWard([r"sk-\w+", r"[\w.]+@[\w.]+"])]
    )

    result = await rite.ainvoke({})
    assert result["note"] == "the key is [REDACTED] and mail [REDACTED]"


async def test_ward_rejection_emits_omen_and_triggers_on_error() -> None:
    class ForbidWard(Ward):
        async def after_sigil(
            self, name: str, aether: Aether, delta: dict
        ) -> dict:
            if delta.get("forbidden"):
                raise WardRejection("forbidden content in delta")
            return delta

    def risky(aether: Aether) -> Aether:
        return {"forbidden": True}

    def mend(aether: Aether) -> Aether:
        failure = aether["__errors__"][-1]
        return {"mended": failure["type"]}

    ritual = Ritual()
    ritual.add_sigil("risky", risky, policy=SigilPolicy(on_error="mend"))
    ritual.add_sigil("mend", mend)
    ritual.set_entry_point("risky")
    ritual.add_edge("risky", END)
    ritual.add_edge("mend", END)
    rite = ritual.compile(wards=[ForbidWard()])

    omens = [omen async for omen in rite.astream({}, mode="omens")]

    rejections = [omen for omen in omens if isinstance(omen, DeltaRejected)]
    assert len(rejections) == 1
    assert rejections[0].sigil == "risky"
    assert rejections[0].ward == "ForbidWard"
    assert "forbidden content" in rejections[0].reason

    manifested = omens[-1]
    assert isinstance(manifested, RiteManifested)
    # The vetoed delta never reached the Aether; the fallback ran instead.
    assert "forbidden" not in manifested.aether
    assert manifested.aether["mended"] == "WardRejection"


async def test_pipeline_applies_wards_in_registration_order() -> None:
    class AppendMark(Ward):
        def __init__(self, mark: str) -> None:
            self._mark = mark

        async def after_sigil(
            self, name: str, aether: Aether, delta: dict
        ) -> dict:
            if "trail" in delta:
                delta = {**delta, "trail": delta["trail"] + self._mark}
            return delta

    ritual = Ritual()
    ritual.add_sigil("origin", lambda aether: {"trail": "x"})
    ritual.set_entry_point("origin")
    ritual.add_edge("origin", END)
    rite = ritual.compile(wards=[AppendMark("A"), AppendMark("B")])

    result = await rite.ainvoke({})
    assert result["trail"] == "xAB"  # A ran first, B saw A's output
