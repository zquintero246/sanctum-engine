"""The Circle — a sealed Rite mounted inside another as a single Sigil.

Subgraph composition. ``circle(rite)`` wraps a compiled Rite into a
Sigil function: when the outer superstep activates it, the inner Rite
performs a complete Invocation of its own — supersteps, reducers,
policies, wards and all — and its final Aether is projected back into
the outer Aether as this Sigil's delta. This is how a ``summon``-ed
Entity (a full ReAct agent) becomes one node of a larger pipeline.

State isolation is explicit: `input_map` chooses what the inner Rite
sees, `output_map` chooses what comes back. Without maps, the full
Aether flows in and the full inner result flows out (fine without an
outer schema; with one, prefer explicit maps so the delta only touches
declared Conduits).

Observability: every inner Omen is echoed to the outer stream wrapped
in ``CircleEchoed(circle=name, omen=...)`` — nested supersteps, spell
calls and tokens stay visible without confusing outer-graph consumers.

Limitations (v1, documented on purpose): each activation is a fresh
inner Invocation (auto-generated invocation_id), so inner Seals do not
resume across outer supersteps — attach a Codex to the *outer* Rite for
persistence; an inner ``interrupt()`` surfaces as a failure of the
Circle Sigil, not as an outer interrupt.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from sanctum.aether import Aether
from sanctum.omens import CircleEchoed, RiteManifested
from sanctum.ritual.errors import SigilExecutionError
from sanctum.ritual.interrupt import Interrupt

InputMap = Mapping[str, str] | Callable[[Aether], Aether] | None
"""How the outer Aether becomes the inner input: None (pass everything),
``{inner_key: outer_key}`` projection, or a callable ``aether -> input``."""

OutputMap = Mapping[str, str] | Callable[[Aether], Aether] | None
"""How the inner final Aether becomes the outer delta: None (return
everything), ``{outer_key: inner_key}`` projection, or a callable
``final -> delta``."""


def circle(
    rite: Any,
    *,
    name: str = "circle",
    input_map: InputMap = None,
    output_map: OutputMap = None,
    resume_map: InputMap = None,
) -> Callable[..., Any]:
    """Seal a compiled Rite into a Sigil function (subgraph as node).

    Returns an async Sigil suitable for ``add_sigil``: it projects the
    outer Aether through `input_map`, invokes `rite` to completion,
    echoes every inner Omen as ``CircleEchoed(circle=name, ...)``, and
    returns the inner final Aether projected through `output_map` as its
    delta. Inner failures propagate, so the outer Sigil's SigilPolicy
    (retries, timeout, on_error) governs the whole Circle.

    **Persistence.** When the inner Rite was compiled with a Codex, the
    Circle derives a stable inner Invocation id —
    ``"<outer invocation_id>:<name>"`` (via the injected ``invocation``
    context) — so inner Seals accumulate under one identity. An inner
    ``interrupt()`` propagates outward as an Interrupt (tagged
    ``"<name>:<inner sigil>"``); when the outer Invocation is resumed and
    re-activates this Sigil, the Circle notices the paused inner
    Invocation and **resumes it from its own Seal** instead of starting
    over — inner progress survives. `resume_map` optionally projects the
    outer Aether into the inner resumption's ``updates`` (dict
    ``{inner: outer}`` or callable); leave it None to resume untouched.
    A previously *completed* inner Invocation is never resumed: each
    fresh activation starts a fresh inner run under the same identity
    (history appends).
    """

    def project_in(aether: Aether) -> Aether:
        if input_map is None:
            return dict(aether)
        if callable(input_map):
            return dict(input_map(dict(aether)))
        return {
            inner: aether[outer]
            for inner, outer in input_map.items()
            if outer in aether
        }

    def project_out(final: Aether) -> Aether:
        if output_map is None:
            return dict(final)
        if callable(output_map):
            return dict(output_map(dict(final)))
        return {
            outer: final[inner]
            for outer, inner in output_map.items()
            if inner in final
        }

    def project_resume(aether: Aether) -> Aether | None:
        if resume_map is None:
            return None
        if callable(resume_map):
            return dict(resume_map(dict(aether)))
        return {
            inner: aether[outer]
            for inner, outer in resume_map.items()
            if outer in aether
        }

    async def perform(aether: Aether, writer=None, invocation=None) -> Aether:
        inner_codex = getattr(rite, "_codex", None)
        stream = None
        if inner_codex is not None and invocation is not None:
            inner_id = f"{invocation.invocation_id}:{name}"
            last = await inner_codex.get(inner_id)
            if last is not None and last.metadata.get("interrupted"):
                # The inner Invocation is paused mid-rite: resume it from
                # its own Seal instead of starting over.
                stream = rite.astream(
                    None,
                    invocation_id=inner_id,
                    updates=project_resume(aether),
                    mode={"omens", "tokens"},
                )
            else:
                stream = rite.astream(
                    project_in(aether),
                    invocation_id=inner_id,
                    mode={"omens", "tokens"},
                )
        if stream is None:
            stream = rite.astream(project_in(aether), mode={"omens", "tokens"})

        final: Aether | None = None
        try:
            async for omen in stream:
                if isinstance(omen, RiteManifested):
                    final = omen.aether
                if writer is not None:
                    await writer(CircleEchoed(circle=name, omen=omen))
        except Interrupt as pause:
            # Tag the pause with the Circle's path so the outer Seal
            # names where the rite is truly waiting, then let it climb.
            pause.sigil = f"{name}:{pause.sigil}" if pause.sigil else name
            raise
        except SigilExecutionError as failure:
            # Re-raise as a plain failure of THIS Sigil so the outer
            # scheduler attributes it to the Circle and the outer
            # SigilPolicy (retries, on_error) governs it.
            cause = failure.__cause__ or failure
            raise RuntimeError(
                f"Circle '{name}' failed at inner Sigil "
                f"'{failure.sigil}': {cause}"
            ) from failure
        if final is None:  # pragma: no cover — astream raises on failure
            raise RuntimeError(
                f"Circle '{name}' concluded without manifesting a result."
            )
        return project_out(final)

    perform.__name__ = f"circle_{name}"
    return perform
