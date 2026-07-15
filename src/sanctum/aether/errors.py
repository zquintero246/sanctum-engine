"""The ways the Aether rejects what does not belong to it.

Exceptions raised by the Aether layer.
"""


class AetherValidationError(Exception):
    """Energy tried to flow outside the declared Conduits.

    Raised at invocation time when a Sigil's delta — or the initial input —
    writes to a key not declared in the AetherSchema. The message names the
    offending Sigil (when one is involved) and the unknown key.
    """
