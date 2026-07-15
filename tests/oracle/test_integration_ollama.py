"""Opt-in integration tests against a live local Ollama.

Skipped unless SANCTUM_TEST_OLLAMA_URL is set (e.g.
``http://127.0.0.1:11434``) with a small model pulled — default
``qwen2.5:0.5b``, override with SANCTUM_TEST_OLLAMA_MODEL. See
CONTRIBUTING.md for the full recipe. These are smoke tests of transport
and parsing against a real server, not model-quality tests.
"""

import os

import pytest

OLLAMA_URL = os.environ.get("SANCTUM_TEST_OLLAMA_URL")
MODEL = os.environ.get("SANCTUM_TEST_OLLAMA_MODEL", "qwen2.5:0.5b")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not OLLAMA_URL, reason="SANCTUM_TEST_OLLAMA_URL not set (see CONTRIBUTING.md)"
    ),
]

PROMPT = [{"role": "user", "content": "Answer with one short sentence: what is fire?"}]


async def test_native_generate_answers() -> None:
    from sanctum.oracle.ollama import OllamaOracle

    oracle = OllamaOracle(arcana=MODEL, host=OLLAMA_URL, options={"temperature": 0.0})
    response = await oracle.generate(PROMPT)
    assert response.text.strip()
    assert response.usage.get("completion_tokens", 0) > 0


async def test_native_stream_yields_incremental_chunks() -> None:
    from sanctum.oracle.ollama import OllamaOracle

    oracle = OllamaOracle(arcana=MODEL, host=OLLAMA_URL, options={"temperature": 0.0})
    chunks = [chunk async for chunk in oracle.stream_generate(PROMPT)]
    assert len(chunks) > 1
    assert "".join(chunks).strip()


async def test_openai_compat_generate_answers() -> None:
    from sanctum.oracle.openai_compat import OpenAICompatibleOracle

    oracle = OpenAICompatibleOracle(arcana=MODEL, base_url=f"{OLLAMA_URL}/v1")
    response = await oracle.generate(PROMPT)
    assert response.text.strip()


async def test_openai_compat_stream_yields_incremental_chunks() -> None:
    from sanctum.oracle.openai_compat import OpenAICompatibleOracle

    oracle = OpenAICompatibleOracle(arcana=MODEL, base_url=f"{OLLAMA_URL}/v1")
    chunks = [chunk async for chunk in oracle.stream_generate(PROMPT)]
    assert len(chunks) > 1
    assert "".join(chunks).strip()
