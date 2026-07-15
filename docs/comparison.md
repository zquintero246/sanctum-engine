# Comparison: LangGraph, n8n, Google ADK

*Know the other circles before drawing your own.*

Sanctum does not try to out-feature the incumbents. It competes in one
niche — **local-first agent orchestration you can audit whole** — and
reimplements the ideas that matter (cycles, reducers, checkpoints,
streaming, middleware) in a core small enough to read in an afternoon.

| | **Sanctum** | **LangGraph** | **n8n** | **Google ADK** |
|---|---|---|---|---|
| Execution model | Cyclic state graph, BSP supersteps | Cyclic state graph, Pregel-inspired | Visual workflow automation (mostly linear/branching) | Agent framework with delegation trees |
| Core dependencies | **None** (Python stdlib) | LangChain ecosystem | Node.js platform | Google Cloud SDK stack |
| LLM coupling | Local-first `Oracle` interface: Ollama, llama.cpp, vLLM, LM Studio, in-process GGUF | Any provider, best with LangChain integrations | Nodes per provider | Gemini-first |
| Small-model tool-calling | First-class: tolerant JSON repair, correction rounds, prompted fallback | Provider-dependent | Provider-dependent | Gemini-native |
| State merging | Per-channel reducers, deterministic insertion order | Per-channel reducers | Node outputs | Session state |
| Persistence | JSON Seals: memory / SQLite / Postgres; append-only history | Checkpointers: memory / SQLite / Postgres | Built-in DB | Sessions/Memory services |
| Human-in-the-loop | `interrupt()` + resume with injected updates | `interrupt()` / breakpoints | Manual approval nodes | Callbacks |
| Time-travel | From any Seal, honest append-only replays | From any checkpoint | Re-run executions | — |
| Streaming | Typed Omens, combinable modes, Sigil `writer` | Multiple stream modes | UI executions | Event streams |
| Middleware | Ward pipeline (transform/veto deltas, observe omens) | — (callbacks/hooks) | — | Plugins/callbacks |
| Observability | Local: JSONL audit, usage tally, single-file HTML trace viewer — no external services | LangSmith (SaaS) or callbacks | Built-in UI | Cloud Trace |
| Resilience | Per-Sigil timeout/retries/backoff/fallback policies | Node retry policies | Node retries | Runner config |
| Maturity & ecosystem | Young, small, thesis-grade docs | Production-grade, large ecosystem | Mature product, huge integration catalog | Backed by Google, growing |

## Choose…

- **Sanctum** when you run local models, need to understand and audit
  every superstep, want observability without SaaS, or are studying how
  agent engines work (the [architecture document](architecture.md) is the
  design rationale, trade-offs included).
- **LangGraph** when you need the batteries: hundreds of integrations, a
  managed platform, and production mileage.
- **n8n** when the job is automating SaaS workflows visually, not
  building agent loops.
- **ADK** when you build on Google's stack and Gemini.
