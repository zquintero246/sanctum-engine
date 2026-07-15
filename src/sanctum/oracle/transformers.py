"""An Oracle that runs the model inside the process, via transformers.

Optional module: requires the ``transformers`` library (declared as the
``transformers`` extra — ``pip install sanctum-engine[transformers]``,
plus a backend such as torch). The import is lazy: importing this module
never fails; the dependency is only loaded when the pipeline is first
used, raising ImportError with install instructions if missing.

Limitations: this adapter drives a plain ``text-generation`` pipeline, so
it has no native Spell-calling — `spell_calls` is always empty — and
``stream_generate`` yields the completed text in a single chunk. No
automated integration tests exercise this module (tests never touch real
models).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from sanctum.oracle.core import Oracle, OracleResponse


class TransformersOracle(Oracle):
    """The voice of a model loaded in-process with transformers.

    `arcana` is the Hugging Face model id; extra keyword arguments are
    forwarded to ``transformers.pipeline``. The pipeline is built lazily
    on first use and blocking inference runs in a worker thread.
    """

    def __init__(
        self,
        arcana: str = "Qwen/Qwen2.5-0.5B-Instruct",
        max_new_tokens: int = 256,
        **pipeline_kwargs: Any,
    ) -> None:
        self.arcana = arcana
        self._max_new_tokens = max_new_tokens
        self._pipeline_kwargs = pipeline_kwargs
        self._pipeline: Any = None

    def _ensure_pipeline(self) -> Any:
        """Build the text-generation pipeline on first use (lazy import)."""
        if self._pipeline is None:
            try:
                from transformers import pipeline
            except ImportError as exc:
                raise ImportError(
                    "TransformersOracle requires the optional dependency "
                    "'transformers'; install it with: "
                    "pip install sanctum-engine[transformers]"
                ) from exc
            self._pipeline = pipeline(
                "text-generation", model=self.arcana, **self._pipeline_kwargs
            )
        return self._pipeline

    async def generate(
        self,
        messages: Sequence[Mapping[str, Any]],
        spells: Sequence[Mapping[str, Any]] | None = None,
    ) -> OracleResponse:
        """Run the pipeline over the transcript in a worker thread.

        `spells` is accepted for interface compatibility but ignored — see
        the module docstring.
        """
        pipe = await asyncio.to_thread(self._ensure_pipeline)
        outputs = await asyncio.to_thread(
            pipe,
            [dict(message) for message in messages],
            max_new_tokens=self._max_new_tokens,
            return_full_text=False,
        )
        text = outputs[0]["generated_text"]
        if isinstance(text, list):  # chat pipelines return a message list
            text = text[-1].get("content", "")
        return OracleResponse(text=str(text), spell_calls=[], usage={})

    async def stream_generate(
        self,
        messages: Sequence[Mapping[str, Any]],
        spells: Sequence[Mapping[str, Any]] | None = None,
    ) -> AsyncIterator[str]:
        """Yield the completed text as one chunk (see module limitations)."""
        response = await self.generate(messages, spells)
        yield response.text
