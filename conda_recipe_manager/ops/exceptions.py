"""
:Description: Exceptions thrown by `ops` modules.
"""

from typing import Final


class VersionBumperException(Exception):
    """
    Base exception for all other Version Bumping exceptions. Should not be raised directly.
    """


class VersionBumperPatchError(VersionBumperException):
    """
    Exception to be thrown when there is a failure to edit (patch) a recipe file.
    """

    def __init__(self, message: str):
        """
        Constructs a version bumper patch exception.

        :param message: String description of the issue encountered.
        """
        self.message = message if message else "An unknown error occurred while trying to update the recipe file."
        super().__init__(self.message)


class VersionBumperInvalidState(VersionBumperException):
    """
    Exception to be thrown when the recipe file or other portion of the version-bumping process is in an illegal state.
    """

    def __init__(self, message: str):
        """
        Constructs a version bumper patch exception.

        :param message: String description of the issue encountered.
        """
        self.message = message if message else "An unknown issue arose because an illegal state was detected."
        super().__init__(self.message)
