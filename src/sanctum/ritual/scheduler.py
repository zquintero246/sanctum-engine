"""The scheduler paces the ritual, superstep by superstep, in lockstep.

Explicit BSP (Bulk Synchronous Parallel / Pregel) execution loop for a
compiled graph. Each superstep: (1) run every Sigil in the frontier
concurrently, (2) collect their partial deltas, (3) apply reducers in
deterministic Sigil-insertion order, (4) evaluate the executed Sigils'
edges — static fan-out plus routers — to compute the next frontier,
(5) repeat until the frontier is empty or holds only END, bounded by
``recursion_limit``.

Fan-out: a Sigil with several static outgoing edges activates all its
targets for the next superstep. Fan-in defaults to "any" semantics: a
Sigil runs as soon as any predecessor activates it, and multiple
activations within the same superstep coalesce into a single execution.
Sigils bound with ``join="all"`` are a barrier instead: activations
accumulate — across supersteps when branches have uneven lengths — and
the Sigil enters the frontier only once every static predecessor has
signaled it. Pending activations persist inside each Seal's metadata
(reserved key ``"__join_pending__"``) so resumption keeps the barrier's
progress; if the frontier empties while a join still waits, the run
fails with SigilJoinError naming the missing predecessors. If a Sigil
raises, its sibling tasks are cancelled, the superstep's deltas are
discarded, and the failure surfaces as SigilExecutionError.

When a Codex is attached, a Seal (full Aether, next frontier, superstep
number) is written at the end of every superstep, and one more when a
Sigil calls ``interrupt()`` — capturing the aborted superstep's frontier
so resumption re-executes it.

Every lifecycle point emits an Omen through the `emit` callback (a no-op
unless ``Rite.astream`` attaches a stream): RiteBegan, SuperstepBegan,
SigilBegan, SigilRetried, SigilCompleted, SuperstepCompleted,
SealWritten, RiteManifested, and TokenEmitted for payloads a Sigil pushes
through its injected `writer`.

Resilience: each Sigil runs under a SigilPolicy (per-Sigil or the
compile-time default) — timeout per attempt, retries with backoff over
`retry_on` failures (SigilRetried Omens), and an `on_error` fallback
Sigil for definitive failures: the failed superstep is aborted without a
Seal, the failure is appended to the reserved ``"__errors__"`` Conduit
(managed by the engine; JSON-serializable entries with sigil, error,
type, superstep), and the fallback runs as the next superstep. See
``sanctum.ritual.policies`` for the precedence contract.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from typing import Any

from sanctum.aether import Aether, AetherSchema
from sanctum.codex import Codex, Seal
from sanctum.omens import (
    DeltaRejected,
    Omen,
    RiteBegan,
    RiteManifested,
    SealWritten,
    SigilBegan,
    SigilCompleted,
    SigilRetried,
    SuperstepBegan,
    SuperstepCompleted,
    TokenEmitted,
)
from sanctum.ritual.constants import DEFAULT_RECURSION_LIMIT, END, START
from sanctum.ritual.errors import (
    RecursionLimitError,
    SigilExecutionError,
    SigilJoinError,
    SigilTimeoutError,
)
from sanctum.ritual.interrupt import Interrupt
from sanctum.ritual.policies import SigilPolicy
from sanctum.wards import Ward, WardRejection

_NO_POLICY = SigilPolicy()

SigilFn = Callable[..., Aether | Awaitable[Aether]]
"""A Sigil's callable: takes the full Aether, returns a partial delta.

May be a plain function or a coroutine function; the engine awaits
awaitable results transparently. A Sigil that declares a `writer`
parameter receives an async callable — ``await writer(token)`` streams the
token out through ``astream`` while the Sigil is still running.
"""

WriterFn = Callable[[Any], Awaitable[None]]
"""The async callable injected into Sigils that declare a `writer`
parameter. Passing an Omen instance emits it verbatim (custom
observability events, e.g. spell-repair Omens); any other payload is
wrapped in a TokenEmitted Omen.
"""

EmitFn = Callable[[Omen], Awaitable[None]]
"""The scheduler's event sink; ``Rite.astream`` attaches a queue-backed
implementation, plain ``ainvoke`` leaves the default no-op.
"""


async def _discard(omen: Omen) -> None:
    """Swallow Omens when no stream is attached."""


def _accepts_writer(fn: SigilFn) -> bool:
    """Detect whether a Sigil declares the optional `writer` parameter.

    Inspected once at construction; callables whose signature cannot be
    introspected are treated as writer-less.
    """
    try:
        parameters = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return "writer" in parameters

RouterFn = Callable[[Aether], str | Awaitable[str]]
"""A conditional edge's router: takes the full Aether, returns the name of
the next Sigil (or END), or a key of the edge's `path_map` when one was
given. May be sync or async.
"""


class Scheduler:
    """The cadence of the invocation: who acts, when, and in what order.

    BSP executor over a validated graph. Holds the Sigils, static edges
    (source -> list of targets), conditional edges, optional AetherSchema,
    and the recursion limit; ``run()`` drives the superstep loop. Built by
    ``Ritual.compile()`` via Rite — not meant to be constructed directly.
    """

    def __init__(
        self,
        sigils: Mapping[str, SigilFn],
        edges: Mapping[str, Sequence[str]],
        conditional_edges: Mapping[str, tuple[RouterFn, dict[str, str] | None]],
        schema: AetherSchema | None = None,
        recursion_limit: int = DEFAULT_RECURSION_LIMIT,
        codex: Codex | None = None,
        policies: Mapping[str, SigilPolicy] | None = None,
        default_policy: SigilPolicy | None = None,
        wards: Sequence[Ward] | None = None,
        joins: Mapping[str, str] | None = None,
    ) -> None:
        self._codex = codex
        self._policies: dict[str, SigilPolicy] = dict(policies or {})
        self._default_policy = default_policy
        self._wards: list[Ward] = list(wards or [])
        self._sigils: dict[str, SigilFn] = dict(sigils)
        self._edges: dict[str, list[str]] = {
            source: list(targets) for source, targets in edges.items()
        }
        self._conditional_edges: dict[str, tuple[RouterFn, dict[str, str] | None]] = (
            dict(conditional_edges)
        )
        self._schema = schema
        self._recursion_limit = recursion_limit
        self._order: dict[str, int] = {
            name: index for index, name in enumerate(self._sigils)
        }
        self._writer_sigils: set[str] = {
            name for name, fn in self._sigils.items() if _accepts_writer(fn)
        }
        # join="all" Sigils and the static predecessors each one waits for.
        self._join_required: dict[str, frozenset[str]] = {
            name: frozenset(
                source
                for source, targets in self._edges.items()
                if name in targets
            )
            for name, mode in (joins or {}).items()
            if mode == "all"
        }
        if self._wards:
            manifest = {
                "sigils": list(self._sigils),
                "edges": {
                    source: list(targets)
                    for source, targets in self._edges.items()
                },
                "conditional_edges": {
                    source: sorted(set(path_map.values())) if path_map else ["*"]
                    for source, (_, path_map) in self._conditional_edges.items()
                },
            }
            for guard in self._wards:
                guard.on_compile(manifest)

    async def run(
        self,
        input: Mapping[str, Any],
        *,
        invocation_id: str,
        frontier: Iterable[str] | None = None,
        superstep: int = 0,
        emit: EmitFn = _discard,
        join_pending: Mapping[str, Iterable[str]] | None = None,
    ) -> Aether:
        """Perform the superstep loop until the ritual concludes.

        Starts with a shallow copy of `input` as the Aether and, by
        default, START's targets as the first frontier; a resumption passes
        the `frontier` and `superstep` restored from a Seal, and the
        counter continues from there (the recursion limit applies to the
        Invocation's total). Ends — returning the final Aether — when the
        frontier is empty or contains only END. With a Codex attached, a
        Seal is written after every superstep and upon interrupt. Every
        lifecycle point is reported through `emit`.

        Raises:
            Interrupt: If a Sigil pauses the Invocation via ``interrupt()``
                (re-raised after the Seal is written).
            RecursionLimitError: If the Invocation would exceed
                `recursion_limit` supersteps.
            SigilExecutionError: If a Sigil raises during a superstep.
            SigilJoinError: If the frontier empties while a ``join="all"``
                Sigil still waits for predecessors that will never run.
            TypeError: If a Sigil returns something other than a mapping.
            ValueError: If a router returns a value that is neither a bound
                Sigil nor END, is missing from its `path_map`, or targets a
                ``join="all"`` Sigil.
        """
        if self._wards:
            emit = self._wrap_emit_with_wards(emit)
        aether: Aether = dict(input)
        pending: dict[str, set[str]] = {
            name: set(sources) for name, sources in (join_pending or {}).items()
        }
        if frontier is None:
            current_frontier: set[str] = set()
            for target in self._edges.get(START, ()):
                self._admit(START, target, pending, current_frontier)
        else:
            current_frontier = set(frontier)
        supersteps = superstep
        previous: list[str] = []
        await emit(RiteBegan(invocation_id=invocation_id))
        while True:
            active = sorted(
                (name for name in current_frontier if name != END),
                key=self._order.__getitem__,
            )
            if not active:
                if pending:
                    missing = {
                        name: sorted(self._join_required[name] - sources)
                        for name, sources in sorted(pending.items())
                    }
                    described = "; ".join(
                        f"'{name}' still waits for {waits}"
                        for name, waits in missing.items()
                    )
                    raise SigilJoinError(
                        f"Invocation '{invocation_id}' concluded with "
                        f"unsatisfied join='all' Sigil(s): {described}. A "
                        "branch feeding the join never ran — check the "
                        "routers on its predecessors, or use join='any'.",
                        pending=missing,
                    )
                await emit(RiteManifested(aether=dict(aether), superstep=supersteps))
                return aether
            if supersteps >= self._recursion_limit:
                names = ", ".join(f"'{name}'" for name in previous) or "(none)"
                raise RecursionLimitError(
                    f"Recursion limit of {self._recursion_limit} supersteps "
                    f"exceeded in Invocation '{invocation_id}'; last Sigil(s) "
                    f"executed: {names}. Check the cycle's stop condition or "
                    "raise recursion_limit in compile()."
                )
            await emit(
                SuperstepBegan(superstep=supersteps + 1, frontier=list(active))
            )
            try:
                deltas = await self._execute_superstep(
                    active, aether, invocation_id, supersteps + 1, emit
                )
            except Interrupt as pause:
                await self._write_seal(
                    invocation_id,
                    aether,
                    current_frontier,
                    supersteps,
                    metadata={
                        "interrupted": True,
                        "sigil": pause.sigil,
                        "reason": pause.reason,
                        **self._join_metadata(pending),
                    },
                    emit=emit,
                )
                raise
            except SigilExecutionError as failure:
                fallback = self._policy_for(failure.sigil).on_error
                if fallback is None:
                    raise
                # The failed superstep is aborted: its deltas are gone and
                # NO Seal is written for it (resumption continues from the
                # last valid Seal); the counter still advances so cycles of
                # failure stay bounded by recursion_limit. The fallback
                # superstep runs — and seals — normally.
                supersteps += 1
                previous = active
                cause = failure.__cause__ or failure
                aether = dict(aether)
                aether["__errors__"] = [
                    *aether.get("__errors__", []),
                    {
                        "sigil": failure.sigil,
                        "error": str(cause),
                        "type": type(cause).__name__,
                        "superstep": supersteps,
                    },
                ]
                current_frontier = {fallback}
                continue
            aether = self._apply_deltas(aether, deltas)
            supersteps += 1
            previous = active
            await emit(SuperstepCompleted(superstep=supersteps, aether=dict(aether)))
            current_frontier = await self._evaluate_edges(active, aether, pending)
            await self._write_seal(
                invocation_id,
                aether,
                current_frontier,
                supersteps,
                metadata=self._join_metadata(pending) or None,
                emit=emit,
            )

    async def _write_seal(
        self,
        invocation_id: str,
        aether: Aether,
        frontier: Iterable[str],
        superstep: int,
        metadata: Mapping[str, Any] | None = None,
        emit: EmitFn = _discard,
    ) -> None:
        """Inscribe the superstep's Seal in the Codex, if one is attached.

        The frontier is stored sorted for determinism. Interrupt Seals mark
        `metadata` with the pausing Sigil and reason; their frontier is the
        aborted superstep's, so resumption re-executes it. Emits a
        SealWritten Omen after the Codex accepts the Seal.
        """
        if self._codex is None:
            return
        seal = Seal(
            aether=dict(aether),
            frontier=sorted(frontier),
            superstep=superstep,
            timestamp=time.time(),
            metadata=dict(metadata or {}),
        )
        await self._codex.put(invocation_id, seal)
        await emit(SealWritten(seal_id=seal.seal_id, superstep=superstep))

    async def _execute_superstep(
        self,
        active: Sequence[str],
        aether: Aether,
        invocation_id: str,
        superstep: int,
        emit: EmitFn = _discard,
    ) -> list[tuple[str, Any]]:
        """Run the frontier's Sigils concurrently against the same Aether.

        Every active Sigil receives its own shallow copy of the pre-superstep
        Aether (BSP: nobody observes a sibling's delta), plus an injected
        async `writer` when its signature declares one — each
        ``await writer(token)`` emits a TokenEmitted Omen immediately.
        Returns ``(sigil_name, delta)`` pairs in Sigil insertion order. On
        the first Sigil failure or interrupt the remaining sibling tasks
        are cancelled and the superstep's deltas are discarded; failures
        surface as SigilExecutionError and take precedence over
        interrupts, with ties resolved by Sigil insertion order.
        """

        async def perform(name: str) -> tuple[str, Any]:
            await emit(SigilBegan(sigil=name, superstep=superstep))
            for guard in self._wards:
                await guard.before_sigil(name, dict(aether))
            policy = self._policy_for(name)
            attempt = 0
            while True:
                try:
                    result = await self._attempt_sigil(
                        name, aether, superstep, emit, policy
                    )
                except Interrupt as pause:
                    if pause.sigil is None:
                        pause.sigil = name
                    raise
                except Exception as exc:
                    if attempt < policy.retries and isinstance(exc, policy.retry_on):
                        attempt += 1
                        await emit(
                            SigilRetried(
                                sigil=name,
                                superstep=superstep,
                                attempt=attempt,
                                cause=repr(exc),
                            )
                        )
                        delay = policy.backoff(attempt)
                        if delay > 0:
                            await asyncio.sleep(delay)
                        continue
                    if isinstance(exc, SigilExecutionError):
                        raise
                    raise SigilExecutionError(
                        f"Sigil '{name}' raised {type(exc).__name__} in "
                        f"Invocation '{invocation_id}'; the superstep was "
                        f"cancelled and its deltas discarded. Aether at "
                        f"failure: {aether!r}",
                        sigil=name,
                        aether=dict(aether),
                    ) from exc
                if isinstance(result, Mapping):
                    result = await self._ward_delta(
                        name, dict(result), aether, superstep, invocation_id, emit
                    )
                    delta = dict(result)
                else:
                    delta = {}
                await emit(
                    SigilCompleted(sigil=name, superstep=superstep, delta=delta)
                )
                return name, result

        def rank(sigil: str | None) -> int:
            return self._order.get(sigil or "", len(self._order))

        try:
            async with asyncio.TaskGroup() as group:
                tasks = [group.create_task(perform(name)) for name in active]
        except ExceptionGroup as eg:
            failures = [
                exc for exc in eg.exceptions if isinstance(exc, SigilExecutionError)
            ]
            if failures:
                failures.sort(key=lambda exc: rank(exc.sigil))
                raise failures[0] from failures[0].__cause__
            pauses = [exc for exc in eg.exceptions if isinstance(exc, Interrupt)]
            if pauses:
                pauses.sort(key=lambda exc: rank(exc.sigil))
                raise pauses[0] from None
            raise
        return [task.result() for task in tasks]

    def _policy_for(self, name: str) -> SigilPolicy:
        """Resolve the Sigil's policy: per-Sigil, then default, then none."""
        return self._policies.get(name) or self._default_policy or _NO_POLICY

    def _wrap_emit_with_wards(self, emit: EmitFn) -> EmitFn:
        """Give every Ward's on_omen a look at each Omen before the stream."""

        async def emit_with_wards(omen: Omen) -> None:
            for guard in self._wards:
                await guard.on_omen(omen)
            await emit(omen)

        return emit_with_wards

    async def _ward_delta(
        self,
        name: str,
        delta: dict[str, Any],
        aether: Aether,
        superstep: int,
        invocation_id: str,
        emit: EmitFn,
    ) -> dict[str, Any]:
        """Run the Ward pipeline over one Sigil's delta.

        Wards apply in registration order; each one's output delta is the
        next one's input, and the final delta is what merges into the
        Aether (and what Seals and SigilCompleted Omens record). A
        WardRejection vetoes the delta: a DeltaRejected Omen is emitted
        and the veto surfaces as SigilExecutionError, so the Sigil's
        `on_error` policy applies when present.
        """
        current: Ward | None = None
        try:
            for guard in self._wards:
                current = guard
                delta = await guard.after_sigil(name, dict(aether), delta)
        except WardRejection as veto:
            ward_name = type(current).__name__
            await emit(
                DeltaRejected(
                    sigil=name,
                    superstep=superstep,
                    ward=ward_name,
                    reason=str(veto),
                )
            )
            raise SigilExecutionError(
                f"Ward '{ward_name}' rejected the delta of Sigil '{name}' "
                f"in Invocation '{invocation_id}': {veto}. The superstep "
                "was cancelled and its deltas discarded.",
                sigil=name,
                aether=dict(aether),
            ) from veto
        return delta

    async def _attempt_sigil(
        self,
        name: str,
        aether: Aether,
        superstep: int,
        emit: EmitFn,
        policy: SigilPolicy,
    ) -> Any:
        """Run one attempt of a Sigil, bounded by its policy's timeout.

        Timeouts bound async Sigils via ``asyncio.timeout``; a synchronous
        Sigil body cannot be interrupted mid-run (offload blocking work
        with ``asyncio.to_thread``). Exceeding the bound raises
        SigilTimeoutError with the configured time in the message.
        """
        if policy.timeout is None:
            return await self._invoke_sigil(name, aether, superstep, emit)
        try:
            async with asyncio.timeout(policy.timeout):
                return await self._invoke_sigil(name, aether, superstep, emit)
        except TimeoutError:
            raise SigilTimeoutError(
                f"Sigil '{name}' exceeded its timeout of {policy.timeout}s "
                "and was cancelled.",
                sigil=name,
                aether=dict(aether),
                timeout=policy.timeout,
            ) from None

    async def _invoke_sigil(
        self, name: str, aether: Aether, superstep: int, emit: EmitFn
    ) -> Any:
        """Call the Sigil — writer injected when declared — and await it."""
        if name in self._writer_sigils:

            async def writer(token: Any) -> None:
                if isinstance(token, Omen):
                    await emit(token)
                    return
                await emit(
                    TokenEmitted(sigil=name, superstep=superstep, token=token)
                )

            result = self._sigils[name](dict(aether), writer=writer)
        else:
            result = self._sigils[name](dict(aether))
        if inspect.isawaitable(result):
            result = await result
        return result

    def _apply_deltas(
        self, aether: Aether, deltas: Sequence[tuple[str, Any]]
    ) -> Aether:
        """Fold one superstep's deltas into the Aether, deterministically.

        Deltas arrive — and are applied — in Sigil insertion order, so
        concurrent writes to the same Conduit resolve the same way on every
        run. With an AetherSchema each key merges through its Conduit's
        reducer; without one, deltas overwrite. Returns a new dict.
        """
        for name, delta in deltas:
            if not isinstance(delta, Mapping):
                raise TypeError(
                    f"Sigil '{name}' must return a partial Aether delta "
                    f"(a mapping), got {type(delta).__name__}."
                )
        if self._schema is not None:
            return self._schema.apply_deltas(aether, deltas)
        merged: Aether = dict(aether)
        for _, delta in deltas:
            merged.update(delta)
        return merged

    def _admit(
        self,
        source: str,
        target: str,
        pending: dict[str, set[str]],
        frontier: set[str],
    ) -> None:
        """Let one activation through, honoring the target's join mode.

        A ``join="any"`` target (the default) enters the frontier at once.
        A ``join="all"`` target records `source` among its pending
        activators and enters only when every static predecessor has
        signaled it — at which point its pending record resets, so joins
        inside cycles re-arm on every pass.
        """
        required = self._join_required.get(target)
        if required is None:
            frontier.add(target)
            return
        gathered = pending.setdefault(target, set())
        gathered.add(source)
        if gathered >= required:
            frontier.add(target)
            pending.pop(target, None)

    def _join_metadata(self, pending: dict[str, set[str]]) -> dict[str, Any]:
        """Serialize pending join activations for a Seal's metadata.

        Returns ``{"__join_pending__": {sigil: sorted activators}}`` when a
        join is mid-gather, an empty dict otherwise — resumption restores
        the barrier's progress from this reserved key.
        """
        if not pending:
            return {}
        return {
            "__join_pending__": {
                name: sorted(sources) for name, sources in pending.items()
            }
        }

    async def _evaluate_edges(
        self,
        executed: Sequence[str],
        aether: Aether,
        pending: dict[str, set[str]],
    ) -> set[str]:
        """Compute the next frontier from the executed Sigils' edges.

        Static edges fan out to all their targets; conditional edges are
        routed against the post-superstep Aether, in Sigil insertion order.
        The frontier is a set, so a Sigil activated by several predecessors
        in the same superstep runs once (fan-in "any" semantics). Every
        activation passes through ``_admit``, so ``join="all"`` targets
        hold back until their barrier is complete.
        """
        frontier: set[str] = set()
        for name in executed:
            for target in self._edges.get(name, ()):
                self._admit(name, target, pending, frontier)
            if name in self._conditional_edges:
                frontier.add(await self._route(name, aether))
        return frontier

    async def _route(self, source: str, aether: Aether) -> str:
        """Evaluate one conditional edge's router against the Aether.

        Awaits async routers, translates the result through `path_map` when
        the edge has one, and validates the destination.
        """
        router, path_map = self._conditional_edges[source]
        choice = router(dict(aether))
        if inspect.isawaitable(choice):
            choice = await choice
        if path_map is not None:
            if choice not in path_map:
                raise ValueError(
                    f"Router at Sigil '{source}' returned '{choice}', which "
                    f"is not a key of its path_map ({sorted(path_map)})."
                )
            choice = path_map[choice]
        if choice != END and choice not in self._sigils:
            raise ValueError(
                f"Router at Sigil '{source}' routed to unknown Sigil "
                f"'{choice}'; routers must return a bound Sigil name or END."
            )
        if choice in self._join_required:
            raise ValueError(
                f"Router at Sigil '{source}' routed to '{choice}', which is "
                "a join='all' Sigil; conditional activations cannot satisfy "
                "a wait-all join — reach it through static edges instead."
            )
        return choice
