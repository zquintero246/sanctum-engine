"""An Oracle speaking the lingua franca of local model servers.

OpenAI-compatible chat-completions adapter — the primary Oracle of the
local ecosystem. One adapter covers every server exposing
``POST /v1/chat/completions``: Ollama (under ``/v1``), llama.cpp's
``llama-server``, vLLM, LM Studio, and others. Optional dependency httpx
(``pip install sanctum-engine[openai-compat]``); importing this module
never fails, the dependency is required at construction time.

Spell schemas are forwarded as OpenAI ``tools``; tool calls come back as
SpellCalls. Parsing is deliberately defensive about the failure modes of
local 7-14B models: string arguments are JSON-decoded, malformed argument
JSON is preserved under ``"__malformed_json__"`` (the Spell then fails
readably and the transcript feeds the error back to the model), and null
content is normalized to "". Transport failures raise OracleError
subclasses with actionable messages.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from sanctum.oracle._shared import (
    map_transport_error,
    parse_arguments,
    raise_for_status,
    require_httpx,
)
from sanctum.oracle.core import Oracle, OracleResponse, SpellCall


def build_payload(
    arcana: str,
    messages: Sequence[Mapping[str, Any]],
    spells: Sequence[Mapping[str, Any]] | None,
    *,
    stream: bool,
    extra_body: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the /chat/completions request body.

    Spell schemas map to OpenAI ``tools``; `extra_body` entries (e.g.
    ``temperature``, ``max_tokens``) merge into the top level last, so
    they can override anything.
    """
    payload: dict[str, Any] = {
        "model": arcana,
        "messages": [dict(message) for message in messages],
        "stream": stream,
    }
    if spells:
        payload["tools"] = [
            {"type": "function", "function": dict(schema)} for schema in spells
        ]
    if extra_body:
        payload.update(extra_body)
    return payload


def parse_chat_completion(data: Mapping[str, Any]) -> OracleResponse:
    """Map an OpenAI-shaped chat completion onto an OracleResponse.

    Tolerates the quirks of local servers: missing ``content`` (null when
    only tool calls are returned), missing ``usage``, and tool-call
    arguments as either JSON strings or malformed JSON (see
    ``parse_arguments``).
    """
    choices = data.get("choices") or [{}]
    message = choices[0].get("message") or {}
    spell_calls: list[SpellCall] = []
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        kwargs: dict[str, Any] = {
            "spell": function.get("name", ""),
            "arguments": parse_arguments(function.get("arguments")),
        }
        if call.get("id"):
            kwargs["call_id"] = call["id"]
        spell_calls.append(SpellCall(**kwargs))
    usage_raw = data.get("usage") or {}
    usage = {
        key: usage_raw[key]
        for key in ("prompt_tokens", "completion_tokens")
        if usage_raw.get(key) is not None
    }
    return OracleResponse(
        text=message.get("content") or "", spell_calls=spell_calls, usage=usage
    )


def parse_sse_line(line: str) -> str | None:
    """Extract the content delta from one SSE line.

    Returns the text chunk, or None for non-data lines, empty deltas,
    ``[DONE]`` terminators, and unparseable payloads (skipped, never
    raised — a garbled keep-alive must not kill the stream).
    """
    line = line.strip()
    if not line.startswith("data:"):
        return None
    data = line[len("data:") :].strip()
    if not data or data == "[DONE]":
        return None
    try:
        chunk = json.loads(data)
    except ValueError:
        return None
    choices = chunk.get("choices") or []
    if not choices:
        return None
    return (choices[0].get("delta") or {}).get("content") or None


class OpenAICompatibleOracle(Oracle):
    """The voice behind any /v1/chat/completions door.

    `arcana` is the model name as the server knows it; `base_url` the API
    root including the version prefix (e.g. ``http://127.0.0.1:11434/v1``
    for Ollama, ``http://127.0.0.1:8080/v1`` for llama-server). `api_key`
    is sent as a Bearer token when given (vLLM/LM Studio setups often
    require one, Ollama does not). `extra_body` merges extra sampling
    fields into every request. `transport` injects an httpx transport —
    used by the unit tests to replay recorded responses.
    """

    def __init__(
        self,
        arcana: str,
        base_url: str = "http://127.0.0.1:11434/v1",
        api_key: str | None = None,
        timeout: float = 120.0,
        extra_body: Mapping[str, Any] | None = None,
        transport: Any | None = None,
    ) -> None:
        require_httpx("openai-compat")  # fail at construction, with guidance
        self.arcana = arcana
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._extra_body = dict(extra_body) if extra_body else None
        self._transport = transport

    def _client(self) -> Any:
        httpx = require_httpx("openai-compat")
        headers = (
            {"Authorization": f"Bearer {self._api_key}"} if self._api_key else None
        )
        return httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            headers=headers,
            transport=self._transport,
        )

    async def generate(
        self,
        messages: Sequence[Mapping[str, Any]],
        spells: Sequence[Mapping[str, Any]] | None = None,
    ) -> OracleResponse:
        """Ask for a complete answer (non-streaming).

        Raises:
            OracleConnectionError: The server is unreachable.
            OracleTimeoutError: No answer within `timeout`.
            OracleResponseError: The server answered with an error status.
        """
        payload = build_payload(
            self.arcana, messages, spells, stream=False, extra_body=self._extra_body
        )
        try:
            async with self._client() as client:
                response = await client.post("/chat/completions", json=payload)
        except Exception as exc:
            mapped = map_transport_error(
                exc, base_url=self._base_url, timeout=self._timeout
            )
            if mapped is not None:
                raise mapped from exc
            raise
        raise_for_status(
            response.status_code,
            response.text,
            base_url=self._base_url,
            arcana=self.arcana,
        )
        return parse_chat_completion(response.json())

    async def stream_generate(
        self,
        messages: Sequence[Mapping[str, Any]],
        spells: Sequence[Mapping[str, Any]] | None = None,
    ) -> AsyncIterator[str]:
        """Yield content chunks from the server's SSE stream.

        Raises the same OracleError subclasses as ``generate``; errors
        surface on the first iteration.
        """
        payload = build_payload(
            self.arcana, messages, spells, stream=True, extra_body=self._extra_body
        )
        try:
            async with self._client() as client, client.stream(
                "POST", "/chat/completions", json=payload
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode(
                        "utf-8", errors="replace"
                    )
                    raise_for_status(
                        response.status_code,
                        body,
                        base_url=self._base_url,
                        arcana=self.arcana,
                    )
                async for line in response.aiter_lines():
                    content = parse_sse_line(line)
                    if content:
                        yield content
        except Exception as exc:
            mapped = map_transport_error(
                exc, base_url=self._base_url, timeout=self._timeout
            )
            if mapped is not None:
                raise mapped from exc
            raise
