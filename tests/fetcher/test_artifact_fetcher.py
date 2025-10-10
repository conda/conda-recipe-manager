"""
:Description: Unit test file for Artifact Fetcher utilities and factory constructors.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final, Type

import pytest
from pyfakefs.fake_filesystem import FakeFilesystem

from conda_recipe_manager.fetcher.artifact_fetcher import from_recipe
from conda_recipe_manager.fetcher.base_artifact_fetcher import BaseArtifactFetcher
from conda_recipe_manager.fetcher.exceptions import FetchUnsupportedError
from conda_recipe_manager.fetcher.git_artifact_fetcher import GitArtifactFetcher
from conda_recipe_manager.fetcher.http_artifact_fetcher import HttpArtifactFetcher
from conda_recipe_manager.parser.recipe_reader import RecipeReader
from tests.file_loading import get_test_path, load_recipe


def test_from_recipe_teardown(fs: FakeFilesystem) -> None:
    """
    Verifies that `from_recipe()` cleans up after itself in an expected manner.

    :param fs: `pyfakefs` Fixture used to replace the file system
    """
    # This file is used as it has multiple `/source` entries.
    file: Final = "cctools-ld64.yaml"
    fs.add_real_file(get_test_path() / file)
    recipe = load_recipe(file, RecipeReader)

    temp_files: list[Path] = []

    with from_recipe(recipe, True) as fetcher_tbl:
        for _, fetcher in fetcher_tbl.items():
            assert not fetcher.fetched()
            assert fetcher._temp_dir_path.exists()  # pylint: disable=protected-access
            temp_files.append(fetcher._temp_dir_path)  # pylint: disable=protected-access

    # This either verifies the context was managed correctly OR we got really really lucky with the garbage collector.
    # Though some print-line debugging appears to confirm that all `__exit__()` calls will occur as soon as the `with`
    # block has been exited.
    for temp_file in temp_files:
        assert not temp_file.exists()


@pytest.mark.parametrize(
    "file,expected",
    [
        ## V0 Format ##
        ("types-toml.yaml", {"/source": HttpArtifactFetcher}),
        ("types-toml_src_lst.yaml", {"/source/0": HttpArtifactFetcher}),
        ("multi-output.yaml", {}),
        ("git-src.yaml", {"/source": GitArtifactFetcher}),
        (
            "cctools-ld64.yaml",
            {
                "/source/0": HttpArtifactFetcher,
                "/source/1": HttpArtifactFetcher,
                "/source/2": HttpArtifactFetcher,
                "/source/3": HttpArtifactFetcher,
            },
        ),
        ## V1 Format ##
        ("v1_format/v1_types-toml.yaml", {"/source": HttpArtifactFetcher}),
        ("v1_format/v1_types-toml_src_lst.yaml", {"/source/0": HttpArtifactFetcher}),
        ("v1_format/v1_multi-output.yaml", {}),
        ("v1_format/v1_git-src.yaml", {"/source": GitArtifactFetcher}),
        (
            "v1_format/v1_cctools-ld64.yaml",
            {
                "/source/0": HttpArtifactFetcher,
                "/source/1": HttpArtifactFetcher,
                "/source/2": HttpArtifactFetcher,
                "/source/3": HttpArtifactFetcher,
            },
        ),
    ],
)
def test_from_recipe_ignore_unsupported(
    file: str, expected: dict[str, Type[BaseArtifactFetcher]], request: pytest.FixtureRequest
) -> None:
    """
    Tests that a list of Artifact Fetchers can be derived from a parsed recipe.

    NOTE: This test ensures that the correct number and type of the derived classes is constructed. It is not up to
          this test to validate that the recipe was parsed correctly and returning the expected values from the
          `/source` path. That should be covered by recipe parsing unit tests.

    :param file: File to work against.
    :param expected: Expected mapping of source paths to classes in the returned list.
    :param request: Pytest fixture request object.
    """
    request.getfixturevalue("fs").add_real_file(get_test_path() / file)  # type: ignore[misc]
    recipe = load_recipe(file, RecipeReader)

    with from_recipe(recipe, True) as fetcher_tbl:
        assert len(fetcher_tbl) == len(expected)
        for key, expected_fetcher_t in expected.items():
            assert key in fetcher_tbl
            assert isinstance(fetcher_tbl[key], expected_fetcher_t)


@pytest.mark.parametrize(
    "file",
    [
        ## V0 Format ##
        "fake_source.yaml",
        ## V1 Format ##
        "v1_format/v1_fake_source.yaml",
    ],
)
def test_from_recipe_throws_on_unsupported(file: str, request: pytest.FixtureRequest) -> None:
    """
    Ensures that `from_recipe()` emits the expected exception in the event that a source section cannot be parsed.

    :param file: File to work against.
    :param request: Pytest fixture request object.
    """
    request.getfixturevalue("fs").add_real_file(get_test_path() / file)  # type: ignore[misc]
    recipe = load_recipe(file, RecipeReader)

    with pytest.raises(FetchUnsupportedError):
        with from_recipe(recipe):
            pass


@pytest.mark.parametrize(
    "file",
    [
        ## V0 Format ##
        "fake_source.yaml",
        ## V1 Format ##
        "v1_format/v1_fake_source.yaml",
    ],
)
def test_from_recipe_does_not_throw_on_ignore_unsupported(file: str, request: pytest.FixtureRequest) -> None:
    """
    Ensures that `from_recipe()` DOES NOT emit an exception in the event that a source section cannot be parsed AND the
    `ignore_unsupported` flag is set.

    :param file: File to work against.
    :param request: Pytest fixture request object.
    """
    request.getfixturevalue("fs").add_real_file(get_test_path() / file)  # type: ignore[misc]
    recipe = load_recipe(file, RecipeReader)

    with from_recipe(recipe, True) as fetcher_tbl:
        assert not fetcher_tbl
