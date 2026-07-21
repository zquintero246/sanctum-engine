"""Reading the ritual's signs after the fact — local-first tracing.

Observability without external services. TraceRecorder is a Ward:
register it with ``compile(wards=[...])`` (or ``summon(wards=[...])``)
and it captures the graph manifest plus every Omen, assembling a complete
trace of one Invocation — graph, superstep timeline with per-Sigil
durations, deltas, spell calls with arguments and results, retries,
repairs, rejections, and Seals — written to a ``.sanctum-trace.json``
file when the Rite manifests (call ``flush()`` to write earlier, e.g.
after a failure). ``render_trace()`` turns a trace file into a
self-contained HTML viewer: a single file, no server, no external
requests. Tracing is opt-in by design: without a recorder the engine
pays nothing.
"""

from __future__ import annotations

import dataclasses
import html
import json
from pathlib import Path
from typing import Any

from sanctum.omens.events import Omen
from sanctum.wards.core import Ward

_FORMAT = "sanctum-trace/1"


class TraceRecorder(Ward):
    """The chronicler of the ritual: records everything, changes nothing.

    Observes the Omen stream (``on_omen``) and the graph manifest
    (``on_compile``); never touches deltas, so results are identical with
    or without it. Use one recorder per Invocation. The trace is written
    to `path` when RiteManifested arrives; after an aborted Invocation,
    call ``flush()`` to persist what was captured.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._graph: dict[str, Any] = {}
        self._events: list[dict[str, Any]] = []

    def on_compile(self, manifest: dict[str, Any]) -> None:
        """Remember the graph this recorder is watching."""
        self._graph = {
            "sigils": list(manifest.get("sigils", [])),
            "edges": {k: list(v) for k, v in manifest.get("edges", {}).items()},
            "conditional_edges": {
                k: list(v)
                for k, v in manifest.get("conditional_edges", {}).items()
            },
        }

    async def on_omen(self, omen: Omen) -> None:
        """Record the Omen; write the trace when the Rite manifests."""
        record = {"type": type(omen).__name__, **dataclasses.asdict(omen)}
        self._events.append(record)
        if record["type"] == "RiteManifested":
            self.flush()

    def flush(self) -> Path:
        """Write the trace assembled so far to `path` and return the path."""
        self._path.write_text(
            json.dumps(self.build(), indent=2, default=str), encoding="utf-8"
        )
        return self._path

    def build(self) -> dict[str, Any]:
        """Assemble the trace document from the recorded Omens."""
        events = self._events
        began = next((e for e in events if e["type"] == "RiteBegan"), {})
        manifested = next(
            (e for e in reversed(events) if e["type"] == "RiteManifested"), None
        )
        steps: dict[int, dict[str, Any]] = {}

        def step(number: int) -> dict[str, Any]:
            return steps.setdefault(
                number,
                {
                    "superstep": number,
                    "frontier": [],
                    "sigils": {},
                    "seals": [],
                    "rejections": [],
                },
            )

        def sigil_record(number: int, name: str) -> dict[str, Any]:
            return step(number)["sigils"].setdefault(
                name, {"sigil": name, "retries": []}
            )

        for event in events:
            kind, number = event["type"], event.get("superstep")
            if kind == "SuperstepBegan":
                entry = step(number)
                entry["frontier"] = list(event["frontier"])
                entry["began_at"] = event["timestamp"]
            elif kind == "SigilBegan":
                sigil_record(number, event["sigil"])["began_at"] = event["timestamp"]
            elif kind == "SigilRetried":
                sigil_record(number, event["sigil"])["retries"].append(
                    {"attempt": event["attempt"], "cause": event["cause"]}
                )
            elif kind == "SigilCompleted":
                record = sigil_record(number, event["sigil"])
                record["completed_at"] = event["timestamp"]
                record["delta"] = event["delta"]
                if "began_at" in record:
                    record["duration_ms"] = round(
                        (event["timestamp"] - record["began_at"]) * 1000, 3
                    )
            elif kind == "SuperstepCompleted":
                step(number)["completed_at"] = event["timestamp"]
            elif kind == "SealWritten":
                step(number)["seals"].append(event["seal_id"])
            elif kind == "DeltaRejected":
                step(number)["rejections"].append(
                    {
                        "sigil": event["sigil"],
                        "ward": event["ward"],
                        "reason": event["reason"],
                    }
                )

        supersteps = [
            {**entry, "sigils": list(entry["sigils"].values())}
            for _, entry in sorted(steps.items())
        ]
        repairs = [
            {
                "kind": event["type"],
                "spell": event.get("spell"),
                "detail": event.get("detail") or event.get("reason"),
                "timestamp": event["timestamp"],
            }
            for event in events
            if event["type"] in ("SpellCallRepaired", "SpellCallRejected")
        ]
        return {
            "format": _FORMAT,
            "invocation_id": began.get("invocation_id"),
            "started_at": began.get("timestamp"),
            "finished_at": manifested["timestamp"] if manifested else None,
            "graph": self._graph,
            "supersteps": supersteps,
            "spell_calls": _extract_spell_calls(supersteps),
            "repairs": repairs,
            "result": manifested["aether"] if manifested else None,
            "omens_recorded": len(events),
        }


def _extract_spell_calls(supersteps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Correlate spell-call requests and results found in the deltas."""
    calls: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for entry in supersteps:
        for record in entry["sigils"]:
            messages = (record.get("delta") or {}).get("messages")
            if not isinstance(messages, list):
                continue
            for message in messages:
                if not isinstance(message, dict):
                    continue
                for request in message.get("spell_calls") or []:
                    call_id = request.get("call_id", "")
                    calls[call_id] = {
                        "call_id": call_id,
                        "spell": request.get("spell"),
                        "arguments": request.get("arguments"),
                        "superstep": entry["superstep"],
                    }
                    if call_id not in order:
                        order.append(call_id)
                if message.get("role") == "spell":
                    call_id = message.get("call_id", "")
                    record_entry = calls.setdefault(
                        call_id,
                        {"call_id": call_id, "spell": message.get("spell")},
                    )
                    record_entry["result"] = message.get("content")
                    record_entry["error"] = bool(message.get("error"))
                    if call_id not in order:
                        order.append(call_id)
    return [calls[call_id] for call_id in order]


def render_trace(trace_path: str | Path, html_path: str | Path | None = None) -> Path:
    """Render a trace file into a self-contained HTML viewer.

    One output file, no server, no external requests: all CSS is inline
    and the graph is a static SVG laid out in Python (simple hierarchical
    layers from START to END; back-edges drawn dashed). Returns the path
    of the written HTML (defaults to the trace path with an ``.html``
    suffix).
    """
    source = Path(trace_path)
    trace = json.loads(source.read_text(encoding="utf-8"))
    target = Path(html_path) if html_path is not None else source.with_suffix(".html")
    target.write_text(_render_page(trace), encoding="utf-8")
    return target


# --- HTML rendering (single file, inline styles, no external references) ---

_CSS = """
body { margin: 0; padding: 2rem 3rem; background: #050505; color: #cfc8b8;
       font-family: 'Cascadia Code', 'Cascadia Mono', Consolas, Menlo,
       monospace; font-size: 13.5px; }
h1, h2, h3 { font-weight: 600; color: #cfc8b8; letter-spacing: 0.1em; }
h1 { font-size: 1.5rem; border-bottom: 1px solid #2c2924; padding-bottom: .6rem; }
h2 { font-size: 1.05rem; margin-top: 2.2rem; text-transform: uppercase;
     letter-spacing: 0.18em; }
h2::before { content: "\\2591\\2592\\2593 "; color: #5d574d; }
.meta { color: #8a8377; }
.panel { background: #0a0908; border: 1px solid #2c2924; border-radius: 0;
         padding: 1rem 1.2rem; margin: .8rem 0; }
svg text { font-family: 'Cascadia Code', Consolas, monospace; font-size: 12px; }
.bar-row { display: flex; align-items: center; margin: .25rem 0; }
.bar-label { width: 14rem; color: #cbc4b2; overflow: hidden;
             text-overflow: ellipsis; white-space: nowrap; }
.bar-track { flex: 1; }
.bar { background: #2c2924; border-left: 3px solid #d43b2a; height: 1.05rem;
       min-width: 2px; }
.bar-ms { color: #8a8377; margin-left: .6rem; white-space: nowrap; }
details { margin: .5rem 0; }
summary { cursor: pointer; color: #cbc4b2; }
summary:hover { color: #ffffff; }
pre { background: #070606; border: 1px solid #2c2924; border-radius: 0;
      padding: .7rem; overflow-x: auto; color: #cfc8b8; font-size: 12px; }
pre::-webkit-scrollbar, body::-webkit-scrollbar { height: 8px; width: 8px; }
pre::-webkit-scrollbar-track, body::-webkit-scrollbar-track { background: #0a0a09; }
pre::-webkit-scrollbar-thumb, body::-webkit-scrollbar-thumb {
  background: #2c2924; border: 2px solid #0a0a09; }
.err { color: #ff8a76; }
.tag { color: #5d574d; font-size: 12px; }
table { border-collapse: collapse; width: 100%; }
td, th { border-bottom: 1px solid #1e1c18; padding: .4rem .6rem;
         text-align: left; vertical-align: top; }
th { color: #5d574d; font-weight: normal; text-transform: uppercase;
     letter-spacing: 0.14em; font-size: 11px; }
"""


def _layers(graph: dict[str, Any]) -> list[list[str]]:
    """Assign nodes to layers via BFS from START (cycle-safe)."""
    sigils = graph.get("sigils", [])
    edges = graph.get("edges", {})
    conditional = graph.get("conditional_edges", {})

    def targets_of(node: str) -> list[str]:
        out = list(edges.get(node, []))
        dynamic = conditional.get(node)
        if dynamic and dynamic != ["*"]:
            out += dynamic
        return out

    layers: list[list[str]] = []
    placed: set[str] = set()
    current = [n for n in edges.get("__start__", []) if n != "__end__"]
    while current:
        layer = [n for n in dict.fromkeys(current) if n not in placed and n in sigils]
        if not layer:
            break
        layers.append(layer)
        placed.update(layer)
        upcoming: list[str] = []
        for node in layer:
            upcoming += targets_of(node)
        current = [n for n in upcoming if n not in placed]
    rest = [s for s in sigils if s not in placed]
    if rest:
        layers.append(rest)
    return [["__start__"], *layers, ["__end__"]]


def _graph_svg(graph: dict[str, Any]) -> str:
    """Draw the graph as a static SVG: layered boxes, dashed back-edges."""
    layers = _layers(graph)
    widest = max(len(layer) for layer in layers)
    width = max(360, widest * 190 + 40)
    height = len(layers) * 90 + 30
    position: dict[str, tuple[float, float]] = {}
    for row, layer in enumerate(layers):
        for column, node in enumerate(layer):
            x = width / 2 + (column - (len(layer) - 1) / 2) * 190
            position[node] = (x, 50 + row * 90)
    row_of = {n: r for r, layer in enumerate(layers) for n in layer}

    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        'role="img" aria-label="Ritual graph">'
    ]
    conditional = graph.get("conditional_edges", {})
    all_edges: list[tuple[str, str, bool]] = []
    for source, targets in graph.get("edges", {}).items():
        for target in targets:
            all_edges.append((source, target, False))
    for source, targets in conditional.items():
        for target in targets if targets != ["*"] else ["__end__"]:
            all_edges.append((source, target, True))
    for source, target, dashed in all_edges:
        if source not in position or target not in position:
            continue
        (x1, y1), (x2, y2) = position[source], position[target]
        dash = ' stroke-dasharray="5,4"' if dashed else ""
        if row_of.get(target, 0) <= row_of.get(source, 0) and source != "__start__":
            bend = max(x1, x2) + 90
            parts.append(
                f'<path d="M {x1 + 70:.0f} {y1:.0f} Q {bend:.0f} '
                f'{(y1 + y2) / 2:.0f} {x2 + 70:.0f} {y2:.0f}" fill="none" '
                f'stroke="#665f52" stroke-dasharray="5,4"/>'
            )
        else:
            parts.append(
                f'<line x1="{x1:.0f}" y1="{y1 + 17:.0f}" x2="{x2:.0f}" '
                f'y2="{y2 - 17:.0f}" stroke="#665f52"{dash}/>'
            )
    for node, (x, y) in position.items():
        virtual = node in ("__start__", "__end__")
        label = {"__start__": "START", "__end__": "END"}.get(node, node)
        fill = "#0a0908" if virtual else "#121210"
        stroke = "#665f52" if virtual else "#d43b2a"
        parts.append(
            f'<rect x="{x - 70:.0f}" y="{y - 17:.0f}" width="140" height="34" '
            f'rx="6" fill="{fill}" stroke="{stroke}"/>'
            f'<text x="{x:.0f}" y="{y + 4:.0f}" text-anchor="middle" '
            f'fill="#cfc8b8">{html.escape(label[:18])}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _timeline_html(supersteps: list[dict[str, Any]]) -> str:
    """Render the superstep timeline with proportional duration bars."""
    durations = [
        record.get("duration_ms", 0.0)
        for entry in supersteps
        for record in entry["sigils"]
    ]
    longest = max(durations, default=1.0) or 1.0
    parts = []
    for entry in supersteps:
        frontier = ", ".join(entry.get("frontier", []))
        parts.append(
            f'<div class="panel"><strong>Superstep {entry["superstep"]}</strong> '
            f'<span class="tag">frontier: {html.escape(frontier)}</span>'
        )
        for record in entry["sigils"]:
            duration = record.get("duration_ms", 0.0)
            share = max(2.0, duration / longest * 100)
            retries = (
                f' <span class="err">({len(record["retries"])} retries)</span>'
                if record.get("retries")
                else ""
            )
            label = html.escape(record["sigil"])
            parts.append(
                '<div class="bar-row">'
                f'<span class="bar-label">{label}{retries}</span>'
                f'<span class="bar-track"><span class="bar" '
                f'style="width:{share:.1f}%; display:block"></span></span>'
                f'<span class="bar-ms">{duration:.2f} ms</span></div>'
            )
        for rejection in entry.get("rejections", []):
            parts.append(
                f'<div class="err">delta rejected by {html.escape(rejection["ward"])}'
                f' at {html.escape(rejection["sigil"])}: '
                f'{html.escape(rejection["reason"])}</div>'
            )
        parts.append("</div>")
    return "".join(parts)


def _details_html(supersteps: list[dict[str, Any]]) -> str:
    """Per-superstep, per-Sigil expandable detail (deltas, retries, seals)."""
    parts = []
    for entry in supersteps:
        parts.append(
            f"<details><summary>Superstep {entry['superstep']}</summary>"
            '<div class="panel">'
        )
        for record in entry["sigils"]:
            delta = json.dumps(record.get("delta", {}), indent=2, default=str)
            parts.append(
                f"<h3>{html.escape(record['sigil'])}</h3>"
                f"<pre>{html.escape(delta)}</pre>"
            )
            for retry in record.get("retries", []):
                parts.append(
                    f'<div class="err">retry {retry["attempt"]}: '
                    f'{html.escape(str(retry["cause"]))}</div>'
                )
        if entry.get("seals"):
            seals = ", ".join(entry["seals"])
            parts.append(f'<div class="tag">seals: {html.escape(seals)}</div>')
        parts.append("</div></details>")
    return "".join(parts)


def _spells_html(spell_calls: list[dict[str, Any]]) -> str:
    """Render the spell-call table (arguments and results)."""
    if not spell_calls:
        return '<p class="meta">No Spells were cast.</p>'
    rows = []
    for call in spell_calls:
        arguments = html.escape(json.dumps(call.get("arguments"), default=str))
        result = html.escape(str(call.get("result", "")))
        marker = ' class="err"' if call.get("error") else ""
        rows.append(
            f"<tr><td>{html.escape(str(call.get('spell')))}</td>"
            f"<td><code>{arguments}</code></td>"
            f"<td{marker}>{result}</td></tr>"
        )
    return (
        "<table><tr><th>Spell</th><th>Arguments</th><th>Result</th></tr>"
        + "".join(rows)
        + "</table>"
    )


def _render_page(trace: dict[str, Any]) -> str:
    """Compose the whole single-file HTML document."""
    started = trace.get("started_at") or 0
    finished = trace.get("finished_at") or started
    total_ms = (finished - started) * 1000
    repairs = trace.get("repairs", [])
    repair_rows = "".join(
        f'<div class="{"err" if r["kind"] == "SpellCallRejected" else "tag"}">'
        f'{html.escape(r["kind"])} — {html.escape(str(r.get("spell")))}: '
        f'{html.escape(str(r.get("detail")))}</div>'
        for r in repairs
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Sanctum trace — {html.escape(str(trace.get("invocation_id")))}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>Sanctum — trace of Invocation {html.escape(str(trace.get("invocation_id")))}</h1>
<p class="meta">{len(trace.get("supersteps", []))} supersteps ·
{total_ms:.1f} ms · {trace.get("omens_recorded", 0)} omens recorded ·
format {html.escape(trace.get("format", ""))}</p>
<h2>Graph</h2>
<div class="panel">{_graph_svg(trace.get("graph", {}))}</div>
<h2>Timeline</h2>
{_timeline_html(trace.get("supersteps", []))}
<h2>Spell calls</h2>
<div class="panel">{_spells_html(trace.get("spell_calls", []))}</div>
{f'<h2>Repairs</h2><div class="panel">{repair_rows}</div>' if repairs else ""}
<h2>Superstep detail</h2>
{_details_html(trace.get("supersteps", []))}
<h2>Final Aether</h2>
<pre>{html.escape(json.dumps(trace.get("result"), indent=2, default=str))}</pre>
</body>
</html>
"""
