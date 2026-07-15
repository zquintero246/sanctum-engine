# Sanctum

*Where agents are summoned, bound, and set to work — a minimal,
local-first orchestration engine for cyclic state graphs.*

Sanctum models multi-agent orchestration as a ritual of invocation:
knowledge lives in the Grimoire (tools), the Sanctum prepares and controls
the ritual (the engine), entities are summoned (agents), and all of them
cooperate over a shared energy — the Aether (state) — until a result is
manifested. Beneath the metaphor sits a precise execution model: a
**cyclic state graph** run by supersteps (Pregel/BSP), where nodes execute
in parallel, return partial state deltas merged through per-channel
reducers, and conditional edges close the loops that make agentic
behavior possible.

Three commitments shape every design decision:

1. **Local-first.** No proprietary APIs assumed anywhere in the core; the
   `Oracle` interface targets Ollama, llama.cpp, vLLM, LM Studio, and
   in-process GGUF models. The known failure modes of 7-14B local models
   (broken tool-call JSON, invented arguments) are handled as first-class
   input, not as errors.
2. **Zero-dependency core.** The engine is pure Python standard library;
   everything else (HTTP, Postgres, in-process inference, these docs) is
   an optional extra with lazy imports.
3. **Auditability.** Small enough to read whole; deterministic delta
   merging; JSON Seals you can inspect with any tool; a tracing viewer
   that is one HTML file with zero external requests.

Start with [Getting started](getting-started.md), read the
[concepts](concepts/ritual.md) for the full vocabulary, or jump to the
[comparison](comparison.md) if you are wondering how this differs from
LangGraph, n8n, or ADK.
