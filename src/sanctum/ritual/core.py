"""The Ritual is drawn, sealed, and performed as a Rite.

Graph builder and executable plan. A Ritual registers Sigils (nodes),
static edges — several per source, enabling fan-out — and conditional
edges (routers); ``compile()`` validates the graph and returns a Rite.
Execution follows the BSP superstep model implemented in
``sanctum.ritual.scheduler``: all frontier Sigils run concurrently, their
deltas merge deterministically (through each Conduit's reducer when the
Ritual has an AetherSchema, by overwrite otherwise), and edges decide the
next frontier. Cycles are allowed and are what enables agentic behavior
(think -> act -> observe -> ...), bounded by ``recursion_limit``. With a
Codex, every superstep leaves a Seal (resumption, ``interrupt()``,
time-travel); ``astream`` yields Omens live. A "wait for all
predecessors" fan-in and subgraphs (Circles) arrive in later phases.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections import deque
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from typing import Any

from sanctum.aether import Aether, AetherSchema
from sanctum.codex import Codex, Seal, SealError
from sanctum.omens import Omen, resolve_modes
from sanctum.ritual.constants import DEFAULT_RECURSION_LIMIT, END, START
from sanctum.ritual.errors import RitualValidationError
from sanctum.ritual.policies import SigilPolicy
from sanctum.ritual.scheduler import RouterFn, Scheduler, SigilFn
from sanctum.wards import Ward


class Ritual:
    """The circle where Sigils are bound before the invocation.

    Mutable graph builder. Register nodes with ``add_sigil``, connect them
    with ``add_edge``/``add_conditional_edge`` (or ``set_entry_point`` for
    a START edge), then call ``compile()`` to validate the graph and obtain
    an executable Rite. Builder methods return ``self`` to allow chaining.

    When an AetherSchema is given, every delta key must name a declared
    Conduit and merges through that Conduit's reducer; without a schema,
    deltas merge by plain overwrite. Within a superstep, deltas are applied
    in Sigil insertion order — the order Sigils were bound to the Ritual —
    so concurrent writes to the same Conduit are deterministic.

    A source with several static edges fans out: all targets activate in
    the next superstep. Fan-in uses "any" semantics: a Sigil runs as soon
    as any predecessor activates it, and multiple activations within one
    superstep coalesce into a single execution ("wait for all
    predecessors" is planned future work).
    """

    def __init__(self, schema: AetherSchema | None = None) -> None:
        self._schema = schema
        self._sigils: dict[str, SigilFn] = {}
        self._edges: dict[str, list[str]] = {}
        self._conditional_edges: dict[str, tuple[RouterFn, dict[str, str] | None]] = {}
        self._policies: dict[str, SigilPolicy] = {}

    def add_sigil(
        self, name: str, fn: SigilFn, policy: SigilPolicy | None = None
    ) -> Ritual:
        """Bind a Sigil to the Ritual.

        Registers a node in the graph. `fn` receives the full Aether (state
        dict) and must return a partial delta to be merged into the state;
        it may be sync or async. `policy` grants the Sigil its resilience —
        timeout, retries with backoff, `on_error` fallback (see
        SigilPolicy); it overrides ``compile(default_policy=...)``.

        Raises:
            RitualValidationError: If `name` is START/END, already bound,
                or `fn` is not callable.
        """
        if name in (START, END):
            raise RitualValidationError(
                f"'{name}' is a reserved constant and cannot name a Sigil."
            )
        if name in self._sigils:
            raise RitualValidationError(
                f"Sigil '{name}' is already bound to this Ritual."
            )
        if not callable(fn):
            raise RitualValidationError(
                f"Sigil '{name}' must be bound to a callable, "
                f"got {type(fn).__name__}."
            )
        self._sigils[name] = fn
        if policy is not None:
            self._policies[name] = policy
        return self

    def add_edge(self, source: str, target: str) -> Ritual:
        """Trace a fixed path from one Sigil to the next.

        Registers a static edge: after `source` completes, `target`
        activates in the next superstep. `source` may be START and `target`
        may be END; cycles (edges back to earlier Sigils) are allowed. A
        source may carry several static edges — all targets activate
        together (fan-out) — but static edges and a conditional edge are
        mutually exclusive on the same source.

        Raises:
            RitualValidationError: If the edge starts at END, ends at
                START, duplicates an existing edge, or `source` already has
                a conditional edge.
        """
        if source == END:
            raise RitualValidationError("END cannot be the source of an edge.")
        if target == START:
            raise RitualValidationError("START cannot be the target of an edge.")
        if source in self._conditional_edges:
            raise RitualValidationError(
                f"Sigil '{source}' already has a conditional edge; static "
                "edges and a conditional edge cannot share a source."
            )
        targets = self._edges.setdefault(source, [])
        if target in targets:
            raise RitualValidationError(
                f"Edge '{source}' -> '{target}' is already traced."
            )
        targets.append(target)
        return self

    def add_conditional_edge(
        self,
        source: str,
        router: RouterFn,
        path_map: Mapping[str, str] | None = None,
    ) -> Ritual:
        """Trace a branching path decided at invocation time.

        Registers a conditional edge: after `source` completes, `router`
        receives the full Aether and returns the name of the next Sigil (or
        END). When `path_map` is given, the router's return value is used
        as a key into it and the mapped name is followed instead. Routing a
        Sigil back to an earlier one is how cycles — and agentic loops —
        are built.

        Raises:
            RitualValidationError: If `source` is START or END, `router` is
                not callable, or `source` already has an outgoing edge
                (static or conditional).
        """
        if source == START:
            raise RitualValidationError(
                "START cannot carry a conditional edge; choose the entry "
                "point with set_entry_point(name)."
            )
        if source == END:
            raise RitualValidationError("END cannot be the source of an edge.")
        if not callable(router):
            raise RitualValidationError(
                f"Router for Sigil '{source}' must be callable, "
                f"got {type(router).__name__}."
            )
        if source in self._edges:
            raise RitualValidationError(
                f"Sigil '{source}' already has static edge(s) to "
                f"{self._edges[source]}; static edges and a conditional "
                "edge cannot share a source."
            )
        if source in self._conditional_edges:
            raise RitualValidationError(
                f"Sigil '{source}' already has a conditional edge."
            )
        self._conditional_edges[source] = (
            router,
            dict(path_map) if path_map is not None else None,
        )
        return self

    def set_entry_point(self, name: str) -> Ritual:
        """Mark a Sigil where the invocation begins.

        Equivalent to ``add_edge(START, name)``. May be called several
        times: all entry points activate in the first superstep (fan-out
        from START).
        """
        return self.add_edge(START, name)

    def compile(
        self,
        recursion_limit: int = DEFAULT_RECURSION_LIMIT,
        codex: Codex | None = None,
        default_policy: SigilPolicy | None = None,
        wards: Sequence[Ward] | None = None,
    ) -> Rite:
        """Seal the Ritual into a Rite.

        Validates the graph and returns the executable plan. Checks, in
        order: an entry point exists, every static edge and every
        `path_map` target references a bound Sigil (or END), every policy's
        `on_error` names a bound Sigil (other than its owner), every Sigil
        is reachable from START (`on_error` fallbacks count as reachable),
        and every Sigil has an outgoing edge. Cycles are valid — the graph
        is a cyclic state graph, not a DAG. A conditional edge without
        `path_map` may route anywhere, so it counts as reaching every
        Sigil; its actual return values are checked at invocation time.

        Args:
            recursion_limit: Maximum supersteps per Invocation before the
                Rite raises RecursionLimitError (default 25).
            codex: Seal store. When given, the Rite writes a Seal at the
                end of every superstep and supports resumption,
                ``interrupt()``, and time-travel.
            default_policy: Resilience applied to Sigils without their own
                policy (see SigilPolicy).
            wards: Middleware pipeline, applied in registration order —
                each Ward's output delta is the next one's input (see
                sanctum.wards).

        Raises:
            RitualValidationError: On the first violation found, with a
                message naming the offending Sigils.
        """
        if recursion_limit < 1:
            raise RitualValidationError(
                f"recursion_limit must be a positive integer, "
                f"got {recursion_limit}."
            )
        for owner, policy in self._policies.items():
            self._validate_policy(policy, owner=owner)
        if default_policy is not None:
            self._validate_policy(default_policy, owner=None)
        for ward in wards or ():
            if not isinstance(ward, Ward):
                raise RitualValidationError(
                    f"Wards must subclass sanctum.wards.Ward; got "
                    f"{type(ward).__name__}."
                )
        if not self._edges.get(START):
            raise RitualValidationError(
                "The Ritual has no entry point; call set_entry_point(name) "
                "or add_edge(START, name) before compiling."
            )

        for source, targets in self._edges.items():
            for target in targets:
                if source != START and source not in self._sigils:
                    raise RitualValidationError(
                        f"Edge '{source}' -> '{target}' starts at unknown "
                        f"Sigil '{source}'; bind it with add_sigil first."
                    )
                if target != END and target not in self._sigils:
                    raise RitualValidationError(
                        f"Edge '{source}' -> '{target}' points to unknown "
                        f"Sigil '{target}'; bind it with add_sigil first."
                    )
        for source, (_, path_map) in self._conditional_edges.items():
            if source not in self._sigils:
                raise RitualValidationError(
                    f"Conditional edge starts at unknown Sigil '{source}'; "
                    "bind it with add_sigil first."
                )
            for key, target in (path_map or {}).items():
                if target != END and target not in self._sigils:
                    raise RitualValidationError(
                        f"Conditional edge at '{source}' maps '{key}' to "
                        f"unknown Sigil '{target}'; bind it with add_sigil "
                        "first."
                    )

        unreachable = sorted(
            set(self._sigils) - self._reachable_from_start(default_policy)
        )
        if unreachable:
            raise RitualValidationError(
                f"Unreachable Sigil(s): {', '.join(unreachable)}; every "
                "Sigil must lie on a path from START."
            )

        dead_ends = sorted(
            set(self._sigils) - set(self._edges) - set(self._conditional_edges)
        )
        if dead_ends:
            raise RitualValidationError(
                f"Sigil(s) without an outgoing edge: {', '.join(dead_ends)}; "
                "add an edge to another Sigil or to END."
            )

        return Rite(
            sigils=self._sigils,
            edges=self._edges,
            conditional_edges=self._conditional_edges,
            schema=self._schema,
            recursion_limit=recursion_limit,
            codex=codex,
            policies=self._policies,
            default_policy=default_policy,
            wards=wards,
        )

    def _validate_policy(self, policy: SigilPolicy, owner: str | None) -> None:
        """Check one SigilPolicy at compile time.

        `owner` is the Sigil the policy is attached to, or None for the
        compile-level default.
        """
        described = f"Sigil '{owner}'" if owner else "the default policy"
        if policy.timeout is not None and policy.timeout <= 0:
            raise RitualValidationError(
                f"The timeout of {described} must be positive, "
                f"got {policy.timeout}."
            )
        if policy.retries < 0:
            raise RitualValidationError(
                f"The retries of {described} must be >= 0, got {policy.retries}."
            )
        if policy.on_error is not None:
            if policy.on_error not in self._sigils:
                raise RitualValidationError(
                    f"The on_error fallback of {described} names unknown "
                    f"Sigil '{policy.on_error}'; bind it with add_sigil "
                    "first."
                )
            if policy.on_error == owner:
                raise RitualValidationError(
                    f"Sigil '{owner}' cannot be its own on_error fallback."
                )

    def _reachable_from_start(
        self, default_policy: SigilPolicy | None = None
    ) -> set[str]:
        """Collect every Sigil reachable from START (cycle-safe BFS).

        Static edges reach all their targets. A conditional edge with a
        `path_map` reaches the map's targets; one without a `path_map` may
        route to any Sigil, so it reaches all of them. A Sigil's `on_error`
        fallback (own policy or the default) is reachable whenever the
        Sigil is.
        """
        reached: set[str] = set()
        frontier: deque[str] = deque(self._edges.get(START, ()))
        while frontier:
            node = frontier.popleft()
            if node == END or node in reached or node not in self._sigils:
                continue
            reached.add(node)
            frontier.extend(self._edges.get(node, ()))
            if node in self._conditional_edges:
                _, path_map = self._conditional_edges[node]
                targets = path_map.values() if path_map else self._sigils
                frontier.extend(targets)
            policy = self._policies.get(node) or default_policy
            if policy is not None and policy.on_error is not None:
                frontier.append(policy.on_error)
        return reached


class Rite:
    """The sealed plan of the invocation, ready to be performed.

    Immutable executable graph produced by ``Ritual.compile()``. Delegates
    execution to the BSP Scheduler: every frontier Sigil runs concurrently
    within a superstep, deltas merge deterministically in Sigil insertion
    order (through Conduit reducers when the Rite has an AetherSchema, by
    overwrite otherwise), and edges decide the next frontier until END or
    ``recursion_limit``. With a Codex attached, every superstep leaves a
    Seal, enabling resumption after ``interrupt()`` and time-travel from
    any historic Seal.
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
    ) -> None:
        self._schema = schema
        self._codex = codex
        self._scheduler = Scheduler(
            sigils=sigils,
            edges=edges,
            conditional_edges=conditional_edges,
            schema=schema,
            recursion_limit=recursion_limit,
            codex=codex,
            policies=policies,
            default_policy=default_policy,
            wards=wards,
        )

    async def ainvoke(
        self,
        input: Aether | None = None,
        *,
        invocation_id: str | None = None,
        seal_id: str | None = None,
        updates: Mapping[str, Any] | None = None,
    ) -> Aether:
        """Perform the invocation, fresh or resumed from a Seal.

        Fresh run — `input` given, no `seal_id`: runs the superstep loop
        with a shallow copy of `input` as the initial Aether. Each active
        Sigil receives a copy of the full Aether (mutating it has no
        effect), deltas merge deterministically, and edges compute the next
        frontier. Returns the final Aether when the frontier empties or
        holds only END.

        Resumption — `input` omitted (requires a Codex and
        `invocation_id`): restores the Invocation's latest Seal — or the
        Seal named by `seal_id` for time-travel — and continues from its
        frontier and superstep count. `updates` optionally injects new data
        into the restored Aether before continuing (human-in-the-loop after
        ``interrupt()``); with a schema it merges through the Conduit
        reducers. Resumption appends new Seals to the same history.

        Args:
            input: Initial Aether values for a fresh run; omit to resume.
            invocation_id: Identifier of this execution session; generated
                (uuid4 hex) when omitted on a fresh run.
            seal_id: Historic Seal to time-travel from (implies resumption).
            updates: Delta injected into the restored Aether on resumption.

        Raises:
            AetherValidationError: If the input, a delta, or `updates`
                writes outside the declared Conduits (schema Rites only).
            Interrupt: If a Sigil pauses the Invocation via ``interrupt()``.
            RecursionLimitError: If the Invocation exceeds the Rite's
                `recursion_limit` supersteps without reaching END.
            SealError: If resumption lacks a Codex or `invocation_id`, no
                Seals exist, or `seal_id` is unknown.
            SigilExecutionError: If a Sigil raises during a superstep.
            TypeError: If a Sigil returns something other than a mapping.
            ValueError: If a router returns a value that is neither a bound
                Sigil nor END, or is missing from its `path_map`.
        """
        aether, frontier, superstep, invocation_id = await self._prepare(
            input, invocation_id, seal_id, updates
        )
        return await self._scheduler.run(
            aether,
            invocation_id=invocation_id,
            frontier=frontier,
            superstep=superstep,
        )

    async def astream(
        self,
        input: Aether | None = None,
        *,
        invocation_id: str | None = None,
        seal_id: str | None = None,
        updates: Mapping[str, Any] | None = None,
        mode: str | Iterable[str] = "updates",
    ) -> AsyncIterator[Omen]:
        """Perform the invocation, streaming Omens as it unfolds.

        Async generator over the same fresh/resume semantics as
        ``ainvoke`` (`input`, `invocation_id`, `seal_id`, `updates`). The
        scheduler runs as a background task; Omens flow through a queue and
        are yielded as they happen, filtered by `mode`:

        - ``"updates"`` (default): SigilCompleted per finished Sigil, with
          its delta.
        - ``"values"``: SuperstepCompleted with the full Aether after each
          superstep.
        - ``"omens"``: granular lifecycle — RiteBegan, SuperstepBegan,
          SigilBegan, SigilCompleted, SealWritten, RiteManifested.
        - ``"tokens"``: TokenEmitted payloads pushed by Sigils through
          their injected `writer`, delivered while the Sigil still runs.

        Modes combine: ``mode={"updates", "tokens"}`` yields the union.
        Exceptions from the Invocation (Interrupt, SigilExecutionError,
        RecursionLimitError, and everything else ``ainvoke`` raises)
        propagate to the consumer after the already-emitted Omens are
        drained. Closing the generator early cancels the Invocation.

        Raises:
            ValueError: If `mode` names an unknown stream mode.
        """
        kinds = resolve_modes(mode)
        aether, frontier, superstep, invocation_id = await self._prepare(
            input, invocation_id, seal_id, updates
        )
        queue: asyncio.Queue[Omen | None] = asyncio.Queue()

        async def emit(omen: Omen) -> None:
            await queue.put(omen)

        async def drive() -> None:
            try:
                await self._scheduler.run(
                    aether,
                    invocation_id=invocation_id,
                    frontier=frontier,
                    superstep=superstep,
                    emit=emit,
                )
            finally:
                await queue.put(None)

        task = asyncio.create_task(drive())
        try:
            while True:
                omen = await queue.get()
                if omen is None:
                    break
                if isinstance(omen, kinds):
                    yield omen
            await task
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

    async def _prepare(
        self,
        input: Aether | None,
        invocation_id: str | None,
        seal_id: str | None,
        updates: Mapping[str, Any] | None,
    ) -> tuple[Aether, list[str] | None, int, str]:
        """Resolve the starting state of a fresh or resumed Invocation.

        Returns ``(aether, frontier, superstep, invocation_id)`` — frontier
        None means "start from START's targets". Fresh runs validate
        `input` against the schema and mint an invocation_id when missing;
        resumptions restore the Seal and merge `updates` into its Aether
        (through the Conduit reducers when a schema is set).

        Raises:
            SealError: On invalid fresh/resume combinations or when the
                Seal cannot be found (see ``_load_seal``).
        """
        if input is not None and seal_id is None:
            if updates is not None:
                raise SealError(
                    "`updates` only applies when resuming; on a fresh run "
                    "put the values in `input`."
                )
            if invocation_id is None:
                invocation_id = uuid.uuid4().hex
            if self._schema is not None:
                self._schema.validate_input(input)
            return dict(input), None, 0, invocation_id

        if input is not None:
            raise SealError(
                "Provide either `input` (fresh run) or `seal_id` "
                "(time-travel resumption), not both; use `updates` to "
                "inject data while resuming."
            )
        seal = await self._load_seal(invocation_id, seal_id)
        aether: Aether = dict(seal.aether)
        if updates:
            if self._schema is not None:
                aether = self._schema.apply_delta(
                    aether, updates, sigil="<resume updates>"
                )
            else:
                aether.update(updates)
        assert invocation_id is not None  # guaranteed by _load_seal
        return aether, list(seal.frontier), seal.superstep, invocation_id

    async def _load_seal(self, invocation_id: str | None, seal_id: str | None) -> Seal:
        """Fetch the Seal a resumption continues from.

        The latest Seal by default; the one named by `seal_id` for
        time-travel.

        Raises:
            SealError: If the Rite has no Codex, `invocation_id` is
                missing, no Seals exist, or `seal_id` is not in the
                Invocation's history.
        """
        if self._codex is None:
            raise SealError(
                "Cannot resume without a Codex; compile the Ritual with "
                "compile(codex=...)."
            )
        if invocation_id is None:
            raise SealError("Resuming requires the `invocation_id` to restore.")
        if seal_id is None:
            seal = await self._codex.get(invocation_id)
            if seal is None:
                raise SealError(
                    f"No Seals recorded for Invocation '{invocation_id}'; "
                    "nothing to resume."
                )
            return seal
        history = await self._codex.list(invocation_id)
        matches = [seal for seal in history if seal.seal_id == seal_id]
        if not matches:
            raise SealError(
                f"Seal '{seal_id}' not found in Invocation "
                f"'{invocation_id}' ({len(history)} Seal(s) recorded)."
            )
        return matches[-1]

    def invoke(
        self,
        input: Aether | None = None,
        *,
        invocation_id: str | None = None,
        seal_id: str | None = None,
        updates: Mapping[str, Any] | None = None,
    ) -> Aether:
        """Perform the invocation synchronously.

        Convenience wrapper around ``ainvoke`` for non-async callers — same
        fresh/resume semantics. Must not be called from within a running
        event loop.
        """
        return asyncio.run(
            self.ainvoke(
                input,
                invocation_id=invocation_id,
                seal_id=seal_id,
                updates=updates,
            )
        )
