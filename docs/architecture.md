# Sanctum — Architecture and Design Rationale

Formal design document for the Sanctum orchestration engine
(`sanctum-engine`). This is thesis-grade material: every claim below is
implemented and tested in the repository. Terminology follows the official
glossary (§8); the ceremonial metaphor names the concepts, the semantics
are always stated technically.

## 1. Purpose and scope

Sanctum is a minimal, local-first orchestration engine for AI agents. It
executes **cyclic state graphs** — explicitly *not* DAGs — under a
superstep model derived from Pregel/BSP. The design goals, in priority
order:

1. **Auditability**: a core small enough to read whole, with zero
   external dependencies (Python stdlib only).
2. **Determinism**: identical inputs produce identical state trajectories,
   including under intra-superstep parallelism.
3. **Local-first**: no proprietary LLM APIs assumed anywhere in the core;
   model access is abstracted behind the `Oracle` interface.
4. **Sufficient primitives**: agent patterns (ReAct, human-in-the-loop,
   time-travel) must be constructible from the public API alone — `summon`
   is implemented that way as an existence proof.

## 2. Execution model: BSP/Pregel supersteps

The unit of progress is the **superstep**. Given a compiled graph (a
`Rite`), the scheduler maintains a *frontier* — the set of active Sigils
(nodes) — and iterates:

1. **Execute** every frontier Sigil concurrently (`asyncio.TaskGroup`).
   Each receives its own shallow copy of the pre-superstep Aether: within
   a superstep, no Sigil observes a sibling's writes (BSP isolation).
2. **Collect** each Sigil's partial delta (a mapping of state keys).
3. **Merge** deltas into the Aether through each Conduit's reducer, in
   **Sigil insertion order** (the order Sigils were bound to the Ritual).
4. **Evaluate edges** of the executed Sigils against the *post-merge*
   Aether: static edges contribute all their targets (fan-out); a
   conditional edge contributes its router's chosen target. The union is
   the next frontier (a set — duplicates coalesce).
5. **Persist**: when a Codex is attached, write a Seal (full Aether, next
   frontier, superstep number).
6. **Terminate** when the frontier is empty or contains only END;
   otherwise loop. A superstep counter bounds the Invocation: exceeding
   `recursion_limit` (default 25) raises `RecursionLimitError`.

Cycles are the point: a conditional edge routing back to an earlier Sigil
is the mechanism behind agentic loops (think → act → observe → …). The
reachability validator in `compile()` is cycle-safe (BFS with a visited
set) and treats a conditional edge without a `path_map` as potentially
reaching every Sigil.

Differences from Pregel proper: Sanctum has no message passing between
vertices (all communication flows through the shared Aether), no vertex
halting votes (termination is frontier-emptiness), and the graph is small
and static per compilation rather than partitioned across workers.

## 3. State model: Aether, Conduits, reducers

The Aether is a flat `dict[str, Any]`. An `AetherSchema` maps each key to
a **Conduit** carrying a reducer `(current, update) -> new`. Built-in
reducers: `overwrite` (default), `append`, `add`, `merge_dict`; any
callable with the same signature works.

Rules, in order of application per delta key:

- Keys not declared in the schema raise `AetherValidationError`, naming
  the offending Sigil (or the initial input).
- If the key is **absent** from the Aether, the delta value is assigned
  directly and the reducer is *not* called. Consequence: custom reducers
  never need to handle a missing `current` (e.g. `max` works unmodified).
- Otherwise the reducer folds the update into the current value.

Without a schema, deltas merge by plain `dict.update` and keys are
unvalidated — a deliberate low-friction mode for prototypes and tests.

## 4. Design decisions and trade-offs

### 4.1 Fan-in: "any" semantics

A Sigil executes as soon as **any** predecessor activates it; multiple
activations within one superstep coalesce into a single execution (the
frontier is a set). Trade-off: an "all predecessors" join (barrier
fan-in) cannot yet be expressed — a Sigil downstream of an unbalanced
fan-out may run before its slower ancestor's branch completes, and run
again later. "Wait-for-all" joins are planned future work; "any" was
chosen first because it is the simpler semantics to reason about, it
never deadlocks, and the BSP structure already provides a per-superstep
barrier that covers the common balanced fan-out/fan-in case (equal-length
branches converge in the same superstep, verified by test).

### 4.2 Deterministic reducer order

Within a superstep, deltas are applied in Sigil **insertion order**, not
completion order. Trade-off: the engine buffers all deltas until the
superstep barrier instead of folding them as they arrive; in exchange,
concurrent writes to the same Conduit resolve identically on every run —
a reproducibility property worth far more than the negligible buffering
cost at this scale. (The event stream is the counterpart: `SigilCompleted`
Omens are emitted at *real* completion time, so observability remains
truthful while state remains deterministic.)

### 4.3 BSP isolation via shallow copies

Each Sigil receives `dict(aether)` — a shallow copy. Mutating the mapping
itself has no effect; only the returned delta changes state. Trade-off:
shallow copying is O(keys) and cheap, but **nested mutable values are
shared** — a Sigil that mutates `aether["messages"].append(...)` in place
bypasses the reducer discipline. Deep-copying every superstep was
rejected on cost and on the principle that deltas-through-reducers is the
contract; the limitation is documented (§5).

### 4.4 Seals and JSON serialization

A Seal stores: the full post-superstep Aether, the **next** frontier
(precisely what resumption must execute), the 1-based superstep number, a
timestamp, metadata, and a unique `seal_id`. Histories are append-only;
`get` returns the most recently *written* Seal, so a time-travel replay
(which re-appends supersteps 3, 4, 5 after 1–5) leaves an honest audit
trail rather than rewriting history.

SQLite and Postgres Codices serialize the Aether/frontier/metadata as
JSON. Trade-off: arbitrary Python objects cannot be checkpointed
(`SealError` at `put` time, with guidance) — accepted because JSON keeps
Seals portable, inspectable with any tooling, and diffable, which matters
more for an auditable engine than checkpointing rich objects (pickle was
rejected: opaque and a deserialization attack surface).

### 4.5 Interrupt semantics

`interrupt()` raises the `Interrupt` control-flow signal from inside a
Sigil. The engine aborts the current superstep — sibling tasks are
cancelled, all deltas discarded — writes a Seal whose frontier is the
*aborted* superstep's, and re-raises to the caller. On resumption the
whole interrupted frontier re-executes. Consequences: (a) interrupting
Sigils must consult the Aether to decide whether the awaited data has
arrived (the injected `updates` make it available), and (b) Sigils that
share a superstep with a potential interrupt should be idempotent, since
they may run twice. The alternative — committing sibling deltas before
pausing — was rejected because it would make the interrupted superstep
half-applied, breaking the invariant that a Seal always describes a
consistent superstep boundary.

### 4.6 Failure semantics

If a Sigil raises, `asyncio.TaskGroup` cancels its superstep siblings,
the superstep's deltas are discarded, and the failure surfaces as
`SigilExecutionError` carrying the Sigil's name, an Aether snapshot, and
the original exception as `__cause__`. When several Sigils fail
concurrently, the earliest by insertion order wins (determinism again);
failures take precedence over interrupts in the same superstep. In the
`summon` ReAct loop, *Spell* failures are deliberately not engine
failures: they are caught as `SpellExecutionError` and injected into the
transcript as error messages, so the Oracle can react — the loop degrades
conversationally instead of crashing.

### 4.7 Always-emit event stream

The scheduler emits every lifecycle Omen unconditionally through an
`emit` callback that defaults to a no-op; `astream` attaches a
queue-backed emitter and filters by mode. Trade-off: a handful of no-op
awaits per superstep on the non-streaming path (measured: within noise,
§6) in exchange for a single, always-consistent instrumentation path —
no divergence between "streamed" and "plain" execution.

### 4.8 Two-layer naming policy

Domain concepts carry the ceremonial vocabulary (Ritual, Sigil, Aether,
Seal, Omen, Spell, …); universal infrastructure stays technical
(`compile`, `invoke`, `astream`, `add_edge`, `reducer`,
`recursion_limit`, START, END, superstep). Rationale: the metaphor is
identity and mnemonics, but renaming well-known technical terms would tax
every new reader; the glossary (§8) is the contract between both layers.

## 5. Known limitations

- **No "wait-for-all" fan-in** (§4.1): unbalanced convergent branches
  re-execute the join Sigil per activation wave.
- **Shallow-copy isolation** (§4.3): in-place mutation of nested values
  leaks across the superstep barrier; the reducer contract is not
  enforceable against it.
- **JSON-only persistence** (§4.4) for SQLite/Postgres Codices.
- **`recursion_limit` counts the whole Invocation**, including resumed
  and time-traveled supersteps — long-lived sessions must raise it.
- **Seal writes are on the hot path**: one awaited `put` per superstep;
  a slow Codex slows the ritual (no write-behind buffering yet).
- **Oracle token streaming is not yet wired into `summon`** — the
  `writer` mechanism exists and is tested, but the packaged ReAct loop
  uses `generate()`, not `stream_generate()`.
- **Single-process scheduler**: parallelism is `asyncio` concurrency, not
  multi-process; CPU-bound Sigils should offload
  (`asyncio.to_thread`).
- **Circles (subgraphs) are not implemented** (deferred by design).
- The optional adapters (`OllamaOracle`, `TransformersOracle`,
  `PostgresCodex`) are validated manually, never by the test suite (tests
  use `ScriptedOracle` exclusively) — they are excluded from core
  coverage accounting.

## 6. Performance

`benchmarks/superstep_overhead.py` measures pure engine overhead with
no-op Sigils (best of 3, CPython 3.13, Windows 11, consumer laptop —
indicative figures):

| scenario | supersteps | µs/superstep |
|---|---:|---:|
| sequential (bare) | 1000 | ~46 |
| sequential + AetherSchema reducers | 1000 | ~49 |
| sequential + MemoryCodex Seals | 1000 | ~63 |
| parallel ×8 (spread/work/gate) | 600 | ~61 |

Local LLM inference latency is typically 10⁴–10⁶ µs per call; the
orchestrator therefore contributes well under 0.1 % of end-to-end latency
in any real pipeline. Reducers add ~5 %, in-memory checkpointing ~35 %,
over the bare loop — all in the tens of microseconds.

## 7. Testing strategy

Every feature ships with tests (74 as of this document; core coverage
98 % with the manual-only adapters excluded). LLM behavior is always
exercised through `ScriptedOracle` — deterministic, scripted transcripts;
never a real model. Time-sensitive properties (real parallelism, tokens
arriving before Sigil completion) are asserted through event ordering and
wall-clock bounds.

## 8. Glossary: metaphor ↔ technical equivalence

| Term | Technical equivalent |
|---|---|
| Ritual | Graph builder; `compile()` validates and freezes it |
| Rite | Compiled, executable graph (invocation façade over the scheduler) |
| Sigil | Node: `(aether: dict) -> dict` partial-delta callable, sync or async |
| Aether | Shared state dict |
| AetherSchema | State schema: key → Conduit |
| Conduit | State channel with a reducer (merge policy) |
| Reducer | `(current, update) -> new` merge function |
| Superstep | One BSP iteration: execute frontier → merge → route |
| Frontier | Set of active nodes for the current superstep |
| Seal | Checkpoint (state + next frontier + superstep number) |
| Codex | Checkpoint store (memory / SQLite / Postgres) |
| Invocation | Execution session, keyed by `invocation_id` |
| Omen | Typed, timestamped streaming event |
| Oracle | Abstract LLM interface; `arcana` = model identifier |
| Spell | Tool: callable + JSON schema |
| Tome | Tool registry; loadable from an AgentGrimoire directory tree |
| Ward | Output-intercepting middleware (planned) |
| summon | Agent factory: Oracle + Tome → ReAct-loop Rite |
| Entity | The summoned agent (a Rite from `summon`) |
| Circle | Subgraph (planned) |
| interrupt / Interrupt | Human-in-the-loop pause signal (technical layer) |
| START / END | Virtual entry/exit node names |
| recursion_limit | Superstep bound per Invocation |
