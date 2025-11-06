"""
:Description: Parser that is capable of comprehending Conda Build Configuration (CBC) files.
"""

from __future__ import annotations

import logging
import sys
from itertools import product
from typing import Final, cast, no_type_check

import yaml

from conda_recipe_manager.parser._node_var import NodeVar
from conda_recipe_manager.parser._types import ForceIndentDumper
from conda_recipe_manager.parser.exceptions import ZipKeysException
from conda_recipe_manager.parser.recipe_reader import RecipeReader
from conda_recipe_manager.parser.selector_query import SelectorQuery
from conda_recipe_manager.parser.types import DEFAULT_VARIANTS
from conda_recipe_manager.types import PRIMITIVES_TUPLE, JsonType, Primitives, SentinelType

# Internal variable table type
_CbcTable = dict[str, list[NodeVar]]

# Type that attempts to represent the contents of a CBC file
_CbcType = dict[str, list[JsonType] | dict[str, dict[str, str]]]

# Type that represents the values and zip_keys of a CBC file as a tuple.
CbcOutputType = tuple[dict[str, list[Primitives]], list[set[str]]]

# Special keys that are currently ignored by the CBC parser.
_SPECIAL_KEYS: Final[set[str]] = {
    "pin_run_as_build",
    "extend_keys",
    "ignore_version",
    "ignore_build_only_deps",
}

log: Final[logging.Logger] = logging.getLogger(__name__)


class CbcParser(RecipeReader):
    """
    Parses a Conda Build Configuration (CBC) file and provides querying capabilities. Often these files are named
    `conda_build_configuration.yaml` or `cbc.yaml`

    This work is based off of the `RecipeReader` class. The CBC file format happens to be similar enough to
    the recipe format (with commented selectors)
    """

    # TODO: Add V1-support for the new CBC equivalent:
    #   https://prefix-dev.github.io/rattler-build/latest/variants/

    def _construct_cbc_variable(self, path: str, value: JsonType, comments_tbl: dict[str, str]) -> NodeVar:
        """
        Constructs a CBC variable from the value and comment.

        :param path: Path to the variable.
        :param value: Value of the variable.
        :param comments_tbl: Table of comments.
        :returns: A `NodeVar` instance representing the CBC variable.
        """
        # Re-assemble the comment components. If successful, append it to the node.
        # TODO Improve: This is not very efficient.
        selector_str = "" if not self.contains_selector_at_path(path) else self.get_selector_at_path(path)
        comment_str = comments_tbl.get(path, "")
        combined_comment = f"{selector_str} {comment_str}"
        return NodeVar(value, f"# {combined_comment}" if combined_comment.strip() else None)

    def _construct_zip_keys(self, value_list: list[JsonType], comments_tbl: dict[str, str]) -> None:
        """
        Constructs the zip keys from the value list.

        :param value_list: list of JSON values to construct the zip keys from.
        :param comments_tbl: Table of comments.
        :raises ZipKeysException: If a zip keys issue occurs.
        """
        is_list_of_lists: Final[bool] = isinstance(value_list, list) and all(
            isinstance(inner_list, list) and all(isinstance(elem, str) for elem in inner_list)
            for inner_list in value_list
        )
        is_list_of_strings: Final[bool] = isinstance(value_list, list) and all(
            isinstance(elem, str) for elem in value_list
        )
        if not is_list_of_lists and not is_list_of_strings:
            raise ZipKeysException(value_list)

        if is_list_of_strings:
            list_of_strings = cast(list[str], value_list)
            node_var_list: list[NodeVar] = []
            for i, elem in enumerate(list_of_strings):
                path = f"/zip_keys/{i}"
                node_var_list.append(self._construct_cbc_variable(path, elem, comments_tbl))
            self._zip_keys.append(node_var_list)
            return

        list_of_lists = cast(list[list[str]], value_list)
        for i, inner_list in enumerate(list_of_lists):
            node_var_list: list[NodeVar] = []  # type: ignore
            for j, elem in enumerate(inner_list):
                path = f"/zip_keys/{i}/{j}"
                node_var_list.append(self._construct_cbc_variable(path, elem, comments_tbl))
            self._zip_keys.append(node_var_list)

    def __init__(self, content: str):
        """
        Constructs a CBC Parser instance from the contents of a CBC file.

        :param content: conda-build formatted configuration file, as a single text string.
        :raises SentinelTypeEvaluationException: If a node value with a sentinel type is evaluated.
        :raises ZipKeysException: If a zip keys issue occurs.
        """
        # We treat floats as strings in CBC files to preserve the original precision of version numbers.
        super().__init__(content, floats_as_strings=True)
        self._cbc_vars_tbl: _CbcTable = {}
        self._zip_keys: list[list[NodeVar]] = []

        parsed_contents: Final[_CbcType] = cast(_CbcType, self.get_value("/"))
        # NOTE: The comments table does not include selectors.
        comments_tbl: Final = self.get_comments_table()
        for variable, value_list in parsed_contents.items():
            # TODO: Handle these special keys ?
            if variable in _SPECIAL_KEYS:
                log.info("Skipping special key: %s", variable)
                continue

            # Handle single value variables
            is_single_value = isinstance(value_list, PRIMITIVES_TUPLE)
            if is_single_value:
                value_list = [cast(Primitives, value_list)]

            if not isinstance(value_list, list):
                continue

            if variable == "zip_keys":
                self._construct_zip_keys(value_list, comments_tbl)
                continue

            # TODO add V1 support for CBC files? Is there a V1 CBC format?
            for i, value in enumerate(value_list):
                path = f"/{variable}/{i}"
                if is_single_value:
                    path = f"/{variable}"
                entry = self._construct_cbc_variable(path, value, comments_tbl)

                # TODO detect duplicates
                if variable not in self._cbc_vars_tbl:
                    self._cbc_vars_tbl[variable] = [entry]
                else:
                    self._cbc_vars_tbl[variable].append(entry)

    def __contains__(self, key: object) -> bool:
        """
        Indicates if a variable is found in a CBC file.

        :param key: Target variable name to check for.
        :returns: True if the variable exists in this CBC file. False otherwise.
        """
        if not isinstance(key, str):
            return False
        return key in self._cbc_vars_tbl

    def list_cbc_variables(self) -> list[str]:
        """
        Get a list of all the available CBC variable names.

        :returns: A list containing all the variables defined in the CBC file.
        """
        return list(self._cbc_vars_tbl.keys())

    def get_cbc_variable_values(
        self, variable: str, query: SelectorQuery, default: JsonType | SentinelType = RecipeReader._sentinel
    ) -> JsonType:
        """
        Determines which value of a CBC variable is applicable to the current environment.

        :param variable: Target variable name.
        :param query: Query that represents the state of the target build environment.
        :param default: (Optional) Value to return if no variable could be found or no value could be determined.
        :raises KeyError: If the key does not exist and no default value is provided.
        :raises ValueError: If the selector query does not match any case and no default value is provided.
        :returns: Value of the variable as indicated by the selector options provided.
        """
        if variable not in self:
            if isinstance(default, SentinelType):
                raise KeyError(f"CBC variable not found: {variable}")
            return default

        selected_entries: list[JsonType] = []
        for entry in self._cbc_vars_tbl[variable]:
            selector = entry.get_selector()
            if selector is None or selector.does_selector_apply(query):
                selected_entries.append(entry.get_value())
        if selected_entries:
            return selected_entries

        # No applicable entries have been found to match any selector variant.
        if isinstance(default, SentinelType):
            raise ValueError(f"CBC variable does not have a value for the provided selector query: {variable}")
        return default

    @staticmethod
    def _validate_zip_keys(zip_keys: list[set[str]]) -> None:
        """
        Validates the zip keys.

        :param zip_keys: List of zip keys to validate.
        :raises ZipKeysException: If a zip keys issue occurs.
        """
        if not all(len(keys) > 1 for keys in zip_keys):
            raise ZipKeysException(zip_keys, "Each set of zip keys must contain at least two values")
        seen_keys: set[str] = set()
        for zip_key_set in zip_keys:
            for key in zip_key_set:
                if key in seen_keys:
                    raise ZipKeysException(zip_keys, f"Duplicate zip key found: {key}")
                seen_keys.add(key)

    def get_zip_keys(self, query: SelectorQuery) -> list[set[str]]:
        """
        Returns the zip keys from the CBC file.

        :param query: Query that represents the state of the target build environment.
        :raises KeyError: If no zip keys are found in the CBC file.
        :raises ValueError: If no zip keys are found for the provided selector query
        :raises ZipKeysException: If zip keys are invalid.
        :returns: List of zip keys.
        """

        if not self._zip_keys:
            raise KeyError("No zip keys found in the CBC file")

        zip_keys: list[set[str]] = []
        for list_of_keys in self._zip_keys:
            potential_keys: set[str] = set()
            for key in list_of_keys:
                selector = key.get_selector()
                if selector is None or selector.does_selector_apply(query):
                    potential_keys.add(key.get_value())  # type: ignore
            if potential_keys:
                zip_keys.append(potential_keys)

        if not zip_keys:
            raise ValueError("No zip keys found for the provided selector query")

        # Perform sanity check on the zip keys.
        self._validate_zip_keys(zip_keys)

        return zip_keys

    @staticmethod
    def _validate_zip_keys_against_cbc_values(
        zip_keys: list[set[str]], cbc_values: dict[str, list[Primitives]]
    ) -> None:
        """
        Validates the zip keys against the CBC values.

        :param zip_keys: List of zip keys to validate.
        :param cbc_values: Dictionary of CBC variable values.
        :raises ZipKeysException: If a zip keys issue occurs.
        """
        for zip_key_set in zip_keys:
            for key in zip_key_set:
                if key not in cbc_values:
                    raise ZipKeysException(zip_keys, f"Zip key not found in CBC values: {key}")

    @no_type_check
    @staticmethod
    def _construct_default_variants_cbc() -> CbcParser:
        """
        Constructs the default variants CBC file.

        :returns: The default variants CBC file.
        """
        default_variants = {}
        for key, value in DEFAULT_VARIANTS.items():
            if isinstance(value, Primitives):
                default_variants[key] = [value]
            else:
                default_variants[key] = value
        yaml_dump = yaml.dump(default_variants, Dumper=ForceIndentDumper, sort_keys=False, width=sys.maxsize)
        return CbcParser(yaml_dump)

    @staticmethod
    def generate_cbc_values(cbc_files: list[CbcParser], selector_query: SelectorQuery) -> CbcOutputType:
        """
        Generates a dictionary of CBC variable values from a list of CBC files.
        The values are generated for the given selector query.
        The values are clobbered if the same variable is defined in multiple CBC files, from first to last in the list.

        :param cbc_files: List of CBC files to generate the values from.
        :param selector_query: Selector query to generate the values for.
        :raises ZipKeysException: If a zip keys issue occurs.
        :returns: Tuple containing a dictionary of CBC variable values and a list of zip keys.
        """

        # Insert the default variants as the first CBC file
        default_variants_cbc = cast(CbcParser, CbcParser._construct_default_variants_cbc())
        cbc_files.insert(0, default_variants_cbc)

        cbc_values: dict[str, list[Primitives]] = {}
        zip_keys: list[set[str]] = []
        # Combine the CBC files into a single output.
        for cbc_file in cbc_files:
            try:
                zip_keys = cbc_file.get_zip_keys(selector_query)
            except (KeyError, ValueError):
                pass
            except ZipKeysException as e:
                raise e
            for variable in cbc_file.list_cbc_variables():
                try:
                    cbc_values[variable] = cast(
                        list[Primitives], cbc_file.get_cbc_variable_values(variable, selector_query)
                    )
                except ValueError:
                    continue
        # Validate that all zip keys are present in the CBC values
        CbcParser._validate_zip_keys_against_cbc_values(zip_keys, cbc_values)
        return cbc_values, zip_keys

    @no_type_check
    @staticmethod
    def generate_variants(cbc_files: list[CbcParser], selector_query: SelectorQuery) -> tuple[dict[str, JsonType]]:
        """
        Generates a tuple of variants from a list of CBC files.
        The variants are generated by combining the values of the CBC variables.

        :param cbc_files: List of CBC files to generate the variants from.
        :param selector_query: Selector query to generate the variants for.
        :raises ZipKeysException: If a zip keys issue occurs.
        :returns: Tuple of variants.
        """
        cbc_values, zip_keys = CbcParser.generate_cbc_values(cbc_files, selector_query)

        initial_keys: set[str] = set(cbc_values.keys())
        zip_keys_tuples: list[tuple[str, ...]] = []
        for zip_key_set in zip_keys:
            zip_keys_tuples.append(tuple(zip_key_set))
            initial_keys -= zip_key_set
        unzipped_keys: list[str] = list(initial_keys)

        all_keys: list[str | tuple[str, ...]] = unzipped_keys + zip_keys_tuples
        all_values: list[list[Primitives | tuple[Primitives]]] = []
        for key in unzipped_keys:
            all_values.append(cbc_values[key])
        for key_tuple in zip_keys_tuples:
            zipped_values = zip(*[cbc_values[key_elem] for key_elem in key_tuple])
            all_values.append(list(zipped_values))

        all_combinations = product(*all_values)
        list_of_variants = []
        for combo in all_combinations:
            new_variant = {}
            # Initialize with zip_keys and target_platform to match conda_build's format.
            new_variant["zip_keys"] = [list(zip_key_set) for zip_key_set in zip_keys]
            new_variant["target_platform"] = selector_query.platform
            for key, value in zip(all_keys, combo):
                if not isinstance(value, tuple):
                    new_variant[key] = value
                    continue
                for key_elem, value_elem in zip(key, value):
                    new_variant[key_elem] = value_elem
            list_of_variants.append(new_variant)
        return tuple(list_of_variants)
