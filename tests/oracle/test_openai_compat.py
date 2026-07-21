"""Unit tests for OpenAICompatibleOracle.

Always run: recorded fixtures are replayed through httpx.MockTransport —
no live server involved. Covers response/SSE parsing, defensive handling
of malformed tool arguments, payload construction, and the actionable
error mapping.
"""

import json
from pathlib import Path

import httpx
import pytest

from sanctum.oracle import (
    OracleConnectionError,
    OracleResponseError,
    OracleTimeoutError,
)
from sanctum.oracle.openai_compat import (
    OpenAICompatibleOracle,
    build_payload,
    parse_chat_completion,
    parse_sse_line,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"
BASE_URL = "http://127.0.0.1:11434/v1"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_oracle(handler, **kwargs) -> OpenAICompatibleOracle:
    return OpenAICompatibleOracle(
        arcana="qwen2.5:7b",
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


# --- parsing (pure functions over recorded fixtures) -----------------------


def test_parse_chat_completion_with_tool_calls() -> None:
    response = parse_chat_completion(load_fixture("openai_chat_completion_tools.json"))
    assert response.text == ""  # null content normalized
    assert len(response.spell_calls) == 1
    call = response.spell_calls[0]
    assert call.spell == "word_count"
    assert call.arguments == {"text": "lux aeterna"}  # JSON string decoded
    assert call.call_id == "call_abc123"
    assert response.usage == {"prompt_tokens": 214, "completion_tokens": 28}


def test_parse_chat_completion_text_only() -> None:
    response = parse_chat_completion(load_fixture("openai_chat_completion_text.json"))
    assert response.text == "The phrase has two words."
    assert response.spell_calls == []
    assert response.usage == {"prompt_tokens": 260, "completion_tokens": 9}


def test_malformed_tool_arguments_are_preserved_not_raised() -> None:
    response = parse_chat_completion(
        load_fixture("openai_chat_completion_malformed_tool.json")
    )
    call = response.spell_calls[0]
    assert call.spell == "word_count"
    assert call.arguments == {"__malformed_json__": '{"text": "lux aeterna'}


def test_parse_sse_line_extracts_deltas_and_ignores_noise() -> None:
    content = 'data: {"choices":[{"delta":{"content":"the "}}]}'
    assert parse_sse_line(content) == "the "
    assert parse_sse_line("data: [DONE]") is None
    assert parse_sse_line("") is None
    assert parse_sse_line(": keep-alive comment") is None
    assert parse_sse_line("data: {not json at all") is None
    assert parse_sse_line('data: {"choices":[{"delta":{}}]}') is None


def test_build_payload_maps_spells_to_tools_and_merges_extra_body() -> None:
    payload = build_payload(
        "qwen2.5:7b",
        [{"role": "user", "content": "count"}],
        [{"name": "word_count", "description": "d", "parameters": {}}],
        stream=False,
        extra_body={"temperature": 0.2},
    )
    assert payload["model"] == "qwen2.5:7b"
    assert payload["stream"] is False
    assert payload["temperature"] == 0.2
    assert payload["tools"] == [
        {
            "type": "function",
            "function": {"name": "word_count", "description": "d", "parameters": {}},
        }
    ]


# --- end-to-end over MockTransport -----------------------------------------


async def test_generate_posts_payload_and_parses_response() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content)
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(
            200, json=load_fixture("openai_chat_completion_tools.json")
        )

    oracle = make_oracle(handler, api_key="secret-key")
    response = await oracle.generate(
        [{"role": "user", "content": "count 'lux aeterna'"}],
        spells=[{"name": "word_count", "description": "d", "parameters": {}}],
    )

    assert captured["path"] == "/v1/chat/completions"
    assert captured["payload"]["tools"][0]["function"]["name"] == "word_count"
    assert captured["auth"] == "Bearer secret-key"
    assert response.spell_calls[0].arguments == {"text": "lux aeterna"}


async def test_stream_generate_parses_sse() -> None:
    sse_body = (FIXTURES / "openai_stream.sse").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(
            200, content=sse_body, headers={"Content-Type": "text/event-stream"}
        )

    oracle = make_oracle(handler)
    prompt = [{"role": "user", "content": "?"}]
    chunks = [chunk async for chunk in oracle.stream_generate(prompt)]
    assert chunks == ["the ", "aether ", "stirs"]


# --- error mapping ----------------------------------------------------------


async def test_connection_refused_names_the_server_and_the_fix() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("[WinError 10061] connection refused")

    oracle = make_oracle(handler)
    with pytest.raises(OracleConnectionError) as excinfo:
        await oracle.generate([{"role": "user", "content": "?"}])
    message = str(excinfo.value)
    assert BASE_URL in message
    assert "running" in message


async def test_timeout_suggests_raising_the_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow")

    oracle = make_oracle(handler)
    with pytest.raises(OracleTimeoutError) as excinfo:
        await oracle.generate([{"role": "user", "content": "?"}])
    message = str(excinfo.value)
    assert "120" in message  # the configured timeout, actionable
    assert "timeout" in message


async def test_404_hints_at_pulling_the_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404, json={"error": {"message": "model 'qwen2.5:7b' not found"}}
        )

    oracle = make_oracle(handler)
    with pytest.raises(OracleResponseError) as excinfo:
        await oracle.generate([{"role": "user", "content": "?"}])
    message = str(excinfo.value)
    assert "404" in message
    assert "ollama pull qwen2.5:7b" in message


async def test_stream_error_status_is_mapped_too() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model not found"})

    oracle = make_oracle(handler)
    with pytest.raises(OracleResponseError, match="404"):
        async for _ in oracle.stream_generate([{"role": "user", "content": "?"}]):
            pass


def test_format_messages_translates_spell_vocabulary():
    from sanctum.oracle.openai_compat import format_messages

    transcript = [
        {"role": "system", "content": "You are a scryer."},
        {"role": "user", "content": "count the seals"},
        {
            "role": "assistant",
            "content": "",
            "spell_calls": [
                {"call_id": "abc123", "spell": "scry", "arguments": {"topic": "door"}}
            ],
        },
        {"role": "spell", "spell": "scry", "call_id": "abc123", "content": "7"},
        {
            "role": "spell",
            "spell": "scry",
            "call_id": "zzz",
            "content": "SpellExecutionError: boom",
            "error": True,
        },
        {"role": "assistant", "content": "Seven seals."},
    ]
    wire = format_messages(transcript)

    assert wire[0] == {"role": "system", "content": "You are a scryer."}
    call_message = wire[2]
    assert call_message["content"] is None  # null, not "" — templates skip it
    assert call_message["tool_calls"] == [
        {
            "id": "abc123",
            "type": "function",
            "function": {"name": "scry", "arguments": '{"topic": "door"}'},
        }
    ]
    assert wire[3] == {"role": "tool", "tool_call_id": "abc123", "content": "7"}
    # error markers are sanctum-internal; the wire only carries the text
    assert wire[4] == {
        "role": "tool",
        "tool_call_id": "zzz",
        "content": "SpellExecutionError: boom",
    }
    assert wire[5] == {"role": "assistant", "content": "Seven seals."}


async def test_stream_response_accumulates_tool_calls():
    payload = (FIXTURES / "openai_stream_tools.sse").read_text(encoding="utf-8")

    def handler(request):
        return httpx.Response(
            200, content=payload, headers={"content-type": "text/event-stream"}
        )

    oracle = make_oracle(handler)
    messages = [{"role": "user", "content": "go"}]
    items = [item async for item in oracle.stream_response(messages)]
    final = items[-1]
    assert not [item for item in items[:-1] if not isinstance(item, str)]
    assert final.text == ""
    assert len(final.spell_calls) == 1
    call = final.spell_calls[0]
    assert call.spell == "scry"
    assert call.arguments == {"topic": "door"}
    assert call.call_id == "call_abc"


async def test_stream_response_streams_text_then_final():
    body = "\n".join(
        [
            'data: {"choices":[{"delta":{"content":"the "}}]}',
            "",
            'data: {"choices":[{"delta":{"content":"door"}}]}',
            "",
            "data: [DONE]",
            "",
        ]
    )

    def handler(request):
        return httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )

    oracle = make_oracle(handler)
    messages = [{"role": "user", "content": "?"}]
    items = [item async for item in oracle.stream_response(messages)]
    assert items[:-1] == ["the ", "door"]
    assert items[-1].text == "the door" and items[-1].spell_calls == []
