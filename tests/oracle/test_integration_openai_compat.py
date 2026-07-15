"""Opt-in integration tests against any OpenAI-compatible server.

Skipped unless SANCTUM_TEST_OPENAI_COMPAT_URL is set — the exact base_url
handed to OpenAICompatibleOracle, version prefix included, e.g.
``http://127.0.0.1:8080/v1`` (llama.cpp's llama-server) or
``http://127.0.0.1:11434/v1`` (Ollama). Model name via
SANCTUM_TEST_OPENAI_COMPAT_MODEL (llama-server ignores it and serves its
loaded model; Ollama requires a pulled model). See CONTRIBUTING.md.

Smoke tests of transport, parsing, and the robust tool-calling loop
end-to-end against a real server — never model quality: with small local
models the tool may be cast natively, via the prompted fallback, after
repairs, or not at all; the contract under test is that the engine
finishes with an assistant answer instead of crashing.
"""

import os

import pytest

BASE_URL = os.environ.get("SANCTUM_TEST_OPENAI_COMPAT_URL")
MODEL = os.environ.get("SANCTUM_TEST_OPENAI_COMPAT_MODEL", "qwen2.5:0.5b")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not BASE_URL,
        reason="SANCTUM_TEST_OPENAI_COMPAT_URL not set (see CONTRIBUTING.md)",
    ),
]

PROMPT = [{"role": "user", "content": "Answer with one short sentence: what is fire?"}]


def make_oracle():
    from sanctum.oracle.openai_compat import OpenAICompatibleOracle

    return OpenAICompatibleOracle(
        arcana=MODEL, base_url=BASE_URL, extra_body={"temperature": 0.0}
    )


async def test_generate_answers() -> None:
    response = await make_oracle().generate(PROMPT)
    assert response.text.strip()


async def test_stream_yields_incremental_chunks() -> None:
    chunks = [chunk async for chunk in make_oracle().stream_generate(PROMPT)]
    assert len(chunks) > 1
    assert "".join(chunks).strip()


async def test_robust_tool_calling_end_to_end() -> None:
    from sanctum import Tome, spell, summon
    from sanctum.omens import (
        RiteManifested,
        SpellCallRejected,
        SpellCallRepaired,
    )

    executions: list[str] = []

    @spell
    def word_count(text: str) -> int:
        """Count the words in a text."""
        executions.append(text)
        return len(text.split())

    entity = summon(
        make_oracle(),
        Tome([word_count]),
        role=(
            "You are a scribe. To count words you MUST cast the word_count "
            "Spell instead of counting yourself."
        ),
        spell_calling="auto",
    )
    omens = [
        omen
        async for omen in entity.astream(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Use word_count to count the words in "
                            "'lux aeterna semper'."
                        ),
                    }
                ]
            },
            mode="omens",
        )
    ]

    manifested = omens[-1]
    assert isinstance(manifested, RiteManifested)
    final = manifested.aether["messages"][-1]
    assert final["role"] == "assistant"
    assert final["content"].strip() or executions  # answered, or at least cast

    repaired = [o for o in omens if isinstance(o, SpellCallRepaired)]
    rejected = [o for o in omens if isinstance(o, SpellCallRejected)]
    print(
        f"\n[integration] tool executed: {bool(executions)} "
        f"(calls={executions!r}); repaired: {len(repaired)}; "
        f"rejected: {len(rejected)}"
    )
