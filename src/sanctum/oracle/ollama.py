"""An Oracle that speaks through a local Ollama daemon, natively.

Native ``/api/chat`` adapter. Prefer this over OpenAICompatibleOracle
when you want Ollama-specific control: `keep_alive` (how long the model
stays loaded) and `options` (temperature, num_ctx, and every other Ollama
runtime option). Optional dependency httpx
(``pip install sanctum-engine[ollama]``); importing this module never
fails, the dependency is required at construction time.

Spell schemas are forwarded as Ollama ``tools`` (native tool calling);
arguments arrive as dicts but are still parsed defensively — see
``sanctum.oracle._shared.parse_arguments`` for how malformed output from
small local models is survived. Transport failures raise OracleError
subclasses with actionable messages. Streaming uses Ollama's native
NDJSON (one JSON object per line), not SSE.
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


def format_messages(
    messages: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Translate sanctum's transcript into Ollama's native chat format.

    Same rationale as the OpenAI adapter's translation: sent verbatim,
    the chat template would drop ``role: "spell"`` results and the model
    would never see its own tool output. Ollama's native shape differs
    from OpenAI's — ``tool_calls`` carry ``arguments`` as a dict (not a
    JSON string) and results travel as ``role: "tool"``.
    """
    formatted: list[dict[str, Any]] = []
    for original in messages:
        message = dict(original)
        if message.get("role") == "assistant" and message.get("spell_calls"):
            formatted.append(
                {
                    "role": "assistant",
                    "content": message.get("content") or "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": call.get("spell", ""),
                                "arguments": dict(call.get("arguments", {})),
                            }
                        }
                        for call in message["spell_calls"]
                    ],
                }
            )
            continue
        if message.get("role") == "spell":
            formatted.append(
                {"role": "tool", "content": str(message.get("content", ""))}
            )
            continue
        message.pop("spell_calls", None)
        message.pop("error", None)
        formatted.append(message)
    return formatted


def build_payload(
    arcana: str,
    messages: Sequence[Mapping[str, Any]],
    spells: Sequence[Mapping[str, Any]] | None,
    *,
    stream: bool,
    keep_alive: str | int | None = None,
    options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the /api/chat request body.

    The transcript is translated through ``format_messages`` (sanctum
    spell vocabulary → Ollama tool vocabulary); Spell schemas map to
    Ollama ``tools``; `keep_alive` and `options` (temperature, num_ctx,
    ...) are included only when set, deferring to the server's defaults
    otherwise.
    """
    payload: dict[str, Any] = {
        "model": arcana,
        "messages": format_messages(messages),
        "stream": stream,
    }
    if spells:
        payload["tools"] = [
            {"type": "function", "function": dict(schema)} for schema in spells
        ]
    if keep_alive is not None:
        payload["keep_alive"] = keep_alive
    if options:
        payload["options"] = dict(options)
    return payload


def parse_chat_response(data: Mapping[str, Any]) -> OracleResponse:
    """Map a native /api/chat response onto an OracleResponse.

    Tool-call arguments arrive as dicts in Ollama's format but pass
    through the same defensive parsing as every adapter; missing content
    and counters are tolerated.
    """
    message = data.get("message") or {}
    spell_calls = [
        SpellCall(
            spell=(call.get("function") or {}).get("name", ""),
            arguments=parse_arguments((call.get("function") or {}).get("arguments")),
        )
        for call in message.get("tool_calls") or []
    ]
    usage = {
        label: data[key]
        for key, label in (
            ("prompt_eval_count", "prompt_tokens"),
            ("eval_count", "completion_tokens"),
        )
        if data.get(key) is not None
    }
    return OracleResponse(
        text=message.get("content") or "", spell_calls=spell_calls, usage=usage
    )


class OllamaOracle(Oracle):
    """The voice of a model served by a local Ollama daemon.

    `arcana` is the Ollama model name (e.g. ``"qwen2.5:7b"``); `host` the
    daemon's base URL. `keep_alive` keeps the model in memory between
    requests (e.g. ``"10m"``, ``-1`` for forever); `options` passes Ollama
    runtime options such as ``{"temperature": 0.2, "num_ctx": 8192}``.
    `transport` injects an httpx transport — used by the unit tests to
    replay recorded responses.
    """

    def __init__(
        self,
        arcana: str = "llama3.2",
        host: str = "http://127.0.0.1:11434",
        timeout: float = 120.0,
        keep_alive: str | int | None = None,
        options: Mapping[str, Any] | None = None,
        transport: Any | None = None,
    ) -> None:
        require_httpx("ollama")  # fail at construction, with guidance
        self.arcana = arcana
        self._host = host.rstrip("/")
        self._timeout = timeout
        self._keep_alive = keep_alive
        self._options = dict(options) if options else None
        self._transport = transport

    def _client(self) -> Any:
        httpx = require_httpx("ollama")
        return httpx.AsyncClient(
            base_url=self._host, timeout=self._timeout, transport=self._transport
        )

    def _payload(
        self,
        messages: Sequence[Mapping[str, Any]],
        spells: Sequence[Mapping[str, Any]] | None,
        stream: bool,
    ) -> dict[str, Any]:
        return build_payload(
            self.arcana,
            messages,
            spells,
            stream=stream,
            keep_alive=self._keep_alive,
            options=self._options,
        )

    async def generate(
        self,
        messages: Sequence[Mapping[str, Any]],
        spells: Sequence[Mapping[str, Any]] | None = None,
    ) -> OracleResponse:
        """Ask /api/chat for a complete answer (non-streaming).

        Raises:
            OracleConnectionError: The daemon is unreachable.
            OracleTimeoutError: No answer within `timeout`.
            OracleResponseError: The daemon answered with an error status.
        """
        try:
            async with self._client() as client:
                response = await client.post(
                    "/api/chat", json=self._payload(messages, spells, stream=False)
                )
        except Exception as exc:
            mapped = map_transport_error(
                exc, base_url=self._host, timeout=self._timeout
            )
            if mapped is not None:
                raise mapped from exc
            raise
        raise_for_status(
            response.status_code,
            response.text,
            base_url=self._host,
            arcana=self.arcana,
        )
        return parse_chat_response(response.json())

    async def stream_generate(
        self,
        messages: Sequence[Mapping[str, Any]],
        spells: Sequence[Mapping[str, Any]] | None = None,
    ) -> AsyncIterator[str]:
        """Yield content chunks from /api/chat's NDJSON stream.

        Raises the same OracleError subclasses as ``generate``; errors
        surface on the first iteration.
        """
        try:
            async with self._client() as client, client.stream(
                "POST", "/api/chat", json=self._payload(messages, spells, stream=True)
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode(
                        "utf-8", errors="replace"
                    )
                    raise_for_status(
                        response.status_code,
                        body,
                        base_url=self._host,
                        arcana=self.arcana,
                    )
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except ValueError:
                        continue  # a garbled line must not kill the stream
                    content = (chunk.get("message") or {}).get("content", "")
                    if content:
                        yield content
                    if chunk.get("done"):
                        break
        except Exception as exc:
            mapped = map_transport_error(
                exc, base_url=self._host, timeout=self._timeout
            )
            if mapped is not None:
                raise mapped from exc
            raise
