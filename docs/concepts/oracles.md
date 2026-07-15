# Oracles

*The Oracle is the voice consulted during the invocation; the Arcana
names which voice.*

Technically: `Oracle` is the abstract LLM interface — `arcana` identifies
the model, `generate(messages, spells)` returns an `OracleResponse`
(text, `spell_calls`, usage counters), and `stream_generate(...)` yields
text chunks. Everything is local-first; no proprietary API is assumed
anywhere.

| Adapter | Extra | Speaks to |
|---|---|---|
| `ScriptedOracle` | — | A fixed script — deterministic, for tests (the suite never touches real models) |
| `OpenAICompatibleOracle` | `[openai-compat]` | Any `/v1/chat/completions` server: Ollama `/v1`, llama-server, vLLM, LM Studio |
| `OllamaOracle` | `[ollama]` | Ollama's native `/api/chat`: native tools, `keep_alive`, `options` |
| `LlamaCppOracle` | `[llamacpp]` | A local GGUF, in-process — the serverless option |
| `TransformersOracle` | `[transformers]` | Hugging Face pipelines, in-process |

```python
from sanctum.oracle.openai_compat import OpenAICompatibleOracle

oracle = OpenAICompatibleOracle(
    arcana="qwen2.5:7b",
    base_url="http://127.0.0.1:11434/v1",
    extra_body={"temperature": 0.2},
)
```

Failures are actionable by design: connection refused, timeout, and
unknown-model responses raise `OracleConnectionError`,
`OracleTimeoutError`, and `OracleResponseError` respectively, each naming
the endpoint and the likely fix (`ollama serve`, raise `timeout=`,
`ollama pull <arcana>`).

Tool-call parsing is deliberately defensive about small local models —
arguments as dicts, JSON strings, or malformed JSON all survive; see
[Robust tool-calling](../guides/robust-tool-calling.md).
