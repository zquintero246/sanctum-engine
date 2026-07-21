"""Unit tests for the native OllamaOracle.

Always run: recorded fixtures replayed through httpx.MockTransport.
Covers native tool-call parsing, keep_alive/options payload wiring,
NDJSON streaming, and error mapping.
"""

import json
from pathlib import Path

import httpx
import pytest

from sanctum.oracle import OracleResponseError
from sanctum.oracle.ollama import OllamaOracle, build_payload, parse_chat_response

FIXTURES = Path(__file__).parent.parent / "fixtures"
HOST = "http://127.0.0.1:11434"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_oracle(handler, **kwargs) -> OllamaOracle:
    return OllamaOracle(
        arcana="qwen2.5:7b",
        host=HOST,
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def test_parse_chat_response_with_native_tool_calls() -> None:
    response = parse_chat_response(load_fixture("ollama_chat_tools.json"))
    assert response.text == ""
    call = response.spell_calls[0]
    assert call.spell == "word_count"
    assert call.arguments == {"text": "lux aeterna"}  # dict arguments pass through
    assert response.usage == {"prompt_tokens": 214, "completion_tokens": 28}


def test_build_payload_includes_keep_alive_options_and_tools() -> None:
    payload = build_payload(
        "qwen2.5:7b",
        [{"role": "user", "content": "count"}],
        [{"name": "word_count", "description": "d", "parameters": {}}],
        stream=False,
        keep_alive="10m",
        options={"temperature": 0.2, "num_ctx": 8192},
    )
    assert payload["keep_alive"] == "10m"
    assert payload["options"] == {"temperature": 0.2, "num_ctx": 8192}
    assert payload["tools"][0]["function"]["name"] == "word_count"


def test_build_payload_omits_unset_fields() -> None:
    payload = build_payload(
        "qwen2.5:7b", [{"role": "user", "content": "hi"}], None, stream=True
    )
    assert "keep_alive" not in payload
    assert "options" not in payload
    assert "tools" not in payload


async def test_generate_posts_to_api_chat_and_parses() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=load_fixture("ollama_chat_tools.json"))

    oracle = make_oracle(handler, keep_alive="10m", options={"temperature": 0.0})
    response = await oracle.generate([{"role": "user", "content": "count"}])

    assert captured["path"] == "/api/chat"
    assert captured["payload"]["keep_alive"] == "10m"
    assert captured["payload"]["options"] == {"temperature": 0.0}
    assert response.spell_calls[0].spell == "word_count"


async def test_stream_generate_parses_ndjson_until_done() -> None:
    body = (FIXTURES / "ollama_stream.ndjson").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    oracle = make_oracle(handler)
    prompt = [{"role": "user", "content": "?"}]
    chunks = [chunk async for chunk in oracle.stream_generate(prompt)]
    assert chunks == ["the ", "aether ", "stirs"]


async def test_404_hints_at_pulling_the_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model 'qwen2.5:7b' not found"})

    oracle = make_oracle(handler)
    with pytest.raises(OracleResponseError, match="ollama pull qwen2.5:7b"):
        await oracle.generate([{"role": "user", "content": "?"}])


def test_ollama_format_messages_translates_spell_vocabulary():
    from sanctum.oracle.ollama import format_messages

    wire = format_messages(
        [
            {"role": "user", "content": "count"},
            {
                "role": "assistant",
                "content": "",
                "spell_calls": [
                    {"call_id": "x1", "spell": "scry", "arguments": {"topic": "door"}}
                ],
            },
            {"role": "spell", "spell": "scry", "call_id": "x1", "content": "7"},
        ]
    )
    assert wire[1] == {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"function": {"name": "scry", "arguments": {"topic": "door"}}}
        ],
    }
    assert wire[2] == {"role": "tool", "content": "7"}
