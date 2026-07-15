# Tracing & the HTML viewer

*A chronicler stands in the circle: it records everything and changes
nothing.*

`TraceRecorder` is a [Ward](../concepts/wards.md) — opt-in, one per
Invocation, zero overhead when absent:

```python
from sanctum.omens import TraceRecorder, render_trace

recorder = TraceRecorder("run.sanctum-trace.json")
entity = summon(oracle, tome, wards=[recorder])
await entity.ainvoke(input, invocation_id="inv-7")
```

When the Rite manifests, `run.sanctum-trace.json` holds the complete
story (format `sanctum-trace/1`): the graph, the superstep timeline with
per-Sigil durations, every delta, spell calls correlated with their
arguments and results, retries, repairs, rejections, and Seal ids. After
a failure, call `recorder.flush()` to persist what was captured.

## The viewer

```sh
python -m sanctum.trace render run.sanctum-trace.json
```

renders a **single self-contained HTML file** — no server, no JavaScript
frameworks, zero external requests (verified by test):

- a static SVG of the graph (hierarchical layers from START to END;
  cycles and conditional edges dashed),
- the superstep timeline with duration bars per Sigil (retries marked),
- expandable per-superstep detail: deltas, retries, Seals,
- the spell-call table and the repairs section,
- the final Aether.

Open it in any browser, attach it to a bug report, archive it next to
the Seals — it will render identically offline in ten years.

Programmatic use: `render_trace(trace_path) -> html_path`.

## Overhead, measured

The benchmark (`python benchmarks/superstep_overhead.py`) includes a
TraceRecorder case: on the order of a hundred microseconds per superstep
on a consumer laptop — noise next to model inference. Recording is
in-memory until the single JSON write at the end.
