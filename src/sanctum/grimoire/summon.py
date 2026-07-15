"""summon — calling an Entity into the circle, ready to act.

Agent factory. Builds the canonical ReAct loop as a Rite using nothing
but the public primitives — Ritual, a Conduit with the append reducer,
and conditional edges — demonstrating they suffice for agentic behavior:

    oracle -> (spell_calls?) -> spells -> oracle -> ... -> END

The Aether holds ``messages`` (append; dicts with ``role``/``content``),
plus ``repair_rounds`` and ``rejected_calls`` for the repair layer. The
``oracle`` Sigil sends the system role plus the transcript to the Oracle
and appends its answer (carrying ``spell_calls`` when Spells were
requested). The ``spells`` Sigil passes EVERY call through the repair
layer (``sanctum.grimoire.repair``) before casting: malformed JSON is
recovered locally (SpellCallRepaired Omen), while unknown Spells and
invalid arguments become correction messages back to the Oracle
(SpellCallRejected Omen). Consecutive correction-only rounds are bounded
by `max_repair_rounds`; past it the loop surrenders with
SpellCallParseError. Spell execution failures stay conversational: they
are injected as error messages and the loop survives. The loop ends when
an answer carries no spell_calls.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sanctum.aether import Aether, AetherSchema, Conduit, append
from sanctum.codex import Codex
from sanctum.grimoire.core import Tome
from sanctum.grimoire.errors import SpellCallParseError, SpellExecutionError
from sanctum.grimoire.repair import repair_spell_call
from sanctum.omens import SpellCallRejected, SpellCallRepaired
from sanctum.oracle import Oracle, SpellCall
from sanctum.oracle.robust import PromptedSpellCalling
from sanctum.ritual import DEFAULT_RECURSION_LIMIT, END, Rite, Ritual
from sanctum.ritual.scheduler import WriterFn
from sanctum.wards import Ward

DEFAULT_ROLE = (
    "You are a summoned entity. Answer faithfully and cast your Spells "
    "when the task requires them."
)


def summon(
    oracle: Oracle,
    tome: Tome | None = None,
    role: str = DEFAULT_ROLE,
    *,
    spell_calling: str = "native",
    max_repair_rounds: int = 2,
    recursion_limit: int = DEFAULT_RECURSION_LIMIT,
    codex: Codex | None = None,
    wards: Sequence[Ward] | None = None,
) -> Rite:
    """Summon an Entity: an Oracle bound to a Tome, sealed as a Rite.

    Returns a compiled Rite implementing the ReAct loop described in the
    module docstring. Invoke it with
    ``rite.ainvoke({"messages": [{"role": "user", "content": ...}]})``;
    the final Aether's ``messages`` holds the full transcript.

    Args:
        oracle: The voice consulted each turn.
        tome: The Spells available to the Entity; None summons a
            spell-less conversationalist.
        role: System prompt prepended (not stored in the Aether) on every
            consultation.
        spell_calling: How Spell schemas reach the model — ``"native"``
            (the Oracle's tool support), ``"prompted"`` (wrap in
            PromptedSpellCalling: schemas in the system prompt, calls
            parsed from text), or ``"auto"`` (native first, falling back
            to prompted when the endpoint rejects tools).
        max_repair_rounds: Consecutive correction-only rounds tolerated
            before the loop surrenders with SpellCallParseError
            (default 2). A round with at least one executable call resets
            the counter.
        recursion_limit: Superstep bound forwarded to ``compile()``.
        codex: Optional Seal store forwarded to ``compile()``.
        wards: Middleware pipeline forwarded to ``compile()``. The
            Oracle's `usage` counters are attached to each assistant
            message, so a UsageWard tallies them out of the box.

    Raises:
        ValueError: If `spell_calling` names an unknown strategy.
    """
    if spell_calling == "prompted":
        oracle = PromptedSpellCalling(oracle)
    elif spell_calling == "auto":
        oracle = PromptedSpellCalling(oracle, mode="auto")
    elif spell_calling != "native":
        raise ValueError(
            f"Unknown spell_calling strategy '{spell_calling}'; use "
            "'native', 'prompted', or 'auto'."
        )

    spell_schemas = tome.schemas() if tome is not None else None

    async def consult_oracle(aether: Aether) -> Aether:
        transcript = [{"role": "system", "content": role}, *aether["messages"]]
        response = await oracle.generate(transcript, spells=spell_schemas)
        message: dict[str, Any] = {"role": "assistant", "content": response.text}
        if response.usage:
            message["usage"] = dict(response.usage)
        if response.spell_calls:
            message["spell_calls"] = [
                {
                    "call_id": call.call_id,
                    "spell": call.spell,
                    "arguments": dict(call.arguments),
                }
                for call in response.spell_calls
            ]
        return {"messages": [message]}

    async def cast_spells(aether: Aether, writer: WriterFn) -> Aether:
        """Repair, validate, and cast the last answer's spell calls.

        Every call goes through the repair layer first. Rejections append
        correction messages (``"error": True``) and count one repair
        round; a round with no rejections resets the counter.
        """
        results: list[dict[str, Any]] = []
        rejected: list[str] = []
        for call_data in aether["messages"][-1].get("spell_calls", []):
            call = SpellCall(
                spell=call_data["spell"],
                arguments=dict(call_data["arguments"]),
                call_id=call_data["call_id"],
            )
            outcome = repair_spell_call(call, tome)
            if outcome.correction is not None:
                await writer(
                    SpellCallRejected(spell=call.spell, reason=outcome.correction)
                )
                rejected.append(
                    outcome.raw
                    if outcome.raw is not None
                    else f"{call.spell}({call.arguments!r})"
                )
                results.append(
                    {
                        "role": "spell",
                        "spell": call.spell,
                        "call_id": call.call_id,
                        "content": outcome.correction,
                        "error": True,
                    }
                )
                continue
            mended = outcome.call
            assert mended is not None and tome is not None  # RepairOutcome contract
            if outcome.repaired is not None:
                await writer(
                    SpellCallRepaired(spell=mended.spell, detail=outcome.repaired)
                )
            entry: dict[str, Any] = {
                "role": "spell",
                "spell": mended.spell,
                "call_id": mended.call_id,
            }
            try:
                value = await tome.get(mended.spell).execute(mended.arguments)
                entry["content"] = str(value)
            except SpellExecutionError as error:
                entry["content"] = f"SpellExecutionError: {error}"
                entry["error"] = True
            results.append(entry)
        rounds = aether.get("repair_rounds", 0) + 1 if rejected else 0
        return {
            "messages": results,
            "repair_rounds": rounds,
            "rejected_calls": rejected,
        }

    def route_after_oracle(aether: Aether) -> str:
        return "spells" if aether["messages"][-1].get("spell_calls") else END

    def route_after_spells(aether: Aether) -> str:
        """Back to the Oracle — unless the repair budget is exhausted."""
        rounds = aether.get("repair_rounds", 0)
        if rounds > max_repair_rounds:
            rejected = list(aether.get("rejected_calls") or [])
            raise SpellCallParseError(
                f"Spell calls stayed invalid after {rounds} correction "
                f"rounds (max_repair_rounds={max_repair_rounds}). Last "
                f"rejected call text(s): {rejected!r}",
                rejected=rejected,
                rounds=rounds,
            )
        return "oracle"

    ritual = Ritual(
        AetherSchema(
            {
                "messages": Conduit(reducer=append),
                "repair_rounds": Conduit(),
                "rejected_calls": Conduit(),
            }
        )
    )
    ritual.add_sigil("oracle", consult_oracle)
    ritual.add_sigil("spells", cast_spells)
    ritual.set_entry_point("oracle")
    ritual.add_conditional_edge("oracle", route_after_oracle)
    ritual.add_conditional_edge("spells", route_after_spells)
    return ritual.compile(
        recursion_limit=recursion_limit, codex=codex, wards=wards
    )
