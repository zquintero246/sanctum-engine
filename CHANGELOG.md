# Changelog

All notable changes to `sanctum-engine` are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project adheres to [Semantic Versioning](https://semver.org/) (see
CONTRIBUTING.md for what counts as a breaking change pre-1.0).

## [0.2.0] — 2026-07-14

### Added
- Production Oracle adapters, all optional (the core stays stdlib-only):
  - `OpenAICompatibleOracle` (`[openai-compat]` extra): any
    `/v1/chat/completions` server — Ollama `/v1`, llama-server, vLLM,
    LM Studio — with OpenAI-format tools and SSE streaming.
  - `LlamaCppOracle` (`[llamacpp]` extra): in-process GGUF inference, the
    serverless option; grammar-backed tool calling where the chat format
    supports it.
  - `OracleError` family (`OracleConnectionError`, `OracleTimeoutError`,
    `OracleResponseError`) with actionable messages.
- Robust spell-calling for local 7-14B models:
  - `PromptedSpellCalling` wrapper (schemas in the system prompt, calls
    parsed from delimited blocks) with `"auto"` fallback when the
    endpoint rejects tools.
  - Repair layer applied to every spell call: tolerant JSON extraction
    (fenced blocks, unbalanced braces, single quotes), correction
    messages back to the Oracle for unknown Spells / invalid arguments,
    bounded by `max_repair_rounds` before `SpellCallParseError`.
  - `SpellCallRepaired` / `SpellCallRejected` Omens.
- Resilience policies: `SigilPolicy` (per-attempt timeout, retries with
  exponential backoff and jitter, selective `retry_on`, `on_error`
  fallback Sigil), `SigilTimeoutError`, `SigilRetried` Omen, and the
  reserved `__errors__` Conduit.
- Wards middleware: `Ward` hooks (`before_sigil`, `after_sigil`,
  `on_omen`, `on_compile`), `WardRejection` + `DeltaRejected` Omen, and
  built-ins `AuditWard` (JSONL trail), `UsageWard` (token/call tally),
  `RedactWard` (pattern masking before Seals and logs).
- Local-first tracing: `TraceRecorder` (full `.sanctum-trace.json` per
  Invocation), `render_trace()` self-contained HTML viewer, and the
  `python -m sanctum.trace render` CLI; tracing overhead case added to
  the benchmark.
- Two-level test strategy: unit tests replay recorded fixtures through
  `httpx.MockTransport`; opt-in integration tests against a live Ollama
  (`SANCTUM_TEST_OLLAMA_URL`, `pytest -m integration`).
- Packaging: extras `openai-compat`, `ollama`, `llamacpp`, `all`;
  CONTRIBUTING.md; MIT LICENSE; CI and trusted-publishing release
  workflows.

### Changed
- `OllamaOracle` rewritten on the native `/api/chat` endpoint via httpx
  (`[ollama]` extra; previously stdlib urllib): native tool calling,
  `keep_alive`, and `options` (temperature, num_ctx, ...).
- `summon()` gained `spell_calling` ("native" / "prompted" / "auto"),
  `max_repair_rounds`, and `wards`; Oracle `usage` counters are attached
  to assistant messages.
- The `all` extra excludes `llama-cpp-python` (needs a C toolchain);
  install `[llamacpp]` explicitly for the in-process backend.

## [0.1.0] — 2026-07-14

### Added
- Cyclic state-graph engine: `Ritual` builder and `Rite` executable plan,
  compile-time validation, static fan-out edges, conditional edges with
  `path_map`, cycles bounded by `recursion_limit`.
- BSP superstep scheduler: concurrent frontier execution
  (`asyncio.TaskGroup`), deterministic delta merging in Sigil insertion
  order, fan-in "any" semantics, `SigilExecutionError` with sibling
  cancellation.
- State system: `AetherSchema` / `Conduit` with reducers (`overwrite`,
  `append`, `add`, `merge_dict`, custom), `Annotated` sugar, runtime
  schema validation naming the offending Sigil.
- Persistence: `Seal` checkpoints per superstep, `Codex` stores
  (`MemoryCodex`, `SqliteCodex`, optional `PostgresCodex`), resumption,
  `interrupt()` human-in-the-loop, and time-travel from any Seal.
- Streaming: `astream` with combinable modes (`updates`, `values`,
  `omens`, `tokens`), typed timestamped Omens, Sigil `writer` injection
  for live tokens, Flask/SSE example.
- LLM layer: abstract `Oracle` + deterministic `ScriptedOracle`;
  Grimoire: `Spell` / `@spell` (schema from type hints), `Tome` with the
  AgentGrimoire directory convention; `summon()` ReAct loop built on the
  public API.
- Docs (`README`, `docs/architecture.md`), superstep-overhead benchmark,
  98% core test coverage.
