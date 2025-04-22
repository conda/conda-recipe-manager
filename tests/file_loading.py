"""
:Description: Constants and utilities used for loading files/recipes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Final, Type, TypeVar, cast

from conda_recipe_manager.grapher.recipe_graph import RecipeGraph
from conda_recipe_manager.parser.cbc_parser import CbcParser
from conda_recipe_manager.parser.recipe_reader import RecipeReader
from conda_recipe_manager.parser.recipe_reader_deps import RecipeReaderDeps
from conda_recipe_manager.types import JsonType

# Private string, calculated once, containing the path to the test files.
_TEST_FILES_PATH_STR: Final[str] = f"{os.path.dirname(__file__)}/test_aux_files"

# Generic Type for recipe-parsing classes
R = TypeVar("R", bound=RecipeReader)


def get_test_path() -> Path:
    """
    Returns a path object that points to the directory containing all auxiliary testing files. We no longer store this
    value as a constant by design. We cannot guarantee the proper construction of a global constants Path variable
    in tests that use `pyfakefs`. So instead, this function aims to provide the convenience of using `pathlib` while
    simplifying the `pyfakefs` nuance.

    See this documentation for more details:
    https://pytest-pyfakefs.readthedocs.io/en/latest/troubleshooting.html#pathlib-path-objects-created-outside-of-tests


    :returns: Path object that points to where all additional test files are stored.
    """
    return Path(_TEST_FILES_PATH_STR)


def load_file(file: Path | str) -> str:
    """
    Loads a file into a single string. Assumes the file is under the `TEST_FILES_PATH` directory, which is the standard
    location for all testing files.

    :param file: Filename/relative path of the file to read
    :returns: Text from the file
    """
    return (get_test_path() / file).read_text(encoding="utf-8")


def load_recipe(file_name: Path | str, recipe_parser: Type[R]) -> R:
    """
    Convenience function that simplifies initializing a recipe parser.

    :param file_name: File name of the test recipe to load
    :returns: RecipeParser instance, based on the file
    """
    recipe: Final[str] = load_file(file_name)
    return recipe_parser(recipe)


def load_recipe_graph(recipes: list[str]) -> RecipeGraph:
    """
    Loads a series of recipe files into a graph.

    :param recipes: List of recipe test files
    :returns: RecipeParser graph consisting of the recipes provided
    """
    tbl: dict[str, RecipeReaderDeps] = {}
    failed: set[str] = set()
    for recipe in recipes:
        try:
            parser = RecipeReaderDeps(load_file(recipe))
            tbl[parser.calc_sha256()] = parser
        except Exception:  # pylint: disable=broad-exception-caught
            failed.add(recipe)

    return RecipeGraph(tbl, failed)


def load_cbc(file_name: Path | str) -> CbcParser:
    """
    Convenience function that simplifies initializing a CBC parser.

    :param file_name: File name of the test CBC file to load
    :returns: RecipeParser instance, based on the file
    """
    cbc: Final[str] = load_file(get_test_path() / "cbc_files" / file_name)
    return CbcParser(cbc)


def load_json_file(file: Path | str) -> JsonType:
    """
    Loads JSON from a test file.

    :param file_name: File name of the JSON file to load
    :returns: Parsed JSON read from the file
    """
    return cast(JsonType, json.loads(load_file(file)))
