"""The ways the ledger refuses an inscription or a consultation.

Exceptions raised by the Codex layer.
"""


class SealError(Exception):
    """A Seal could not be written, found, or restored.

    Raised when persistence fails (e.g. the Aether is not
    JSON-serializable for a storage backend) or when resumption cannot
    proceed: no Codex attached, no Seals recorded for the Invocation, or an
    unknown `seal_id`.
    """
