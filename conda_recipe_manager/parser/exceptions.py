"""
:Description: Provides exceptions thrown by the parser.
"""

from __future__ import annotations

import json

from conda_recipe_manager.types import JsonPatchType


class BaseParserException(Exception):
    """
    Exception raised when an unexpected issue occurred while trying to parse or manipulate a recipe file.
    """

    def __init__(self, message: str):
        """
        Constructs a generic parser exception.

        :param message: String description of the issue encountered.
        """
        self.message = message if message else "An unknown recipe-parsing issue occurred."
        super().__init__(self.message)


class IndentFormattingException(BaseParserException):
    """
    Exception raised when a recipe file cannot be formatted correctly for indentation issues.
    """

    def __init__(self, message: str):
        """
        Constructs an indent formatting exception.

        :param message: String description of the issue encountered.
        """
        self.message = message if message else "An unknown indent formatting issue occurred."
        super().__init__(self.message)

class IndentFormattingException(BaseParserException):
    """
    Exception raised when a recipe file cannot be formatted correctly for indentation issues.
    """

    def __init__(self, message: str):
        """
        Constructs an indent formatting exception.

        :param message: String description of the issue encountered.
        """
        self.message = message if message else "An unknown indent formatting issue occurred."
        super().__init__(self.message)


class JsonPatchValidationException(BaseParserException):
    """
    Indicates that the calling code has attempted to use an illegal JSON patch payload that does not meet the schema
    criteria.
    """

    def __init__(self, patch: JsonPatchType):
        """
        Constructs a JSON Patch Validation Exception

        :param op: Operation being encountered.
        """
        super().__init__(f"Invalid patch was attempted:\n{json.dumps(patch, indent=2)}")
