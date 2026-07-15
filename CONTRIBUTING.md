# Contributing to Sanctum

The design rationale, execution model, trade-offs, and the full glossary
live in [`docs/architecture.md`](docs/architecture.md) — read it before
changing the core.

## Engineering principles

1. **Zero-dependency core**: the engine is Python stdlib only; extras
   (HTTP, Postgres, in-process inference, docs) are optional modules with
   lazy imports.
2. **Local-first**: never assume a proprietary LLM API in the core.
3. Everything public is **typed** and documented with dual docstrings
   (metaphor first line, precise technical explanation below).
4. **Every feature ships with tests**; tests script LLM behavior with
   `ScriptedOracle` and never touch real models or live services.
5. The **public API stays small and stable** (see Versioning below).
6. **Async-first**: the engine is native asyncio; synchronous entry
   points are thin wrappers.
7. Spells load from directory trees by convention
   (`Tome.load_from_directory`), keeping the tool library decoupled.

## Setup

```sh
python -m venv .venv
.venv/Scripts/activate          # Windows; use source .venv/bin/activate elsewhere
pip install -e ".[dev]"
```

## Running the tests

```sh
pytest                          # unit suite — always green, no services needed
pytest --cov=sanctum            # with core coverage
python benchmarks/superstep_overhead.py
```

Unit tests never touch real models or servers: LLM behavior is scripted
with `ScriptedOracle`, and the HTTP Oracle adapters are tested by
replaying recorded responses (in `tests/fixtures/`) through
`httpx.MockTransport`.

## Integration tests (opt-in)

The suite includes smoke tests against **live local model servers**,
marked `@pytest.mark.integration` and skipped unless the matching
environment variable is set:

- `SANCTUM_TEST_OPENAI_COMPAT_URL` — exercises `OpenAICompatibleOracle`
  and the robust tool-calling loop end-to-end against **any** server
  exposing `/v1/chat/completions` (llama.cpp's `llama-server`, Ollama's
  `/v1`, vLLM, LM Studio). Set it to the exact base URL, version prefix
  included.
- `SANCTUM_TEST_OLLAMA_URL` — exercises the native `OllamaOracle`
  (`/api/chat`) against an Ollama daemon. Base URL without `/v1`.

With llama.cpp's `llama-server` (any small instruct GGUF works):

```sh
llama-server -m qwen2.5-0.5b-instruct-q4_k_m.gguf --port 8080 -c 4096 --jinja

# bash
SANCTUM_TEST_OPENAI_COMPAT_URL=http://127.0.0.1:8080/v1 pytest -m integration

# PowerShell
$env:SANCTUM_TEST_OPENAI_COMPAT_URL = "http://127.0.0.1:8080/v1"
pytest -m integration
```

With Ollama (`ollama serve` + `ollama pull qwen2.5:0.5b`), both adapters
can run in one pass:

```sh
SANCTUM_TEST_OLLAMA_URL=http://127.0.0.1:11434 \
SANCTUM_TEST_OPENAI_COMPAT_URL=http://127.0.0.1:11434/v1 \
pytest -m integration
```

Model overrides: `SANCTUM_TEST_OLLAMA_MODEL` and
`SANCTUM_TEST_OPENAI_COMPAT_MODEL` (both default `qwen2.5:0.5b`;
`llama-server` ignores the name and serves whatever model it loaded).
These tests assert transport, parsing, and loop survival against a real
server — never model quality — so any chat-capable model works.

## Style

- `ruff check .` must pass (config in `pyproject.toml`; black-compatible
  formatting, line length 88). CI runs it on every push and PR.
- Code and docstrings in English. The metaphor appears in names and in
  the first line of each docstring, followed by the precise technical
  explanation — never instead of it.
- Tone of the metaphor: classical occultism and alchemy — mystery and
  precision. Avoid jokey copy, RPG/gamer aesthetics, pop-fantasy
  references, and cartoonish names. Documentation is technically precise
  first; the metaphor is identity, never a substitute for clarity.
- Error messages must be actionable: name the endpoint/file involved and
  state the most likely fix.

### The two-layer naming policy

Domain concepts use the glossary vocabulary (Ritual, Sigil, Aether,
Conduit, Seal, Codex, Omen, Oracle, Spell, Tome, Ward, summon — full
glossary with technical equivalences in
[`docs/architecture.md`](docs/architecture.md) §8). Universal infrastructure stays
technical and is never themed: `compile`, `invoke`, `ainvoke`, `astream`,
`add_edge`, `add_conditional_edge`, `reducer`, `recursion_limit`,
`interrupt`, START, END, superstep. Exceptions combine a domain name with
a technical suffix (`RitualValidationError`, `SigilTimeoutError`,
`SpellCallParseError`, ...). Don't invent new glossary terms or mystical
synonyms for technical ones.

## Commit convention

Conventional Commits: `<type>(<scope>): <imperative summary>` where type
is one of `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `chore` and
scope is the subsystem (`ritual`, `aether`, `codex`, `omens`, `oracle`,
`grimoire`, `wards`, `ci`). Examples:

```
feat(oracle): add OpenAI-compatible adapter with SSE streaming
fix(ritual): count fallback supersteps toward recursion_limit
docs(architecture): document fan-in trade-offs
```

Breaking changes add a `!` (`feat(ritual)!: ...`) and a `BREAKING CHANGE:`
footer explaining the migration.

## Versioning (SemVer)

The **public API** is the contract (engineering principle 5):
`Ritual`, `Rite`, `add_sigil`, `add_edge`, `add_conditional_edge`,
`compile`, `invoke`/`ainvoke`, `astream`, `Codex` (and the `Seal` shape),
`Tome`, `Oracle` (and `OracleResponse`/`SpellCall`), `summon` — plus the
documented Omen types, `SigilPolicy`, `Ward` hooks, and the exception
hierarchy exported from `sanctum`.

A **breaking change** is anything that makes existing correct code fail
or change meaning: removing/renaming those names, changing signatures or
return shapes, changing documented semantics (delta merge order, Seal
format, stream mode contents), or raising different exception types.

While the project is pre-1.0: breaking changes bump the **minor** version
(0.2.0 → 0.3.0) and are listed under a "Changed"/"Removed" heading in
CHANGELOG.md with migration notes; everything else bumps the patch. From
1.0.0 on, standard SemVer applies (breaking = major).

## Releasing

1. Update `CHANGELOG.md` (move Unreleased to the new version) and the
   version in `pyproject.toml` + `sanctum/__init__.py`.
2. Tag: `git tag vX.Y.Z && git push --tags`.
3. `release.yml` builds with `python -m build` and publishes to PyPI via
   **trusted publishing** — the one-time PyPI/GitHub setup is documented
   at the top of `.github/workflows/release.yml`.

## Scope guardrails

Sanctum competes in the local-first niche, not on feature parity with
larger frameworks. Priorities: reliability with local 7-14B models
(including their tool-calling failure modes), developer experience, and
observability without external services. Don't add advanced graph
features without a concrete use case that demands them. Use-case code
belongs in `examples/`, never in the core or the main docs.
