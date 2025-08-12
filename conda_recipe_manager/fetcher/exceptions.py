"""
:Description: Provides exceptions for fetching modules.
"""

from __future__ import annotations


class FetcherException(Exception):
    """
    Base exception for all other artifact fetching exceptions. Should not be raised directly.
    """


class FetchUnsupportedError(FetcherException):
    """
    An issue occurred because the target artifact/source format is unsupported.
    """

    def __init__(self, message: str):
        """
        Constructs a FetchUnsupportedError Exception.

        :param message: String description of the issue encountered.
        """
        self.message = message if message else "The target artifact format is unsupported."
        super().__init__(self.message)


class FetchError(FetcherException):
    """
    General exception to be thrown when there is a failure to fetch an artifact.
    """

    def __init__(self, message: str):
        """
        Constructs a FetchError Exception.

        :param message: String description of the issue encountered.
        """
        self.message = message if message else "An unknown error occurred while trying to fetch an artifact."
        super().__init__(self.message)


class FetchRequiredError(FetcherException):
    """
    This operation could not be performed because a call to `fetch()` has not yet succeeded.
    """

    def __init__(self, message: str):
        """
        Constructs a FetchRequiredError Exception.

        :param message: String description of the issue encountered.
        """
        self.message = (
            message if message else "An operation could not be completed as the artifact has not been fetched."
        )
        super().__init__(self.message)
