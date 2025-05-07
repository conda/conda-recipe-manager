"""
:Description: Provides public types, type aliases, constants, and small classes used by all modules.
"""

from __future__ import annotations

from collections.abc import Hashable
from enum import StrEnum, auto
from typing import Final, TypeVar, Union

# Base types that can store value
Primitives = Union[str, int, float, bool, None]
# Same primitives, as a tuple. Used with `isinstance()`
PRIMITIVES_TUPLE: Final[tuple[type[str], type[int], type[float], type[bool], type[None]]] = (
    str,
    int,
    float,
    bool,
    type(None),
)

# Type that represents a JSON-like type
JsonType = Union[dict[str, "JsonType"], list["JsonType"], Primitives]

# A JSON object must be have string keys.
JsonObjectType = dict[str, JsonType]
# Type that represents a JSON patch payload. A patch is a JSON object, so this alias is used for readability.
JsonPatchType = JsonObjectType

# Types that build up to types used in `jsonschema`s
SchemaPrimitives = Union[str, int, bool, None]
SchemaDetails = Union[dict[str, "SchemaDetails"], list["SchemaDetails"], SchemaPrimitives]
# Type for a schema object used by the `jsonschema` library
SchemaType = dict[str, SchemaDetails]

# Generic, hashable type
H = TypeVar("H", bound=Hashable)

# Bootstraps global singleton used by `SentinelType`
_schema_type_singleton: SentinelType


class SentinelType:
    """
    A single sentinel class to be used in this project, as an alternative to `None` when `None` cannot be used.
    It is defined in a way such that SentinelType instances survive pickling and allocations in different memory
    spaces.
    """

    def __new__(cls) -> SentinelType:
        """
        Constructs a global singleton SentinelType instance, once.

        :returns: The SentinelType instance
        """
        # Credit to @dholth for suggesting this approach in PR #105.
        global _schema_type_singleton
        try:
            return _schema_type_singleton
        except NameError:
            _schema_type_singleton = super().__new__(cls)
            return _schema_type_singleton


class MessageCategory(StrEnum):
    """
    Categories to classify messages into.
    """

    EXCEPTION = auto()
    ERROR = auto()
    WARNING = auto()


class MessageTable:
    """
    Stores and tags messages that may come up during library operations. It is up to the client program to handle the
    logging of these messages. In other words, this class aims to keep logging out of the library code by providing
    an object that can track debugging information.
    """

    def __init__(self) -> None:
        """
        Constructs an empty message table
        """
        self._tbl: dict[MessageCategory, list[str]] = {}

    def add_message(self, category: MessageCategory, message: str) -> None:
        """
        Adds a message to the table

        :param category:
        :param message:
        """
        if category not in self._tbl:
            self._tbl[category] = []
        self._tbl[category].append(message)

    def get_messages(self, category: MessageCategory) -> list[str]:
        """
        Returns all the messages stored in a given category

        :param category: Category to target
        :returns: A list containing all the messages stored in a category.
        """
        if category not in self._tbl:
            return []
        return self._tbl[category]

    def get_message_count(self, category: MessageCategory) -> int:
        """
        Returns how many messages are stored in a given category

        :param category: Category to target
        :returns: A list containing all the messages stored in a category.
        """
        if category not in self._tbl:
            return 0
        return len(self._tbl[category])

    def get_totals_message(self) -> str:
        """
        Convenience function that returns a displayable count of the number of warnings and errors contained in the
        messaging object.

        :returns: A message indicating the number of errors and warnings that have been accumulated. If there are none,
            an empty string is returned.
        """
        if not self._tbl:
            return ""

        def _pluralize(n: int, s: str) -> str:
            if n == 1:
                return s
            return f"{s}s"

        num_errors: Final[int] = 0 if MessageCategory.ERROR not in self._tbl else len(self._tbl[MessageCategory.ERROR])
        errors: Final[str] = f"{num_errors} " + _pluralize(num_errors, "error")
        num_warnings: Final[int] = (
            0 if MessageCategory.WARNING not in self._tbl else len(self._tbl[MessageCategory.WARNING])
        )
        warnings: Final[str] = f"{num_warnings} " + _pluralize(num_warnings, "warning")

        return f"{errors} and {warnings} were found."

    def clear_messages(self) -> None:
        """
        Clears-out the current messages.
        """
        self._tbl.clear()
