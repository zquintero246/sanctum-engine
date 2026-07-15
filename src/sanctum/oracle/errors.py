"""The ways the Oracle's voice can fail to arrive.

Exceptions raised by the Oracle adapters. Every message is written to be
actionable: it names the endpoint involved and states the most likely fix
(start the server, pull the model, raise the timeout).
"""


class OracleError(Exception):
    """The Oracle could not be consulted.

    Base class of all Oracle adapter failures.
    """


class OracleConnectionError(OracleError):
    """No one answered at the Oracle's address.

    The model server could not be reached (connection refused, DNS
    failure). The message names the address and how to start a server
    there.
    """


class OracleTimeoutError(OracleError):
    """The Oracle stayed silent past the allotted time.

    The request exceeded the configured timeout. Common with local models
    on first request, while weights load into memory.
    """


class OracleResponseError(OracleError):
    """The Oracle's voice arrived, but as a refusal.

    The server answered with an error status (unknown model, malformed
    request, server fault). The message includes the HTTP status, a body
    snippet, and a hint when the cause is recognizable.
    """
