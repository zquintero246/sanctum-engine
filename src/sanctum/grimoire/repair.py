"""Mending the Oracle's imperfect spell calls before they are cast.

Repair layer, applied to EVERY spell call — native tool calling or
prompted — before execution. Three tiers: **local repair** (tolerant JSON
extraction via ``sanctum.oracle.robust.extract_json``, no model round
trip), **conversational repair** (a correction message returned to the
Oracle through the transcript, written so a small model knows exactly
what to fix), and **surrender** (``SpellCallParseError``, raised by the
summon loop once ``max_repair_rounds`` is exhausted). Repairs and
rejections surface as SpellCallRepaired / SpellCallRejected Omens.
"""

from __future__ import annotations

from dataclasses import dataclass

from sanctum.grimoire.core import Tome
from sanctum.oracle.core import SpellCall
from sanctum.oracle.robust import extract_json


@dataclass(frozen=True, slots=True)
class RepairOutcome:
    """What the repair layer decided about one spell call.

    Exactly one of `call`/`correction` is set: `call` is the executable
    (possibly mended) SpellCall; `correction` is the message to return to
    the Oracle. `repaired` describes the local mend applied, if any;
    `raw` preserves the original unparseable text for debugging.
    """

    call: SpellCall | None = None
    correction: str | None = None
    repaired: str | None = None
    raw: str | None = None


def repair_spell_call(call: SpellCall, tome: Tome | None) -> RepairOutcome:
    """Validate and, when possible, mend one spell call.

    Checks in order: (1) arguments flagged ``"__malformed_json__"`` are
    recovered with ``extract_json`` — a recovered full call object
    (``{"spell": ..., "arguments": {...}}``) replaces both name and
    arguments; unrecoverable text becomes a correction with the original
    preserved. (2) Unknown Spell names get a correction listing the
    available Spells. (3) Arguments are checked against the Spell's JSON
    schema — missing required or unexpected keys get a correction naming
    them. Corrections are phrased for a small model: they state exactly
    what to change.
    """
    name = call.spell
    arguments = dict(call.arguments)
    repaired: str | None = None

    if "__malformed_json__" in arguments:
        raw = str(arguments["__malformed_json__"])
        extracted = extract_json(raw)
        if extracted is None:
            return RepairOutcome(
                correction=(
                    "Your Spell call could not be parsed as JSON. Original "
                    f"text: {raw!r}. Write the call again with valid JSON "
                    "arguments matching the Spell's schema."
                ),
                raw=raw,
            )
        if isinstance(extracted.get("spell"), str) and isinstance(
            extracted.get("arguments"), dict
        ):
            name = extracted["spell"] or name
            arguments = dict(extracted["arguments"])
        else:
            arguments = extracted
        repaired = "arguments recovered from malformed JSON"

    if tome is None:
        return RepairOutcome(
            correction=(
                f"Spell '{name}' cannot be cast: the Entity was summoned "
                "without a Tome (no Spells are available). Answer directly, "
                "without Spell calls."
            )
        )
    if name not in tome:
        available = ", ".join(entry.name for entry in tome) or "(none)"
        return RepairOutcome(
            correction=(
                f"Unknown Spell '{name}'. Available Spells: {available}. "
                "Write the call again using one of those exact names."
            )
        )

    parameters = tome.get(name).parameters or {}
    properties = parameters.get("properties") or {}
    required = parameters.get("required") or []
    missing = [key for key in required if key not in arguments]
    unexpected = [key for key in arguments if properties and key not in properties]
    if missing or unexpected:
        problems = []
        if missing:
            problems.append(f"missing required argument(s): {', '.join(missing)}")
        if unexpected:
            problems.append(
                f"unexpected argument(s): {', '.join(unexpected)} — "
                f"allowed: {', '.join(properties) or '(none)'}"
            )
        return RepairOutcome(
            correction=(
                f"Invalid arguments for Spell '{name}': {'; '.join(problems)}. "
                "Write the call again with arguments matching the schema."
            )
        )

    return RepairOutcome(
        call=SpellCall(spell=name, arguments=arguments, call_id=call.call_id),
        repaired=repaired,
    )
