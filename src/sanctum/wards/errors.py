"""The ways a protective circle refuses what crosses it.

Exceptions raised by the Ward layer.
"""


class WardRejection(Exception):
    """A Ward vetoed a Sigil's delta before it reached the Aether.

    Raise from ``Ward.after_sigil`` to reject the delta. The engine
    discards it, emits a DeltaRejected Omen, and applies the Sigil's
    `on_error` policy when one exists; otherwise the failure surfaces as
    SigilExecutionError with this rejection as ``__cause__``.
    """
