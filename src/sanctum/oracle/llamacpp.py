"""An Oracle that carries the model within itself — no server at all.

In-process GGUF inference via llama-cpp-python (optional extra
``pip install sanctum-engine[llamacpp]``; the package builds llama.cpp,
so a C compiler or a prebuilt wheel is needed). This is the **serverless
option**: no daemon to start, no port to configure — the model file is
loaded into the current process on first use. Trade-offs: model load time
is paid inside your process, memory is shared with your app, and requests
serialize on one model instance.

Tool-calling: `tools` are forwarded to ``create_chat_completion``, which
uses llama.cpp's grammar/JSON-schema-constrained generation for chat
formats that support it (e.g. ``chatml-function-calling``, functionary
models — pass `chat_format` accordingly). With formats lacking tool
support, models may answer in plain text instead of calling tools;
responses are parsed defensively either way, reusing the OpenAI-shaped
parser (llama-cpp-python mimics that response format).

Importing this module never fails; the dependency is required at
construction time. Validated manually, never by the automated suite
(tests never load real models).
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from sanctum.oracle.core import Oracle, OracleResponse
from sanctum.oracle.openai_compat import parse_chat_completion


def _require_llama() -> Any:
    """Import llama_cpp lazily, with install guidance on failure."""
    try:
        from llama_cpp import Llama
    except ImportError as exc:
        raise ImportError(
            "LlamaCppOracle requires the optional dependency "
            "'llama-cpp-python'; install it with: "
            "pip install sanctum-engine[llamacpp] "
            "(builds llama.cpp — needs a C compiler or a prebuilt wheel)."
        ) from exc
    return Llama


class LlamaCppOracle(Oracle):
    """The voice bound into the process itself, read from a local GGUF.

    `model_path` points at a GGUF file on disk; `arcana` defaults to the
    file's stem. `n_ctx` sets the context window, `chat_format` selects
    llama-cpp-python's chat template (pick a tool-capable one for Spell
    calling); remaining keyword arguments go to ``llama_cpp.Llama``
    verbatim (e.g. ``n_gpu_layers=-1``). The model loads lazily on first
    use, in a worker thread, so constructing the Oracle is cheap.
    """

    def __init__(
        self,
        model_path: str | Path,
        arcana: str | None = None,
        n_ctx: int = 4096,
        chat_format: str | None = None,
        verbose: bool = False,
        **llama_kwargs: Any,
    ) -> None:
        _require_llama()  # fail at construction, with guidance
        path = Path(model_path)
        if not path.is_file():
            raise FileNotFoundError(
                f"No GGUF model file at {path}. Download one first — e.g. "
                "search Hugging Face for '<model name> GGUF' and pick a "
                "quantization that fits your RAM."
            )
        self.arcana = arcana or path.stem
        self._model_path = str(path)
        self._n_ctx = n_ctx
        self._chat_format = chat_format
        self._verbose = verbose
        self._llama_kwargs = llama_kwargs
        self._llama: Any = None
        self._load_lock = threading.Lock()

    def _ensure_model(self) -> Any:
        """Load the GGUF on first use (thread-safe, called off-loop)."""
        with self._load_lock:
            if self._llama is None:
                Llama = _require_llama()
                self._llama = Llama(
                    model_path=self._model_path,
                    n_ctx=self._n_ctx,
                    chat_format=self._chat_format,
                    verbose=self._verbose,
                    **self._llama_kwargs,
                )
        return self._llama

    def _chat(
        self,
        messages: Sequence[Mapping[str, Any]],
        spells: Sequence[Mapping[str, Any]] | None,
        stream: bool,
    ) -> Any:
        """Run create_chat_completion (blocking; call from a thread)."""
        llama = self._ensure_model()
        kwargs: dict[str, Any] = {
            "messages": [dict(message) for message in messages],
            "stream": stream,
        }
        if spells:
            kwargs["tools"] = [
                {"type": "function", "function": dict(schema)} for schema in spells
            ]
            kwargs["tool_choice"] = "auto"
        return llama.create_chat_completion(**kwargs)

    async def generate(
        self,
        messages: Sequence[Mapping[str, Any]],
        spells: Sequence[Mapping[str, Any]] | None = None,
    ) -> OracleResponse:
        """Run inference in a worker thread and parse the full answer."""
        result = await asyncio.to_thread(self._chat, messages, spells, False)
        return parse_chat_completion(result)

    async def stream_generate(
        self,
        messages: Sequence[Mapping[str, Any]],
        spells: Sequence[Mapping[str, Any]] | None = None,
    ) -> AsyncIterator[str]:
        """Yield content chunks from the in-process stream.

        A worker thread drives llama.cpp's blocking chunk generator and
        forwards deltas to the event loop through a queue.
        """
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def produce() -> None:
            try:
                for chunk in self._chat(messages, spells, True):
                    delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        loop.call_soon_threadsafe(queue.put_nowait, content)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        threading.Thread(target=produce, daemon=True).start()
        while (chunk := await queue.get()) is not None:
            yield chunk
