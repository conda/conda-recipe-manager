"""
:Description: Provides public types, type aliases, constants, and small classes used by the parser.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from conda_recipe_manager.parser.enums import SchemaVersion
from conda_recipe_manager.types import Primitives, SchemaType

#### Types ####

# Nodes can store a single value or a list of strings (for multiline-string nodes)
NodeValue = Primitives | list[str]


#### Constants ####

# The "new" recipe format introduces the concept of a schema version. Presumably the "old" recipe format would be
# considered "0". When converting to the V1 format, we'll use this constant value.
CURRENT_RECIPE_SCHEMA_FORMAT: Final[int] = SchemaVersion.V1.value

# Pre-CEP-13 name of the recipe file
V0_FORMAT_RECIPE_FILE_NAME: Final[str] = "meta.yaml"
# Required file name for the recipe, specified in CEP-13
V1_FORMAT_RECIPE_FILE_NAME: Final[str] = "recipe.yaml"

# Indicates how many spaces are in a level of indentation
TAB_SPACE_COUNT: Final[int] = 2
TAB_AS_SPACES: Final[str] = " " * TAB_SPACE_COUNT

# Schema validator for JSON patching
JSON_PATCH_SCHEMA: Final[SchemaType] = {
    "type": "object",
    "properties": {
        "op": {"enum": ["add", "remove", "replace", "move", "copy", "test"]},
        "path": {"type": "string", "minLength": 1},
        "from": {"type": "string"},
        "value": {
            "type": [
                "string",
                "number",
                "object",
                "array",
                "boolean",
                "null",
            ],
            "items": {
                "type": [
                    "string",
                    "number",
                    "object",
                    "array",
                    "boolean",
                    "null",
                ]
            },
        },
    },
    "required": [
        "op",
        "path",
    ],
    "allOf": [
        # `value` is required for `add`/`replace`/`test`
        {
            "if": {
                "properties": {"op": {"const": "add"}},
            },
            "then": {"required": ["value"]},
        },
        {
            "if": {
                "properties": {"op": {"const": "replace"}},
            },
            "then": {"required": ["value"]},
        },
        {
            "if": {
                "properties": {"op": {"const": "test"}},
            },
            "then": {"required": ["value"]},
        },
        # `from` is required for `move`/`copy`
        {
            "if": {
                "properties": {"op": {"const": "move"}},
            },
            "then": {"required": ["from"]},
        },
        {
            "if": {
                "properties": {"op": {"const": "copy"}},
            },
            "then": {"required": ["from"]},
        },
    ],
    "additionalProperties": False,
}


class MultilineVariant(StrEnum):
    """
    Captures which "multiline" descriptor was used on a Node, if one was used at all.

    See this guide for details on the YAML spec:
      https://stackoverflow.com/questions/3790454/how-do-i-break-a-string-in-yaml-over-multiple-lines/21699210
    """

    NONE = ""
    PIPE = "|"
    PIPE_PLUS = "|+"
    PIPE_MINUS = "|-"
    R_ANGLE = ">"
    R_ANGLE_PLUS = ">+"
    R_ANGLE_MINUS = ">-"
    L_ANGLE = "<"
    L_ANGLE_PLUS = "<+"
    L_ANGLE_MINUS = "<-"
    # This variant works differently. The starting line must begin with a " and end with a \. Every subsequent line
    # then must start with a \ until an unescaped-closing-" is found.
    BACKSLASH_QUOTE = "\\"
