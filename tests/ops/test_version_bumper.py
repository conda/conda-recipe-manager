"""
:Description: Tests to validate the `VersionBumper` class.
"""

from __future__ import annotations

from typing import Final, Optional
from unittest.mock import patch

import pytest
from pyfakefs.fake_filesystem import FakeFilesystem

from conda_recipe_manager.fetcher.artifact_fetcher import from_recipe_fetch, from_recipe_fetch_corrected
from conda_recipe_manager.ops.exceptions import VersionBumperInvalidState, VersionBumperPatchError
from conda_recipe_manager.ops.version_bumper import VersionBumper, VersionBumperOption
from conda_recipe_manager.parser.recipe_parser import RecipeParser
from conda_recipe_manager.parser.recipe_parser_deps import RecipeReaderDeps
from tests.file_loading import get_test_path, load_recipe
from tests.mock_artifact_fetch import mock_artifact_requests_get

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


def _simulate_failed_patch(_: RecipeParser) -> bool:
    """
    Simulates a failed recipe parser `patch()` call.

    :returns: False
    """
    return False


@pytest.mark.parametrize(
    "file",
    [
        ## V0 Format ##
        ("types-toml.yaml"),
        ## V1 Format ##
        ("v1_format/v1_types-toml.yaml"),
    ],
)
def test_vb_simulate_failure_on_construction(fs: FakeFilesystem, file: str) -> None:
    """
    Ensures that the recipe file is saved when a failure occurs. This one test simulates a number of failure scenarios
    in a row.

    :param fs: `pyfakefs` Fixture used to replace the file system
    :param file: Target recipe file to use.
    """
    file_path: Final = get_test_path() / file
    fs.add_real_file(file_path, read_only=False)
    with patch(
        "conda_recipe_manager.parser.recipe_parser.RecipeParser.patch", side_effect=_simulate_failed_patch
    ) as bad_patch:
        with pytest.raises(VersionBumperPatchError):
            VersionBumper(file_path, options=_VBO_SAFE_MODE)
            bad_patch.assert_called_once()


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

    with patch(
        "conda_recipe_manager.parser.recipe_parser.RecipeParser.patch", side_effect=_simulate_failed_patch
    ) as bad_patch:
        with pytest.raises(VersionBumperPatchError):
            vb.update_build_num(1)
            bad_patch.assert_called_once()
            assert_vb_n_disk_usage(vb, 5)


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

    with patch(
        "conda_recipe_manager.parser.recipe_parser.RecipeParser.patch", side_effect=_simulate_failed_patch
    ) as bad_patch:
        with pytest.raises(VersionBumperPatchError):
            vb.update_build_num(1)
            bad_patch.assert_called_once()

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
        ("types-toml.yaml", _VBO_NO_DELTA),
        ## V1 Format ##
        ("v1_format/v1_types-toml.yaml", _VBO_NONE),
        ("v1_format/v1_types-toml.yaml", _VBO_SAFE_MODE),
        ("v1_format/v1_types-toml.yaml", _VBO_NO_DELTA),
    ],
)
def test_vb_commit_changes(fs: FakeFilesystem, file: str, vbo: VersionBumperOption) -> None:
    """
    Ensures that `VersionBumper::commit_changes()` saves to the disk when it is expected to do so.

    :param fs: `pyfakefs` Fixture used to replace the file system
    :param file: Target recipe file to use.
    :param vbo: Options to pass to the `VersionBumper` instance.
    """
    file_path: Final = get_test_path() / file
    fs.add_real_file(file_path, read_only=False)
    vb: Final = VersionBumper(file_path, options=vbo)
    vb.commit_changes()
    # Whether or not the disk was written to depends on if the dry run flag is enabled.
    assert_vb_n_disk_usage(vb, 0 if vbo & VersionBumperOption.DRY_RUN_MODE else 1)


@pytest.mark.parametrize(
    ["file", "value", "expected"],
    [
        ## V0 Format ##
        ("types-toml.yaml", None, 1),
        ("types-toml.yaml", 100, 100),
        ("types-toml.yaml", 0, 0),
        ("bump_recipe/build_num_-1.yaml", None, 0),
        ("bump_recipe/build_num_-1.yaml", 1, 1),
        ("bump_recipe/build_num_-1.yaml", 0, 0),
        ("bump_recipe/build_num_42.yaml", None, 43),
        ("bump_recipe/boto_build_num_1.yaml", None, 2),
        ("bump_recipe/boto_build_num_1.yaml", 0, 0),
        ("bump_recipe/no_build_num.yaml", None, 0),
        ("bump_recipe/no_build_num.yaml", 2, 2),
        ## V1 Format ##
        ("v1_format/v1_types-toml.yaml", None, 1),
        ("v1_format/v1_types-toml.yaml", 100, 100),
    ],
)
def test_vb_update_build_num(file: str, value: Optional[int], expected: int) -> None:
    """
    Validates updating the `/build/number` field.

    :param file: Target recipe file to use.
    :param value: Value to set.
    :param expected: Expected value to be set.
    """
    vb: Final = VersionBumper(get_test_path() / file)
    vb.update_build_num(value)
    assert vb.get_recipe_reader().get_value("/build/number") == expected
    assert_vb_no_disk_usage(vb)


@pytest.mark.parametrize(
    ["file", "value"],
    [
        ("bump_recipe/no_build_key.yaml", None),
        ("bump_recipe/no_build_key.yaml", 2),
    ],
)
def test_vb_update_build_num_throws_on_missing_build(file: str, value: Optional[int]) -> None:
    """
    Verifies that `update_build_num()` throws the expected exception if the `/build` key is missing.

    :param file: Target recipe file to use.
    :param value: Value to set.
    """
    vb: Final = VersionBumper(get_test_path() / file)
    with pytest.raises(VersionBumperInvalidState):
        vb.update_build_num(value)


@pytest.mark.parametrize(
    ["file", "value", "expected"],
    [
        ## V0 Format ##
        ("types-toml.yaml", "1.2.3", "1.2.3"),
        # This file just so happens to be missing a `version` key (but has "/package").
        ("bump_recipe/no_build_key.yaml", "3.4.3", "3.4.3"),
        ## V1 Format ##
        ("v1_format/v1_types-toml.yaml", "1.2.3", "1.2.3"),
    ],
)
def test_vb_update_version(file: str, value: str, expected: str) -> None:
    """
    Validates updating the `/package/version` field.

    :param file: Target recipe file to use.
    :param value: Value to set.
    :param expected: Expected value to be set.
    """
    vb: Final = VersionBumper(get_test_path() / file)
    vb.update_version(value)
    # Checking this way ensures we evaluate the field is correct, regardless if a variable was changed or not.
    assert vb.get_recipe_reader().get_value("/package/version", sub_vars=True) == expected
    assert_vb_no_disk_usage(vb)


## Functions that require fetched source data. ##
# NOTE: These tests MUST safely use disk storage and guard against network usage.


@pytest.mark.parametrize(
    ["file", "expected"],
    [
        ## V0 Format ##
        (
            "types-toml.yaml",
            {"/source": "https://pypi.org/packages/source/{{ name[0] }}/{{ name }}/types-toml-{{ version }}.tar.gz"},
        ),
        (
            "cctools-ld64.yaml",
            {
                "/source/0": "https://opensource.apple.com/tarballs/cctools/cctools-{{ cctools_version }}.tar.gz",
                "/source/1": "https://opensource.apple.com/tarballs/ld64/ld64-{{ ld64_version }}.tar.gz",
                "/source/2": "https://opensource.apple.com/tarballs/dyld/dyld-{{ dyld_version }}.tar.gz",
                "/source/3": "http://releases.llvm.org/{{ clang_version }}/clang+llvm-{{ clang_version }}-x86_64-apple-darwin.tar.xz",  # pylint: disable=line-too-long
            },
        ),
        ## V1 Format ##
        (
            "v1_format/v1_types-toml.yaml",
            {"/source": "https://pypi.org/packages/source/${{ name[0] }}/${{ name }}/types-toml-${{ version }}.tar.gz"},
        ),
        (
            "v1_format/v1_cctools-ld64.yaml",
            {
                "/source/0": "https://opensource.apple.com/tarballs/cctools/cctools-${{ cctools_version }}.tar.gz",
                "/source/1": "https://opensource.apple.com/tarballs/ld64/ld64-${{ ld64_version }}.tar.gz",
                "/source/2": "https://opensource.apple.com/tarballs/dyld/dyld-${{ dyld_version }}.tar.gz",
                "/source/3": "http://releases.llvm.org/${{ clang_version }}/clang+llvm-${{ clang_version }}-x86_64-apple-darwin.tar.xz",  # pylint: disable=line-too-long
            },
        ),
    ],
)
def test_update_http_urls(file: str, expected: dict[str, str]) -> None:
    """
    Validates correcting source URLs found in a recipe file.

    :param file: Target recipe file to use.
    :param expected: A look-up table mapping the location of a "source" object to the new expected value.
    """
    vb: Final = VersionBumper(get_test_path() / file)

    with patch("requests.get", new=mock_artifact_requests_get):
        # Prevent `GitArtifactFetcher` instances from reaching out to the network by doing a no-op patch.
        with patch("conda_recipe_manager.fetcher.git_artifact_fetcher.GitArtifactFetcher.fetch"):
            # This function MUST be used with this test, as `from_recipe_fetch()` will never return an updated URL.
            with from_recipe_fetch_corrected(vb.get_recipe_reader(), ignore_unsupported=True) as futures_tbl:
                vb.update_http_urls(futures_tbl)

    for src_path, expected_url in expected.items():
        assert vb.get_recipe_reader().get_value(RecipeParser.append_to_path(src_path, "/url")) == expected_url
    assert_vb_no_disk_usage(vb)


@pytest.mark.parametrize(
    ["file", "expected"],
    [
        # NOTE: The mocked archive file will always return the same SHA-256 hash.
        ## V0 Format ##
        ("types-toml.yaml", {"/source": "e594f5bc141acabe4b0298d05234e80195116667edad3d6a9cd610cab36bc4e1"}),
        (
            "bump_recipe/types-toml_hash_type_var_defined_but_not_used.yaml",
            {"/source": "e594f5bc141acabe4b0298d05234e80195116667edad3d6a9cd610cab36bc4e1"},
        ),
        (
            "cctools-ld64.yaml",
            {
                "/source/0": "e594f5bc141acabe4b0298d05234e80195116667edad3d6a9cd610cab36bc4e1",
                "/source/1": "e594f5bc141acabe4b0298d05234e80195116667edad3d6a9cd610cab36bc4e1",
                "/source/2": "e594f5bc141acabe4b0298d05234e80195116667edad3d6a9cd610cab36bc4e1",
                "/source/3": "e594f5bc141acabe4b0298d05234e80195116667edad3d6a9cd610cab36bc4e1",
            },
        ),
        ## V1 Format ##
        (
            "v1_format/v1_types-toml.yaml",
            {"/source": "e594f5bc141acabe4b0298d05234e80195116667edad3d6a9cd610cab36bc4e1"},
        ),
        (
            "v1_format/v1_cctools-ld64.yaml",
            {
                "/source/0": "e594f5bc141acabe4b0298d05234e80195116667edad3d6a9cd610cab36bc4e1",
                "/source/1": "e594f5bc141acabe4b0298d05234e80195116667edad3d6a9cd610cab36bc4e1",
                "/source/2": "e594f5bc141acabe4b0298d05234e80195116667edad3d6a9cd610cab36bc4e1",
                "/source/3": "e594f5bc141acabe4b0298d05234e80195116667edad3d6a9cd610cab36bc4e1",
            },
        ),
    ],
)
def test_vb_update_sha256(file: str, expected: dict[str, str]) -> None:
    """
    Validates updating the SHA-256 hash value for applicable sources found in a recipe file.

    :param file: Target recipe file to use.
    :param expected: A look-up table mapping the location of a "source" object to the new expected value.
    """
    vb: Final = VersionBumper(get_test_path() / file)

    with patch("requests.get", new=mock_artifact_requests_get):
        # Prevent `GitArtifactFetcher` instances from reaching out to the network by doing a no-op patch.
        with patch("conda_recipe_manager.fetcher.git_artifact_fetcher.GitArtifactFetcher.fetch"):
            with from_recipe_fetch(vb.get_recipe_reader(), ignore_unsupported=True) as futures_tbl:
                vb.update_sha256(futures_tbl)

    for src_path, expected_url in expected.items():
        assert vb.get_recipe_reader().get_value(RecipeParser.append_to_path(src_path, "/sha256")) == expected_url

    assert_vb_no_disk_usage(vb)
