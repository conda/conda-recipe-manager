"""
:Description: Provides types and utilities for managing recipe dependencies.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import NamedTuple, Optional, cast

from conda.models.match_spec import InvalidMatchSpec, MatchSpec

from conda_recipe_manager.parser._types import Regex
from conda_recipe_manager.parser.selector_parser import SelectorParser
from conda_recipe_manager.parser.types import SchemaVersion


class DependencySection(Enum):
    """
    Enumerates dependency sections found in a recipe file.
    """

    BUILD = auto()
    HOST = auto()
    RUN = auto()
    RUN_CONSTRAINTS = auto()
    # NOTE: `run_exports` was not in the `requirements/` section in the V0 format
    RUN_EXPORTS = auto()
    # NOTE:
    #   - Test dependencies are not found under the `requirements/` section, they are found under the testing section.
    #   - There are major changes to the testing section in V1.
    # TODO TEST not covered in get_all_dependencies()
    TESTS = auto()


class DependencyConflictMode(Enum):
    """
    Mode of operation to use when handling duplicate dependencies (identified by name).
    """

    # Replace the existing dependency with the incoming dependency. Append to the end if there is no duplicate.
    REPLACE = auto()
    # Ignore the incoming dependency if there is a duplicate and do not modify any existing selector. Otherwise, append
    # to the end of the list.
    IGNORE = auto()
    # Include both dependencies, always appending to the end of the list.
    USE_BOTH = auto()
    # Write over what exists at the index provided, regardless of duplicates.
    EXACT_POSITION = auto()


def dependency_section_to_str(section: DependencySection, schema: SchemaVersion) -> str:
    """
    Converts a dependency section enumeration to the equivalent string found in the recipe, based on the current
    schema.

    :param section: Target dependency section
    :param schema: Target recipe schema
    :returns: String equivalent of the recipe schema
    """
    # `match` is used here so the static analyzer can ensure all cases are covered
    match schema:
        case SchemaVersion.V0:
            match section:
                case DependencySection.BUILD:
                    return "build"
                case DependencySection.HOST:
                    return "host"
                case DependencySection.RUN:
                    return "run"
                case DependencySection.RUN_CONSTRAINTS:
                    return "run_constrained"
                case DependencySection.RUN_EXPORTS:
                    return "run_exports"
                case DependencySection.TESTS:
                    return "requires"
        case SchemaVersion.V1:
            match section:
                case DependencySection.BUILD:
                    return "build"
                case DependencySection.HOST:
                    return "host"
                case DependencySection.RUN:
                    return "run"
                case DependencySection.RUN_CONSTRAINTS:
                    return "run_constraints"
                case DependencySection.RUN_EXPORTS:
                    return "run_exports"
                case DependencySection.TESTS:
                    return "requires"


def str_to_dependency_section(s: str) -> Optional[DependencySection]:
    """
    Converts a dependency section string to a section enumeration.

    :param s: Target string to convert
    :returns: String equivalent of the recipe schema. None if the string is unrecognized.
    """
    # `match` is used here so the static analyzer can ensure all cases are covered
    match s.strip().lower():
        case "build":
            return DependencySection.BUILD
        case "host":
            return DependencySection.HOST
        case "run":
            return DependencySection.RUN
        case "run_constrained":  # V0
            return DependencySection.RUN_CONSTRAINTS
        case "run_constraints":  # V1
            return DependencySection.RUN_CONSTRAINTS
        case "run_exports":
            return DependencySection.RUN_EXPORTS
        # This is included for the sake of completeness. Realistically, test dependencies should be detected by looking
        # at the testing section, not `/requirements`.
        case "requires":
            return DependencySection.TESTS
        case _:
            return None


class DependencyVariable:
    """
    Represents a dependency that contains a JINJA variable that is unable to be resolved by the recipe's variable table.
    """

    def __init__(self, s: str):
        """
        Constructs a DependencyVariable instance.

        :param s: String to initialize the instance with.
        """
        # Using `name` allows this class to be used trivially with MatchSpec without type guards. We sanitize the name
        # for leading/trailing whitespace as a precaution.
        # TODO normalize common JINJA functions for quote usage
        self.name = s.strip()

    def __eq__(self, o: object) -> bool:
        """
        Checks to see if two objects are equivalent.

        :param o: Other instance to check.
        :returns: True if two DependencyVariable instances are equivalent. False otherwise.
        """
        if not isinstance(o, DependencyVariable):
            return False
        return self.name == o.name

    def __hash__(self) -> int:
        """
        Hashes this `DependencyVariable` instance.

        :returns: The hash value of this object.
        """
        return hash(self.name)


# Type alias for types allowed in a Dependency's `data` field.
DependencyData = MatchSpec | DependencyVariable


def dependency_data_from_str(s: str) -> DependencyData:
    """
    Constructs a `DependencyData` object from a dependency string in a recipe file.

    :param s: String to process.
    :returns: A `DependencyData` instance.
    """
    if Regex.JINJA_V0_SUB.search(s) or Regex.JINJA_V1_SUB.search(s):
        return DependencyVariable(s)

    try:
        return MatchSpec(s)
    except (ValueError, InvalidMatchSpec):
        # In an effort to be more resilient, fallback to the simpler type.
        return DependencyVariable(s)


def dependency_data_render_as_str(data: DependencyData) -> str:
    """
    Given a `DependencyData` instance, derive the original string found in the recipe.

    :param data: Target `DependencyData`
    :return s: The original (raw) string found in the recipe file.
    """
    match data:
        case MatchSpec():
            return cast(str, data.original_spec_str)
        case DependencyVariable():
            return data.name


class Dependency(NamedTuple):
    """
    Structure that contains metadata about a dependency found in the recipe. This is immutable by design.
    """

    # Owning package name
    required_by: str
    # Path in the recipe where this dependency was found
    path: str
    # Identifies what kind of dependency this is
    type: DependencySection
    # Parsed dependency. Identifies a name and version constraints
    data: DependencyData
    # The selector applied to this dependency, if applicable
    selector: Optional[SelectorParser] = None


# Maps-out dependencies found in a recipe. Maps package name -> list of parsed dependencies.
DependencyMap = dict[str, list[Dependency]]
