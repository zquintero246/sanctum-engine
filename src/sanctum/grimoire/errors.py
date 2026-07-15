"""The ways a Spell can fail when cast.

Exceptions raised by the Grimoire layer.
"""


class SpellExecutionError(Exception):
    """A Spell failed while being cast.

    Raised when a Spell's callable raises, or when an unknown Spell is
    requested from a Tome. Carries the Spell's name (`spell`) and the
    original exception as ``__cause__`` when there is one. In the ReAct
    loop built by ``summon``, this error does not crash the Invocation: it
    is injected into the transcript as an error message for the Oracle to
    react to.
    """

    def __init__(self, message: str, *, spell: str) -> None:
        super().__init__(message)
        self.spell = spell


class SpellCallParseError(Exception):
    """The Oracle's spell calls stayed invalid after every repair round.

    Raised by the summon loop when `max_repair_rounds` consecutive rounds
    of correction messages did not yield an executable spell call.
    `rejected` preserves the raw text of the last rejected call(s) for
    debugging; `rounds` is how many correction rounds were spent.
    """

    def __init__(self, message: str, *, rejected: list[str], rounds: int) -> None:
        super().__init__(message)
        self.rejected = rejected
        self.rounds = rounds
