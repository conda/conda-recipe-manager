"""
:Description: Provides public types, type aliases, constants, and small classes used by the parser.
"""

from __future__ import annotations

import re
import sys
from enum import Flag, StrEnum, auto
from typing import Final

from conda_recipe_manager.parser.enums import SchemaVersion
from conda_recipe_manager.types import JsonType, Primitives, SchemaType

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

# Definition of opposite operations to compute skip selectors from python version pinnings
OPPOSITE_OPS: Final[list[tuple[str, str]]] = [
    (">=", "<"),
    (">", "<="),
]

# Python skip selector regex
PYTHON_SKIP_PATTERN: Final[re.Pattern[str]] = re.compile(r"py[ \t]*([~!<>=]=|>|<)[ \t]*\d\d+")


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


# NOTE: This is a copy of the default variants from conda-build.
DEFAULT_VARIANTS: Final[dict[str, JsonType]] = {
    "python": f"{sys.version_info.major}.{sys.version_info.minor}",
    "numpy": {
        # (python): numpy_version,  # range of versions built for given python
        (3, 8): "1.22",  # 1.19-1.24
        (3, 9): "1.22",  # 1.19-1.26
        (3, 10): "1.22",  # 1.21-1.26
        (3, 11): "1.23",  # 1.23-1.26
        (3, 12): "1.26",  # 1.26-
    }.get(
        sys.version_info[:2], "1.26"  # type: ignore[misc]
    ),
    # this one actually needs to be pretty specific.  The reason is that cpan skeleton uses the
    #    version to say what's in their standard library.
    "perl": "5.26.2",
    "lua": "5",
    "r_base": "3.4" if sys.platform == "win32" else "3.5",
    "cpu_optimization_target": "nocona",
    "pin_run_as_build": {
        "python": {"min_pin": "x.x", "max_pin": "x.x"},
        "r-base": {"min_pin": "x.x", "max_pin": "x.x"},
    },
    "ignore_version": [],
    "ignore_build_only_deps": ["python", "numpy"],
    "extend_keys": [
        "pin_run_as_build",
        "ignore_version",
        "ignore_build_only_deps",
        "extend_keys",
    ],
    "cran_mirror": "https://cran.r-project.org",
}


# Flags for the recipe reader
class RecipeReaderFlags(Flag):
    """
    Flags for controlling the behavior of the recipe reader.
    NONE: No flags are set.
    FORCE_REMOVE_JINJA: Whether to force remove unsupported JINJA statements from the recipe file.
        If this is set to True,
            then unsupported JINJA statements will silently be removed from the recipe file.
        If this is set to False,
            then unsupported JINJA statements will trigger a ParsingJinjaException.
    FLOATS_AS_STRINGS: Whether to treat floats as strings. If this is set to True,
        then floats will be treated as strings during parsing.
    """

    NONE = 0
    FORCE_REMOVE_JINJA = auto()
    FLOATS_AS_STRINGS = auto()
