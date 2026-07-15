# Robust tool-calling with local models

*Small voices stumble; the ritual answers with patience, not collapse.*

Local 7-14B models fumble tool calls in known ways: malformed JSON,
prose mixed into the payload, invented or missing arguments, calls to
Spells that do not exist — or no native tool support at all. Sanctum
treats all of these as first-class input.

## The repair layer (always on)

Every spell call — native or prompted — passes through three tiers
before execution:

1. **Local repair.** Arguments that failed JSON parsing arrive flagged
   `__malformed_json__`; tolerant extraction recovers objects from fenced
   ```` ```json ```` blocks, unbalanced braces, and single quotes. A
   successful mend emits a `SpellCallRepaired` Omen and the call
   proceeds — no model round trip.
2. **Conversational repair.** Unknown Spell names get a correction
   message listing the available Spells; missing/unexpected arguments get
   one naming exactly what to fix. The correction is injected into the
   transcript (`SpellCallRejected` Omen) and the model answers again.
3. **Surrender.** After `max_repair_rounds` consecutive correction-only
   rounds (default 2, configurable on `summon`), the loop raises
   `SpellCallParseError` with the original raw text preserved in
   `.rejected` for debugging.

Spell *execution* failures stay conversational too: they become
`role: "spell"` error messages the model can react to.

## No native tools? Prompt them

`PromptedSpellCalling` wraps any Oracle: Spell schemas go into the system
prompt with a delimited call format, and the answer's text is parsed back
into calls (unparseable blocks flow into the repair layer above).

```python
entity = summon(oracle, tome, spell_calling="prompted")  # always prompt
entity = summon(oracle, tome, spell_calling="auto")      # try native,
                                                         # fall back once
                                                         # tools are rejected
```

With `"auto"`, the first endpoint response rejecting tools flips the
wrapper to prompted mode for the rest of the session.

## Observing it

All of it streams: `SpellCallRepaired`, `SpellCallRejected` (mode
`"omens"`) and the trace viewer's *Repairs* section
([tracing guide](tracing.md)) show exactly what was mended, what was
corrected, and what the model finally cast.
