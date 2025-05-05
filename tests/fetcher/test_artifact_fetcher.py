"""
:Description: Unit test file for Artifact Fetcher utilities and factory constructors.
"""

from __future__ import annotations

from typing import Final, Type

import pytest

from conda_recipe_manager.fetcher.artifact_fetcher import from_recipe
from conda_recipe_manager.fetcher.base_artifact_fetcher import BaseArtifactFetcher
from conda_recipe_manager.fetcher.exceptions import FetchUnsupportedError
from conda_recipe_manager.fetcher.git_artifact_fetcher import GitArtifactFetcher
from conda_recipe_manager.fetcher.http_artifact_fetcher import HttpArtifactFetcher
from conda_recipe_manager.parser.recipe_reader import RecipeReader
from tests.file_loading import get_test_path, load_recipe


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

    :param file: File to work against
    :param expected: Expected mapping of source paths to classes in the returned list.
    """
    request.getfixturevalue("fs").add_real_file(get_test_path() / file)  # type: ignore[misc]
    recipe = load_recipe(file, RecipeReader)

    fetcher_map: Final[dict[str, BaseArtifactFetcher]] = from_recipe(recipe, True)

    assert len(fetcher_map) == len(expected)
    for key, expected_fetcher_t in expected.items():
        assert key in fetcher_map
        assert isinstance(fetcher_map[key], expected_fetcher_t)


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

    :param file: File to work against
    """
    request.getfixturevalue("fs").add_real_file(get_test_path() / file)  # type: ignore[misc]
    recipe = load_recipe(file, RecipeReader)

    with pytest.raises(FetchUnsupportedError):
        from_recipe(recipe)


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

    :param file: File to work against
    """
    request.getfixturevalue("fs").add_real_file(get_test_path() / file)  # type: ignore[misc]
    recipe = load_recipe(file, RecipeReader)

    assert not from_recipe(recipe, True)
