"""
:Description: Unit test file for Artifact Fetcher utilities and factory constructors.
"""

from __future__ import annotations

import concurrent.futures as cf
from pathlib import Path
from typing import Final, Optional, Type
from unittest.mock import patch

import pytest

from conda_recipe_manager.fetcher.artifact_fetcher import (
    fetch_all_artifacts_with_retry,
    fetch_all_corrected_artifacts_with_retry,
    from_recipe,
)
from conda_recipe_manager.fetcher.base_artifact_fetcher import BaseArtifactFetcher
from conda_recipe_manager.fetcher.exceptions import FetchUnsupportedError
from conda_recipe_manager.fetcher.git_artifact_fetcher import GitArtifactFetcher
from conda_recipe_manager.fetcher.http_artifact_fetcher import HttpArtifactFetcher
from conda_recipe_manager.parser.recipe_reader import RecipeReader
from tests.file_loading import get_test_path, load_recipe
from tests.mock_artifact_fetch import mock_artifact_requests_get


def test_from_recipe_teardown() -> None:
    """
    Verifies that `from_recipe()` cleans up after itself in an expected manner.
    """
    # NOTE: This test does not use `pyfakefs`. The only files written to disk are extracted dummy test archives to
    #       temporary directories that should be cleaned up via context management.

    # This file is used as it has multiple `/source` entries.
    file: Final = "cctools-ld64.yaml"
    recipe: Final = load_recipe(file, RecipeReader)

    temp_files: list[Path] = []

    with from_recipe(recipe, ignore_unsupported=True) as fetcher_tbl:
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
    Tests that a collection of Artifact Fetchers can be derived from a parsed recipe.

    NOTE: This test ensures that the correct number and type of the derived classes is constructed. It is not up to
          this test to validate that the recipe was parsed correctly and returning the expected values from the
          `/source` path. That should be covered by recipe parsing unit tests.

    :param file: File to work against.
    :param expected: Expected mapping of source paths to classes in the returned list.
    :param request: Pytest fixture request object.
    """
    request.getfixturevalue("fs").add_real_file(get_test_path() / file)  # type: ignore[misc]
    recipe = load_recipe(file, RecipeReader)

    with from_recipe(recipe, ignore_unsupported=True) as fetcher_tbl:
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
        with from_recipe(recipe, ignore_unsupported=False):
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

    with from_recipe(recipe, ignore_unsupported=True) as fetcher_tbl:
        assert not fetcher_tbl


def test_fetch_all_artifacts_with_retry_teardown() -> None:
    """
    Verifies that `fetch_all_artifacts_with_retry()` cleans up after itself in an expected manner.
    """
    # NOTE: This test does not use `pyfakefs`. The only files written to disk are extracted dummy test archives to
    #       temporary directories that should be cleaned up via context management.

    # This file is used as it has multiple `/source` entries.
    file: Final = "cctools-ld64.yaml"
    recipe: Final = load_recipe(file, RecipeReader)

    temp_files: list[Path] = []

    # NOTE: The test file used only has HTTP artifacts.
    with patch("requests.get", new=mock_artifact_requests_get):
        with fetch_all_artifacts_with_retry(recipe, ignore_unsupported=True) as future_tbl:
            for future in cf.as_completed(future_tbl):
                fetcher, _ = future.result()
                assert fetcher.fetched()
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
def test_fetch_all_artifacts_with_retry_ignore_unsupported(
    file: str, expected: dict[str, Type[BaseArtifactFetcher]]
) -> None:
    """
    Tests that a collection of Artifact Fetchers can be derived from a parsed recipe and fetched automatically.

    NOTE: This test ensures that the correct number and type of the derived classes is constructed. It is not up to
          this test to validate that the recipe was parsed correctly and returning the expected values from the
          `/source` path. That should be covered by recipe parsing unit tests.

    :param file: File to work against.
    :param expected: Expected mapping of source paths to classes in the returned list.
    """
    # NOTE: This test does not use `pyfakefs`. The only files written to disk are extracted dummy test archives to
    #       temporary directories that should be cleaned up via context management.
    recipe: Final = load_recipe(file, RecipeReader)

    with patch("requests.get", new=mock_artifact_requests_get):
        # Prevent `GitArtifactFetcher` instances from reaching out to the network by doing a no-op patch.
        with patch("conda_recipe_manager.fetcher.git_artifact_fetcher.GitArtifactFetcher.fetch") as gaf:
            with fetch_all_artifacts_with_retry(recipe, ignore_unsupported=True) as futures_tbl:
                assert len(futures_tbl) == len(expected)
                for future in cf.as_completed(futures_tbl):
                    assert futures_tbl[future] in expected
                    expected_fetcher_t = expected[futures_tbl[future]]
                    fetcher, updated_url = future.result()
                    assert isinstance(fetcher, expected_fetcher_t)
                    # Ensure the `git` mocker is working.
                    if isinstance(fetcher, GitArtifactFetcher):
                        gaf.assert_called_once()
                    # This should always be `None` for calls to `fetch_all_artifacts_with_retry()`
                    assert updated_url is None


def test_fetch_all_corrected_artifacts_with_retry_teardown() -> None:
    """
    Verifies that `fetch_all_corrected_artifacts_with_retry()` cleans up after itself in an expected manner.
    """
    # NOTE: This test does not use `pyfakefs`. The only files written to disk are extracted dummy test archives to
    #       temporary directories that should be cleaned up via context management.

    # This file is used as it has multiple `/source` entries.
    file: Final = "cctools-ld64.yaml"
    recipe: Final = load_recipe(file, RecipeReader)

    temp_files: list[Path] = []

    # NOTE: The test file used only has HTTP artifacts.
    with patch("requests.get", new=mock_artifact_requests_get):
        with fetch_all_corrected_artifacts_with_retry(recipe, ignore_unsupported=True) as future_tbl:
            for future in cf.as_completed(future_tbl):
                fetcher, _ = future.result()
                assert fetcher.fetched()
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
        ("types-toml.yaml", {"/source": (HttpArtifactFetcher, None)}),
        ("types-toml_src_lst.yaml", {"/source/0": (HttpArtifactFetcher, None)}),
        ("multi-output.yaml", {}),
        ("git-src.yaml", {"/source": (GitArtifactFetcher, None)}),
        (
            "cctools-ld64.yaml",
            {
                "/source/0": (HttpArtifactFetcher, None),
                "/source/1": (HttpArtifactFetcher, None),
                "/source/2": (HttpArtifactFetcher, None),
                "/source/3": (HttpArtifactFetcher, None),
            },
        ),
        # Ensure the URL update happens
        (
            "bump_recipe/types-toml_fix_pypi_uppercase_url.yaml",
            {
                "/source": (
                    HttpArtifactFetcher,
                    "https://pypi.org/packages/source/t/types-toml/types-toml-0.10.8.6.tar.gz",
                )
            },
        ),
        (
            "bump_recipe/types-toml_fix_pypi_url.yaml",
            {
                "/source": (
                    HttpArtifactFetcher,
                    "https://pypi.org/packages/source/t/types-toml/types-toml-0.10.8.6.tar.gz",
                )
            },
        ),
        ## V1 Format ##
        ("v1_format/v1_types-toml.yaml", {"/source": (HttpArtifactFetcher, None)}),
        ("v1_format/v1_types-toml_src_lst.yaml", {"/source/0": (HttpArtifactFetcher, None)}),
        ("v1_format/v1_multi-output.yaml", {}),
        ("v1_format/v1_git-src.yaml", {"/source": (GitArtifactFetcher, None)}),
        (
            "v1_format/v1_cctools-ld64.yaml",
            {
                "/source/0": (HttpArtifactFetcher, None),
                "/source/1": (HttpArtifactFetcher, None),
                "/source/2": (HttpArtifactFetcher, None),
                "/source/3": (HttpArtifactFetcher, None),
            },
        ),
    ],
)
def test_fetch_all_corrected_artifacts_with_retry(
    file: str, expected: dict[str, tuple[Type[BaseArtifactFetcher], Optional[str]]]
) -> None:
    """
    Tests that a collection of Artifact Fetchers can be derived from a parsed recipe, fetched automatically, and provide
    an updated URL, if applicable.

    NOTE: This test ensures that the correct number and type of the derived classes is constructed. It is not up to
          this test to validate that the recipe was parsed correctly and returning the expected values from the
          `/source` path. That should be covered by recipe parsing unit tests.

    :param file: File to work against.
    :param expected: Expected mapping of source paths to classes in the returned list.
    """
    # NOTE: This test does not use `pyfakefs`. The only files written to disk are extracted dummy test archives to
    #       temporary directories that should be cleaned up via context management.
    recipe: Final = load_recipe(file, RecipeReader)

    with patch("requests.get", new=mock_artifact_requests_get):
        # Prevent `GitArtifactFetcher` instances from reaching out to the network by doing a no-op patch.
        with patch("conda_recipe_manager.fetcher.git_artifact_fetcher.GitArtifactFetcher.fetch") as gaf:
            # NOTE: We set the retry interval low here as we _expect_ the retry mechanism to trip on PyPI URLs that need
            #       to be corrected.
            with fetch_all_corrected_artifacts_with_retry(
                recipe, ignore_unsupported=True, retry_interval=0.01
            ) as futures_tbl:
                assert len(futures_tbl) == len(expected)
                for future in cf.as_completed(futures_tbl):
                    assert futures_tbl[future] in expected
                    expected_fetcher_t, expected_update_url = expected[futures_tbl[future]]
                    fetcher, updated_url = future.result()
                    assert isinstance(fetcher, expected_fetcher_t)
                    # Ensure the `git` mocker is working.
                    if isinstance(fetcher, GitArtifactFetcher):
                        gaf.assert_called_once()
                    # This should always be `None` for calls to `fetch_all_artifacts_with_retry()`
                    assert updated_url == expected_update_url
