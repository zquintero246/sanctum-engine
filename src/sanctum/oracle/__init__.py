"""Oracle — the voice consulted during the invocation.

Abstract LLM interface. An Oracle answers prompts on behalf of invoked
entities; the Arcana identifies the underlying model. All adapters are
local-first — no proprietary APIs assumed. Implementations:

- ScriptedOracle (here): deterministic, for tests.
- OpenAICompatibleOracle (`sanctum.oracle.openai_compat`, extra
  ``[openai-compat]``): the primary adapter — any /v1/chat/completions
  server (Ollama /v1, llama-server, vLLM, LM Studio).
- OllamaOracle (`sanctum.oracle.ollama`, extra ``[ollama]``): native
  /api/chat with keep_alive and runtime options.
- LlamaCppOracle (`sanctum.oracle.llamacpp`, extra ``[llamacpp]``):
  in-process GGUF inference, the serverless option.
- TransformersOracle (`sanctum.oracle.transformers`, extra
  ``[transformers]``): in-process via Hugging Face pipelines.

The optional adapters are not imported here (dependencies stay lazy);
import their modules explicitly. Their failures raise the OracleError
family exported below, with actionable messages.
"""

from sanctum.oracle.core import Message, Oracle, OracleResponse, SpellCall
from sanctum.oracle.errors import (
    OracleConnectionError,
    OracleError,
    OracleResponseError,
    OracleTimeoutError,
)
from sanctum.oracle.robust import PromptedSpellCalling
from sanctum.oracle.scripted import ScriptedOracle

__all__ = [
    "Message",
    "Oracle",
    "OracleConnectionError",
    "OracleError",
    "OracleResponse",
    "OracleResponseError",
    "OracleTimeoutError",
    "PromptedSpellCalling",
    "ScriptedOracle",
    "SpellCall",
]
