# Time-travel

*Return to any pressed Seal and let history run again — without erasing
what happened the first time.*

Every superstep leaves a Seal; `seal_id` resumes from any of them:

```python
seals = await codex.list("inv-1")
replay = await rite.ainvoke(invocation_id="inv-1",
                            seal_id=seals[1].seal_id)
```

## The semantics (stable since v0.1.0)

- **A Seal restores historic state.** Its Aether is what the world looked
  like *at that superstep* — not what it became later. Resuming from a
  Seal written before some fact arrived replays the run without that
  fact. In particular, resuming from an *interrupt* Seal will interrupt
  again unless you inject the awaited data.
- **Combine `seal_id` with `updates`** to change history deliberately:

    ```python
    replay = await rite.ainvoke(
        invocation_id="inv-1",
        seal_id=seals[1].seal_id,
        updates={"approved": True},   # what-if: approve at superstep 1
    )
    ```

- **Histories are append-only.** A replay appends its new Seals after the
  old ones instead of rewriting them; `codex.get()` returns the most
  recently *written* Seal. The audit trail stays honest — you can see
  both the original run and every replay.
- **The superstep counter resumes from the Seal**, and `recursion_limit`
  applies to the Invocation's total — long histories with many replays
  may need a higher limit at `compile()`.

Typical uses: debugging an agent's wrong turn by replaying from just
before it, A/B-ing a prompt change from a mid-run Seal, and recovering a
crashed pipeline from the last valid checkpoint (see
[resilience policies](../concepts/policies.md) — failed supersteps never
write a Seal, so the latest Seal is always consistent).
