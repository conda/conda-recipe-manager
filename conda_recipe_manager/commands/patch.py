"""
:Description: CLI for patching JSON patch blobs to recipe files.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import cast

import click

from conda_recipe_manager.commands.utils.print import print_err
from conda_recipe_manager.commands.utils.types import ExitCode
from conda_recipe_manager.parser.exceptions import JsonPatchValidationException
from conda_recipe_manager.parser.recipe_parser import RecipeParser
from conda_recipe_manager.types import JsonPatchType


def _pre_patch_validate(
    json_patch_file_path: Path, recipe_file_path: Path
) -> tuple[JsonPatchType | list[JsonPatchType], RecipeParser]:
    """
    Confirm that the json patch file and recipe file can be read and that the recipe parser object is created.

    :param json_patch_file_path: path to the json file containing the patch blobs
    :param recipe_file_path: path to the target recipe file
    :returns: A tuple containing the patch blob/blobs from the json file and a RecipeParser object
    """
    try:
        contents_json = cast(JsonPatchType | list[JsonPatchType], json.loads(json_patch_file_path.read_text()))
    except json.JSONDecodeError:
        print(f"Non-JSON file provided: {json_patch_file_path}")
        sys.exit(ExitCode.JSON_ERROR)

    try:
        contents_recipe = recipe_file_path.read_text()
    except IOError:
        print_err(f"Couldn't read the given recipe file: {recipe_file_path}")
        sys.exit(ExitCode.IO_ERROR)  # untested

    try:
        recipe_parser = RecipeParser(contents_recipe)
    except Exception:  # pylint: disable=broad-except
        print_err("An error occurred while parsing the recipe file contents.")
        sys.exit(ExitCode.PARSE_EXCEPTION)  # untested

    return contents_json, recipe_parser


# TODO Improve. In order for `click` to play nice with `pyfakefs`, we set `path_type=str` and delay converting to a
# `Path` instance. This is caused by how `click` uses decorators. See these links for more detail:
# - https://pytest-pyfakefs.readthedocs.io/en/latest/troubleshooting.html#pathlib-path-objects-created-outside-of-tests
# - https://github.com/pytest-dev/pyfakefs/discussions/605
CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])
@click.command(short_help="Modify recipe files with JSON patch blobs.", context_settings=CONTEXT_SETTINGS)
@click.argument("json_patch_file_path", type=click.Path(exists=True, path_type=str))
@click.argument("recipe_file_path", type=click.Path(exists=True, path_type=str))
def patch(json_patch_file_path: str, recipe_file_path: str) -> None:
    """
    Patches recipe files with JSON patch blobs.

    JSON_PATCH_FILE_PATH: Path to the json file containing the patch blobs
    RECIPE_FILE_PATH: Path to the target recipe file
    """
    # Manually convert to a `Path` object. See note above about `pyfakefs` test issues.
    recipe_path = Path(recipe_file_path)
    contents_json, recipe_parser = _pre_patch_validate(Path(json_patch_file_path), recipe_path)

    if not isinstance(contents_json, list):
        contents_json = [contents_json]

    error_code = ExitCode.SUCCESS
    try:
        for patch_blob in contents_json:
            if not recipe_parser.patch(patch_blob):
                print_err(f"Couldn't perform the patch: {patch_blob}.")
                error_code = ExitCode.ILLEGAL_OPERATION
                break
    except JsonPatchValidationException:
        print_err("The patch provided did not follow the expected schema.")
        error_code = ExitCode.JSON_ERROR

    recipe_path.write_text(recipe_parser.render(), encoding="utf-8")
    sys.exit(error_code)
