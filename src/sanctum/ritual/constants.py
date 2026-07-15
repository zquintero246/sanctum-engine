"""START and END — the thresholds the ritual crosses.

Sentinel node names marking the virtual entry and exit of the graph. They
are plain strings so they can be stored and serialized like any Sigil name,
but no Sigil may be bound under them.
"""

from typing import Final

START: Final[str] = "__start__"
END: Final[str] = "__end__"

DEFAULT_RECURSION_LIMIT: Final[int] = 25
"""Default maximum number of supersteps per Invocation."""
