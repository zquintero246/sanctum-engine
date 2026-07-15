"""Tests for ScriptedOracle: chunked streaming and script exhaustion."""

import pytest

from sanctum.oracle import OracleResponse, ScriptedOracle


async def test_stream_generate_yields_chunks_reassembling_the_text() -> None:
    oracle = ScriptedOracle(["the aether stirs"])
    chunks = [
        chunk
        async for chunk in oracle.stream_generate(
            [{"role": "user", "content": "speak"}]
        )
    ]
    assert len(chunks) == 3
    assert "".join(chunks) == "the aether stirs"


async def test_string_entries_are_shorthand_for_text_responses() -> None:
    oracle = ScriptedOracle(["a plain answer"])
    response = await oracle.generate([{"role": "user", "content": "?"}])
    assert response == OracleResponse(text="a plain answer")


async def test_exhausted_script_raises_runtime_error() -> None:
    oracle = ScriptedOracle([])
    with pytest.raises(RuntimeError, match="exhausted"):
        await oracle.generate([{"role": "user", "content": "?"}])
