"""
:Description: Tests to validate the `VersionBumper` class.
"""

from __future__ import annotations

from typing import Final

import pytest
from pyfakefs.fake_filesystem import FakeFilesystem

from conda_recipe_manager.ops.version_bumper import VersionBumper, VersionBumperInvalidState, VersionBumperOption
from conda_recipe_manager.parser.recipe_parser_deps import RecipeReaderDeps
from tests.file_loading import get_test_path, load_recipe

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


## Test utility functions ##


def assert_vb_no_disk_usage(vb: VersionBumper) -> None:
    """
    Ensures disk storage was not touched during a test.

    :param vb: `VersionBumper` instance being used in the test.
    """
    assert vb._disk_write_cntr == 0  # pylint: disable=protected-access


def assert_vb_n_disk_usage(vb: VersionBumper, n: int) -> None:
    """
    Ensures disk storage WAS touched N times during a test.

    :param vb: `VersionBumper` instance being used in the test.
    :param n: How many times the disk should have been touched.
    """
    assert vb._disk_write_cntr == n  # pylint: disable=protected-access


## Class flag tests ##


@pytest.mark.parametrize(
    "file",
    [
        ## V0 Format ##
        ("types-toml.yaml"),
        ## V1 Format ##
        ("v1_format/v1_types-toml.yaml"),
    ],
)
def test_vb_simulate_failures_to_save_changes(fs: FakeFilesystem, file: str) -> None:
    """
    Ensures that the recipe file is saved when a failure occurs. This one test simulates a number of failure scenarios
    in a row.

    :param fs: `pyfakefs` Fixture used to replace the file system
    :param file: Target recipe file to use.
    """
    file_path: Final = get_test_path() / file
    fs.add_real_file(file_path, read_only=False)
    vb: Final = VersionBumper(file_path, options=_VBO_SAFE_MODE)
    with pytest.raises(VersionBumperInvalidState):
        vb.update_build_num(-42)
    assert_vb_n_disk_usage(vb, 1)

    with pytest.raises(VersionBumperInvalidState):
        vb.update_version("")
    assert_vb_n_disk_usage(vb, 2)

    with pytest.raises(VersionBumperInvalidState):
        vb.update_http_urls({})
    assert_vb_n_disk_usage(vb, 3)

    with pytest.raises(VersionBumperInvalidState):
        vb.update_sha256({})
    assert_vb_n_disk_usage(vb, 4)


@pytest.mark.parametrize(
    ["file", "vbo"],
    [
        ## V0 Format ##
        ("types-toml.yaml", _VBO_NONE),
        ("types-toml.yaml", _VBO_NO_DELTA),
        ## V1 Format ##
        ("v1_format/v1_types-toml.yaml", _VBO_NONE),
        ("v1_format/v1_types-toml.yaml", _VBO_NO_DELTA),
    ],
)
def test_vb_simulate_failures_to_not_save_changes(fs: FakeFilesystem, file: str, vbo: VersionBumperOption) -> None:
    """
    Ensures that the recipe file is NOT saved when a failure occurs. This one test simulates a number of failure
    scenarios in a row. This test can't be used with the `_VBO_SAFE_MODE` options.

    :param fs: `pyfakefs` Fixture used to replace the file system
    :param file: Target recipe file to use.
    :param vbo: Options to pass to the `VersionBumper` instance.
    """
    file_path: Final = get_test_path() / file
    fs.add_real_file(file_path, read_only=False)
    vb: Final = VersionBumper(file_path, options=vbo)
    with pytest.raises(VersionBumperInvalidState):
        vb.update_build_num(-42)

    with pytest.raises(VersionBumperInvalidState):
        vb.update_version("")

    with pytest.raises(VersionBumperInvalidState):
        vb.update_http_urls({})

    with pytest.raises(VersionBumperInvalidState):
        vb.update_sha256({})

    assert_vb_no_disk_usage(vb)


@pytest.mark.parametrize(
    ["file", "expected_file"],
    [
        ("bump_recipe/build_num_1.yaml", "bump_recipe/build_num_1_no_new_line.yaml"),
    ],
)
def test_vb_omit_new_line(fs: FakeFilesystem, file: str, expected_file: str) -> None:
    """
    Ensures that a `VersionBumper` instance can save a file without a trailing new line.

    :param fs: `pyfakefs` Fixture used to replace the file system
    :param file: Target recipe file to use.
    :param expected_file: Expected recipe file after a simulated save.
    """
    file_path: Final = get_test_path() / file
    fs.add_real_file(file_path, read_only=False)
    fs.add_real_file(get_test_path() / expected_file, read_only=True)
    vb: Final = VersionBumper(file_path, options=VersionBumperOption.OMIT_TRAILING_NEW_LINE)
    vb.commit_changes()
    assert load_recipe(file, RecipeReaderDeps) == load_recipe(expected_file, RecipeReaderDeps)


## Member function tests ##


@pytest.mark.parametrize(
    ["file", "vbo", "expected_mod"],
    [
        ## V0 Format ##
        ("types-toml.yaml", _VBO_NONE, True),
        ("types-toml.yaml", _VBO_SAFE_MODE, True),
        ## V1 Format ##
        ("v1_format/v1_types-toml.yaml", _VBO_NONE, True),
        ("v1_format/v1_types-toml.yaml", _VBO_SAFE_MODE, True),
    ],
)
def test_vb_get_recipe_reader(file: str, vbo: VersionBumperOption, expected_mod: bool) -> None:
    """
    Validates that the `VersionBumper()` class can provide read-only access to the underlying recipe parser instance.

    This allows the caller to look at the current state of the recipe file without committing changes.

    :param file: Target recipe file to use.
    :param vbo: Options to pass to the `VersionBumper` instance.
    :param expected_mod: Boolean indicating if a modification (on construction) was expected or not.
    """
    vb: Final = VersionBumper(get_test_path() / file, options=vbo)
    reader: Final = vb.get_recipe_reader()
    assert isinstance(reader, RecipeReaderDeps)
    # NOTE: We expect changes to be made in cases where the pre/post-processing phases cause a delta.
    assert reader.is_modified() == expected_mod
    assert_vb_no_disk_usage(vb)


@pytest.mark.parametrize(
    ["file", "vbo"],
    [
        ## V0 Format ##
        ("types-toml.yaml", _VBO_NONE),
        ("types-toml.yaml", _VBO_SAFE_MODE),
        ## V1 Format ##
        ("v1_format/v1_types-toml.yaml", _VBO_NONE),
        ("v1_format/v1_types-toml.yaml", _VBO_SAFE_MODE),
    ],
)
def test_vb_commit_changes_reader(file: str, vbo: VersionBumperOption) -> None:
    """
    TODO

    :param file: Target recipe file to use.
    :param vbo: Options to pass to the `VersionBumper` instance.
    """
    vb: Final = VersionBumper(get_test_path() / file, options=vbo)
    assert_vb_no_disk_usage(vb)


@pytest.mark.parametrize(
    ["file", "vbo"],
    [
        ## V0 Format ##
        ("types-toml.yaml", _VBO_NONE),
        ("types-toml.yaml", _VBO_SAFE_MODE),
        ## V1 Format ##
        ("v1_format/v1_types-toml.yaml", _VBO_NONE),
        ("v1_format/v1_types-toml.yaml", _VBO_SAFE_MODE),
    ],
)
def test_vb_update_build_num_reader(file: str, vbo: VersionBumperOption) -> None:
    """
    TODO

    :param file: Target recipe file to use.
    :param vbo: Options to pass to the `VersionBumper` instance.
    """
    vb: Final = VersionBumper(get_test_path() / file, options=vbo)
    assert_vb_no_disk_usage(vb)


@pytest.mark.parametrize(
    ["file", "vbo"],
    [
        ## V0 Format ##
        ("types-toml.yaml", _VBO_NONE),
        ("types-toml.yaml", _VBO_SAFE_MODE),
        ## V1 Format ##
        ("v1_format/v1_types-toml.yaml", _VBO_NONE),
        ("v1_format/v1_types-toml.yaml", _VBO_SAFE_MODE),
    ],
)
def test_vb_update_version_reader(file: str, vbo: VersionBumperOption) -> None:
    """
    TODO

    :param file: Target recipe file to use.
    :param vbo: Options to pass to the `VersionBumper` instance.
    """
    vb: Final = VersionBumper(get_test_path() / file, options=vbo)
    assert_vb_no_disk_usage(vb)


## Functions that require fetched source data. ##
# NOTE: These tests MUST safely use disk storage and guard against network usage.


@pytest.mark.parametrize(
    ["file", "vbo"],
    [
        ## V0 Format ##
        ("types-toml.yaml", _VBO_NONE),
        ("types-toml.yaml", _VBO_SAFE_MODE),
        ## V1 Format ##
        ("v1_format/v1_types-toml.yaml", _VBO_NONE),
        ("v1_format/v1_types-toml.yaml", _VBO_SAFE_MODE),
    ],
)
def test_update_http_urls_reader(file: str, vbo: VersionBumperOption) -> None:
    """
    TODO

    :param file: Target recipe file to use.
    :param vbo: Options to pass to the `VersionBumper` instance.
    """
    vb: Final = VersionBumper(get_test_path() / file, options=vbo)
    assert_vb_no_disk_usage(vb)


@pytest.mark.parametrize(
    ["file", "vbo"],
    [
        ## V0 Format ##
        ("types-toml.yaml", _VBO_NONE),
        ("types-toml.yaml", _VBO_SAFE_MODE),
        ## V1 Format ##
        ("v1_format/v1_types-toml.yaml", _VBO_NONE),
        ("v1_format/v1_types-toml.yaml", _VBO_SAFE_MODE),
    ],
)
def test_vb_update_sha256_reader(file: str, vbo: VersionBumperOption) -> None:
    """
    TODO

    :param file: Target recipe file to use.
    :param vbo: Options to pass to the `VersionBumper` instance.
    """
    vb: Final = VersionBumper(get_test_path() / file, options=vbo)
    assert_vb_no_disk_usage(vb)
