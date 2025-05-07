"""
:Description: Contains private constants, types, and classes used in the APIs provided by this package.
"""

from typing import Final

# Timeout of HTTP requests, in seconds
DEFAULT_HTTP_REQ_TIMEOUT: Final[int] = 60


class BaseApiException(Exception):
    """
    Base generic API exception indicating an unrecoverable failure of this API.

    This exception is meant to condense many possible failures into one generic error. The thinking is, if the calling
    code runs into any API failure, there isn't much that can be done. So it is easier for the caller to handle one
    exception than many exception types.
    """

    def __init__(self, message: str):
        """
        Constructs an API exception

        :param message: String description of the issue encountered.
        """
        self.message = message if len(message) else "An unknown API issue was encountered."
        super().__init__(self.message)
