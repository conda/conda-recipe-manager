"""
:Description: Parser that is capable of comprehending Conda Build Configuration (CBC) files.
"""

from __future__ import annotations

from typing import Final, cast

from conda_recipe_manager.parser._node_var import NodeVar
from conda_recipe_manager.parser.recipe_reader import RecipeReader
from conda_recipe_manager.parser.selector_query import SelectorQuery
from conda_recipe_manager.types import JsonType, SentinelType

# Internal variable table type
_CbcTable = dict[str, list[NodeVar]]

# Type that attempts to represent the contents of a CBC file
_CbcType = dict[str, list[JsonType] | dict[str, dict[str, str]]]


class CbcParser(RecipeReader):
    """
    Parses a Conda Build Configuration (CBC) file and provides querying capabilities. Often these files are named
    `conda_build_configuration.yaml` or `cbc.yaml`

    This work is based off of the `RecipeReader` class. The CBC file format happens to be similar enough to
    the recipe format (with commented selectors)
    """

    # TODO: Add V1-support for the new CBC equivalent:
    #   https://prefix-dev.github.io/rattler-build/latest/variants/

    def __init__(self, content: str):
        """
        Constructs a CBC Parser instance from the contents of a CBC file.

        :param content: conda-build formatted configuration file, as a single text string.
        """
        super().__init__(content)
        self._cbc_vars_tbl: _CbcTable = {}
        self._zip_keys: list[list[NodeVar]] = []

        # TODO Handle special cases:
        #   - pin_run_as_build
        #   - zip_keys
        #     - python (versions)
        #     - numpy
        #     - The CBC file matches the python version and numpy version by list index
        #   - r_implementation
        # From Charles: "Compared to meta.yaml, no jinja is allowed in the cbc. Also I believe only the base subset of
        #                selectors is available (so py>=38 and py<=310 wouldn't work). To be confirmed though."

        parsed_contents: Final[_CbcType] = cast(_CbcType, self.get_value("/"))
        # NOTE: The comments table does not include selectors.
        comments_tbl: Final = self.get_comments_table()
        for variable, value_list in parsed_contents.items():
            if not isinstance(value_list, list):
                continue

            if variable == "zip_keys":
                self._construct_zip_keys(value_list, comments_tbl)
                continue

            # TODO add V1 support for CBC files? Is there a V1 CBC format?
            for i, value in enumerate(value_list):
                path = f"/{variable}/{i}"
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

    def _construct_cbc_variable(self, path: str, value: JsonType, comments_tbl: dict[str, str]) -> NodeVar:
        """
        Constructs a CBC variable from the value and comment.

        :param path: Path to the variable.
        :param value: Value of the variable.
        :param comments_tbl: Table of comments.
        """
        # Re-assemble the comment components. If successful, append it to the node.
        # TODO Improve: This is not very efficient.
        selector_str = "" if not self.contains_selector_at_path(path) else self.get_selector_at_path(path)
        comment_str = comments_tbl.get(path, "")
        combined_comment = f"{selector_str} {comment_str}"
        return NodeVar(value, f"# {combined_comment}" if combined_comment.strip() else None)

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

    def _is_multi_level_list(self, value: JsonType) -> bool:
        """
        Checks if the value is a multi-level list.
        The format is: [{"None": ["python", "numpy"]}, {"None": ["pypy", "pypy3"]}, ...]

        :param value: JSON value to check.
        :returns: True if the value is a multi-level list. False otherwise.
        """
        if not isinstance(value, list) or not all(isinstance(elem, dict) for elem in value):
            return False
        for dict_elem in value:
            dict_elem = cast(dict[str, JsonType], dict_elem)
            if len(dict_elem) != 1:
                return False
            if "None" not in dict_elem:
                return False
            if not isinstance(dict_elem["None"], list) or not all(isinstance(elem, str) for elem in dict_elem["None"]):
                return False
        return True

    def _construct_zip_keys(self, value_list: list[JsonType], comments_tbl: dict[str, str]) -> None:
        """
        Constructs the zip keys from the value list.

        :param value_list: list of JSON values to construct the zip keys from.
        :param comments_tbl: Table of comments.
        """
        is_multi_level_list: Final[bool] = self._is_multi_level_list(value_list)
        is_list_of_strings: Final[bool] = isinstance(value_list, list) and all(
            isinstance(elem, str) for elem in value_list
        )
        if not is_multi_level_list and not is_list_of_strings:
            return

        list_of_strings = cast(list[str], value_list)
        if is_list_of_strings:
            node_var_list: list[NodeVar] = []
            for i, elem in enumerate(list_of_strings):
                path = f"/zip_keys/{i}"
                node_var_list.append(self._construct_cbc_variable(path, elem, comments_tbl))
            self._zip_keys.append(node_var_list)
            return

        multi_level_list = cast(list[dict[str, list[str]]], value_list)
        for i, inner_dict in enumerate(multi_level_list):
            inner_list = inner_dict["None"]
            node_var_list: list[NodeVar] = []  # type: ignore
            for j, elem in enumerate(inner_list):
                path = f"/zip_keys/{i}/{j}"
                node_var_list.append(self._construct_cbc_variable(path, elem, comments_tbl))
            self._zip_keys.append(node_var_list)

    def get_zip_keys(self, query: SelectorQuery) -> list[set[str]]:
        """
        Returns the zip keys from the CBC file.

        :param query: Query that represents the state of the target build environment.
        :returns: List of zip keys.
        """
        zip_keys: list[set[str]] = []
        for list_of_keys in self._zip_keys:
            potential_keys: set[str] = set()
            for key in list_of_keys:
                selector = key.get_selector()
                if selector is None or selector.does_selector_apply(query):
                    potential_keys.add(key.get_value())  # type: ignore
            if potential_keys:
                zip_keys.append(potential_keys)
        return zip_keys
