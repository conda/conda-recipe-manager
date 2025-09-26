"""
:Description: Provides public types, type aliases, constants, and small classes used by all modules.
"""

from __future__ import annotations

from collections.abc import Hashable
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

# Primitives without `None`
PrimitivesNoNone = Union[str, int, float, bool]
# Same primitives, as a tuple. Used with `isinstance()`
PRIMITIVES_NO_NONE_TUPLE: Final[tuple[type[str], type[int], type[float], type[bool]]] = (
    str,
    int,
    float,
    bool,
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
