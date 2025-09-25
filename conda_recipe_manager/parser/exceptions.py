"""
:Description: Provides exceptions thrown by the parser.
"""

from __future__ import annotations

import json
from typing import Optional

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


class ParsingException(BaseParserException):
    """
    Exception raised when a recipe file cannot be correctly parsed. This can occur on construction of a parser class.
    """

    def __init__(self, message: Optional[str] = None) -> None:
        """
        Constructs a parser exception.

        :param message: String description of the issue encountered.
        """
        self.message = (
            message
            if message
            else "The recipe parser ran into an unexpected issue and was unable to interpret the provided Conda recipe."
        )
        super().__init__(self.message)


class ParsingJinjaException(ParsingException):
    """
    Exception raised when a recipe file cannot be correctly parsed because of unsupported JINJA statements.
    This can occur on construction of a parser class.
    """

    def __init__(self, jinja_statement: str) -> None:
        """
        Constructs a parser exception.

        :param jinja_statement: The JINJA statement that was encountered.
        """
        super().__init__(
            "The recipe parser was unable to interpret the provided Conda"
            f"recipe because of an unsupported JINJA statement: {jinja_statement}.\n"
            "Please consider reformating the recipe file to use the supported JINJA syntax:\n"
            "    - If using {% if %} statements, please consider replacing them with selectors.\n"
            "    - If using {% for %} statements, especially in testing logic, "
            "please consider using a test script instead.\n"
        )
