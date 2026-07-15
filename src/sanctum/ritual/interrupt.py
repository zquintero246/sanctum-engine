"""Halting the ritual so the outside world may speak.

Human-in-the-loop control flow. A Sigil calls ``interrupt()`` to pause the
Invocation: the current superstep is aborted (its deltas discarded), the
scheduler writes a Seal when a Codex is attached, and the Interrupt signal
propagates to the caller. The caller resumes later with
``rite.ainvoke(invocation_id=...)``, optionally injecting new data into
the Aether via `updates`; the interrupted superstep's frontier re-executes
in full.
"""

from __future__ import annotations

from typing import NoReturn


class Interrupt(Exception):
    """The ritual paused, awaiting words from beyond the circle.

    Control-flow signal, not a failure: raised by ``interrupt()`` inside a
    Sigil and propagated to the caller after a Seal is written. Carries the
    caller-facing `reason` and the name of the Sigil that paused (`sigil`,
    filled in by the scheduler).
    """

    def __init__(self, reason: str = "") -> None:
        super().__init__(reason or "Ritual interrupted, awaiting external input.")
        self.reason = reason
        self.sigil: str | None = None


def interrupt(reason: str = "") -> NoReturn:
    """Pause the Invocation from inside a Sigil, leaving a Seal behind.

    Raises Interrupt, which aborts the current superstep (its deltas are
    discarded), persists a Seal when the Rite has a Codex, and surfaces to
    the caller of ``ainvoke``/``invoke``. On resumption the whole
    interrupted frontier — including the Sigil that paused — runs again,
    so interrupting Sigils should check the Aether to decide whether the
    awaited data has arrived.
    """
    raise Interrupt(reason)
