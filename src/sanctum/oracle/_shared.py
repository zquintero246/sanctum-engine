"""Shared plumbing for the HTTP-backed Oracle adapters (private module).

Lazy httpx access, transport-error mapping with actionable messages, HTTP
status handling, and defensive parsing of tool-call arguments. The known
failure modes of local 7-14B models — malformed argument JSON, arguments
as dicts vs strings, empty content alongside tool calls — are normalized
here once, so every adapter behaves identically.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from sanctum.oracle.errors import (
    OracleConnectionError,
    OracleResponseError,
    OracleTimeoutError,
)


def require_httpx(extra: str) -> Any:
    """Import httpx lazily, pointing at the right extra on failure."""
    try:
        import httpx
    except ImportError as exc:
        raise ImportError(
            "This Oracle requires the optional dependency 'httpx'; install "
            f"it with: pip install sanctum-engine[{extra}]"
        ) from exc
    return httpx


def map_transport_error(
    exc: Exception, *, base_url: str, timeout: float
) -> Exception | None:
    """Translate an httpx transport failure into an actionable OracleError.

    Returns None for exceptions this helper does not recognize; the caller
    re-raises the original.
    """
    import httpx

    if isinstance(exc, httpx.ConnectError):
        return OracleConnectionError(
            f"Cannot reach {base_url} (connection refused). Is the model "
            "server running there? Start it (e.g. `ollama serve`, "
            "`llama-server`, `vllm serve ...`) or point base_url/host at "
            "the right address."
        )
    if isinstance(exc, httpx.TimeoutException):
        return OracleTimeoutError(
            f"No answer from {base_url} within {timeout}s. Local models can "
            "take long on the first request while weights load; raise "
            "`timeout=`, warm the model up, or pick a smaller model."
        )
    if isinstance(exc, httpx.HTTPError):
        return OracleResponseError(
            f"Transport error talking to {base_url}: {exc}"
        )
    return None


def raise_for_status(
    status_code: int, body: str, *, base_url: str, arcana: str
) -> None:
    """Turn an HTTP error status into an actionable OracleResponseError."""
    if status_code < 400:
        return
    hint = ""
    if status_code == 404:
        hint = (
            f" If the model is missing, pull or load it first (e.g. "
            f"`ollama pull {arcana}`); if the path is wrong, check that "
            "base_url includes the expected prefix (Ollama's OpenAI API "
            "lives under /v1)."
        )
    raise OracleResponseError(
        f"The server at {base_url} rejected the request for model "
        f"'{arcana}' (HTTP {status_code}): {body[:300]}.{hint}"
    )


def parse_arguments(raw: Any) -> dict[str, Any]:
    """Decode tool-call arguments defensively.

    Local models emit arguments as a dict (Ollama native), a JSON string
    (OpenAI format), or — not rarely, with 7-14B models — malformed JSON.
    The malformed case is preserved under ``"__malformed_json__"`` instead
    of raising: the Spell then fails with a readable message that flows
    back to the model as transcript feedback, and the engine keeps
    running.
    """
    if raw is None:
        return {}
    if isinstance(raw, Mapping):
        return dict(raw)
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return {"__malformed_json__": raw}
    if isinstance(decoded, dict):
        return decoded
    return {"__malformed_json__": raw}
