"""
:Description: Tests to validate the `VersionBumper` class.
"""

from __future__ import annotations

from typing import Final

import pytest

from conda_recipe_manager.ops.version_bumper import VersionBumper, VersionBumperArguments, VersionBumperOption
from conda_recipe_manager.parser.recipe_parser_deps import RecipeReaderDeps
from tests.file_loading import get_test_path

## Constants ##

# Aliases for common sets of version bumper flags
_VBO_NONE: Final = VersionBumperOption.NONE
_VBO_NO_DELTA: Final = VersionBumperOption.DRY_RUN_MODE
# Tests that use `COMMIT_ON_FAILURE` must not write-back to the original test file.
_VBO_SAFE_MODE: Final = VersionBumperOption.COMMIT_ON_FAILURE
_VBO_ALL: Final = (
    VersionBumperOption.COMMIT_ON_FAILURE
    | VersionBumperOption.DRY_RUN_MODE
    | VersionBumperOption.OMIT_TRAILING_NEW_LINE
)

# Aliases for common version bumper arguments
_VBA_DEFAULT: Final = VersionBumperArguments()
_VBA_ONE_SHOT: Final = VersionBumperArguments(fetch_retry_interval=1, fetch_retry_limit=1)


## Test utility functions ##
def assert_no_disk_usage(vb: VersionBumper) -> None:
    """
    Ensures disk storage was not touched during a test.

    :param vb: `VersionBumper` instance being used in the test.
    """
    assert vb._disk_write_cntr == 0  # pylint: disable=protected-access


## Class flag tests ##
# TODO

## Class arguments tests ##
# TODO

## Member function tests ##


@pytest.mark.parametrize(
    ["file", "vba", "vbo", "expected_mod"],
    [
        ## V0 Format ##
        ("types-toml.yaml", _VBA_DEFAULT, _VBO_NONE, True),
        ("types-toml.yaml", _VBA_DEFAULT, _VBO_SAFE_MODE, True),
        ## V1 Format ##
        ("v1_format/v1_types-toml.yaml", _VBA_DEFAULT, _VBO_NONE, True),
        ("v1_format/v1_types-toml.yaml", _VBA_DEFAULT, _VBO_SAFE_MODE, True),
    ],
)
def test_get_recipe_reader(
    file: str, vba: VersionBumperArguments, vbo: VersionBumperOption, expected_mod: bool
) -> None:
    """
    Validates that the `VersionBumper()` class can provide read-only access to the underlying recipe parser instance.

    This allows the caller to look at the current state of the recipe file without committing changes.

    :param file: Target recipe file to use.
    :param vba: Arguments to pass to the `VersionBumper` instance.
    :param vbo: Options to pass to the `VersionBumper` instance.
    :param expected_mod: Boolean indicating if a modification (on construction) was expected or not.
    """
    vb: Final = VersionBumper(get_test_path() / file, bumper_args=vba, options=vbo)
    reader: Final = vb.get_recipe_reader()
    assert isinstance(reader, RecipeReaderDeps)
    # NOTE: We expect changes to be made in cases where the pre/post-processing phases cause a delta.
    assert reader.is_modified() == expected_mod
    assert_no_disk_usage(vb)


@pytest.mark.parametrize(
    ["file", "vba", "vbo"],
    [
        ## V0 Format ##
        ("types-toml.yaml", _VBA_DEFAULT, _VBO_NONE),
        ("types-toml.yaml", _VBA_DEFAULT, _VBO_SAFE_MODE),
        ## V1 Format ##
        ("v1_format/v1_types-toml.yaml", _VBA_DEFAULT, _VBO_NONE),
        ("v1_format/v1_types-toml.yaml", _VBA_DEFAULT, _VBO_SAFE_MODE),
    ],
)
def test_commit_changes_reader(file: str, vba: VersionBumperArguments, vbo: VersionBumperOption) -> None:
    """
    TODO

    :param file: Target recipe file to use.
    :param vba: Arguments to pass to the `VersionBumper` instance.
    :param vbo: Options to pass to the `VersionBumper` instance.
    """
    vb: Final = VersionBumper(get_test_path() / file, bumper_args=vba, options=vbo)
    assert_no_disk_usage(vb)


@pytest.mark.parametrize(
    ["file", "vba", "vbo"],
    [
        ## V0 Format ##
        ("types-toml.yaml", _VBA_DEFAULT, _VBO_NONE),
        ("types-toml.yaml", _VBA_DEFAULT, _VBO_SAFE_MODE),
        ## V1 Format ##
        ("v1_format/v1_types-toml.yaml", _VBA_DEFAULT, _VBO_NONE),
        ("v1_format/v1_types-toml.yaml", _VBA_DEFAULT, _VBO_SAFE_MODE),
    ],
)
def test_update_build_num_reader(file: str, vba: VersionBumperArguments, vbo: VersionBumperOption) -> None:
    """
    TODO

    :param file: Target recipe file to use.
    :param vba: Arguments to pass to the `VersionBumper` instance.
    :param vbo: Options to pass to the `VersionBumper` instance.
    """
    vb: Final = VersionBumper(get_test_path() / file, bumper_args=vba, options=vbo)
    assert_no_disk_usage(vb)


@pytest.mark.parametrize(
    ["file", "vba", "vbo"],
    [
        ## V0 Format ##
        ("types-toml.yaml", _VBA_DEFAULT, _VBO_NONE),
        ("types-toml.yaml", _VBA_DEFAULT, _VBO_SAFE_MODE),
        ## V1 Format ##
        ("v1_format/v1_types-toml.yaml", _VBA_DEFAULT, _VBO_NONE),
        ("v1_format/v1_types-toml.yaml", _VBA_DEFAULT, _VBO_SAFE_MODE),
    ],
)
def test_update_version_reader(file: str, vba: VersionBumperArguments, vbo: VersionBumperOption) -> None:
    """
    TODO

    :param file: Target recipe file to use.
    :param vba: Arguments to pass to the `VersionBumper` instance.
    :param vbo: Options to pass to the `VersionBumper` instance.
    """
    vb: Final = VersionBumper(get_test_path() / file, bumper_args=vba, options=vbo)
    assert_no_disk_usage(vb)


## Functions that require fetched source data. ##
# NOTE: These tests MUST safely use disk storage and guard against network usage.


@pytest.mark.parametrize(
    ["file", "vba", "vbo"],
    [
        ## V0 Format ##
        ("types-toml.yaml", _VBA_DEFAULT, _VBO_NONE),
        ("types-toml.yaml", _VBA_DEFAULT, _VBO_SAFE_MODE),
        ## V1 Format ##
        ("v1_format/v1_types-toml.yaml", _VBA_DEFAULT, _VBO_NONE),
        ("v1_format/v1_types-toml.yaml", _VBA_DEFAULT, _VBO_SAFE_MODE),
    ],
)
def test_update_http_urls_reader(file: str, vba: VersionBumperArguments, vbo: VersionBumperOption) -> None:
    """
    TODO

    :param file: Target recipe file to use.
    :param vba: Arguments to pass to the `VersionBumper` instance.
    :param vbo: Options to pass to the `VersionBumper` instance.
    """
    vb: Final = VersionBumper(get_test_path() / file, bumper_args=vba, options=vbo)
    assert_no_disk_usage(vb)


@pytest.mark.parametrize(
    ["file", "vba", "vbo"],
    [
        ## V0 Format ##
        ("types-toml.yaml", _VBA_DEFAULT, _VBO_NONE),
        ("types-toml.yaml", _VBA_DEFAULT, _VBO_SAFE_MODE),
        ## V1 Format ##
        ("v1_format/v1_types-toml.yaml", _VBA_DEFAULT, _VBO_NONE),
        ("v1_format/v1_types-toml.yaml", _VBA_DEFAULT, _VBO_SAFE_MODE),
    ],
)
def test_update_sha256_reader(file: str, vba: VersionBumperArguments, vbo: VersionBumperOption) -> None:
    """
    TODO

    :param file: Target recipe file to use.
    :param vba: Arguments to pass to the `VersionBumper` instance.
    :param vbo: Options to pass to the `VersionBumper` instance.
    """
    vb: Final = VersionBumper(get_test_path() / file, bumper_args=vba, options=vbo)
    assert_no_disk_usage(vb)
