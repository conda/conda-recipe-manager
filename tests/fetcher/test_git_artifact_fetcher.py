"""
:Description: Unit tests for the `GitArtifactFetcher` class.

:Note:
  - All tests in this file should use `pyfakefs` to prevent writing to disk.
  - `GitPython` is incompatible with `pyfakefs` as it relies on the `git` CLI.
    Since the `GitArtifactFetcher` class is a simple wrapper around `GitPython`,
    the amount of mocking compared to the amount of lines tested makes the cost
    of developing comprehensive unit tests high compared to the value received.
  - TODO Future: develop an integration test for this class against `GitPython`
"""

from __future__ import annotations

from typing import Optional

import pytest

from conda_recipe_manager.fetcher.exceptions import FetchRequiredError
from conda_recipe_manager.fetcher.git_artifact_fetcher import GitArtifactFetcher


@pytest.fixture(name="git_fetcher_failure")
def fixture_git_fetcher_failure() -> GitArtifactFetcher:
    """
    Single-instance `GitArtifactFetcher` test fixture. This can be used for error cases that don't need multiple tests
    to be run or need to simulate a failed git command.
    """
    # NOTE: This creates a temp directory on construction. That should be safe enough for most tests to not have to
    #       worry about managing a fake filesystem.
    return GitArtifactFetcher("dummy_project_failure", "")


def test_get_path_to_source_code_raises_no_fetch(
    git_fetcher_failure: GitArtifactFetcher,
) -> None:
    """
    Ensures `get_path_to_source_code()` throws if `fetch()` has not been called.

    :param git_fetcher_failure: GitArtifactFetcher test fixture
    """
    with pytest.raises(FetchRequiredError):
        git_fetcher_failure.get_path_to_source_code()


def test_get_repo_tags_raises_no_fetch(
    git_fetcher_failure: GitArtifactFetcher,
) -> None:
    """
    Ensures `get_repo_tags()` throws if `fetch()` has not been called.

    :param git_fetcher_failure: GitArtifactFetcher test fixture
    """
    with pytest.raises(FetchRequiredError):
        git_fetcher_failure.get_repo_tags()


@pytest.mark.parametrize(
    ["version", "tags", "expected"],
    [
        ("1.2.3", [], None),
        ("1.2.3", ["1.2.4", "4.6.0"], None),
        ("1.2.3", ["1.2.4", "1.2.3", "4.6.0"], "1.2.3"),
        ("4.2", ["1.2.4", "4.6.0", "4.1"], None),
        ("4.2", ["1.2.4", "4.6.0", "4.1", "4.2"], "4.2"),
        ("v4.2", ["v1.2.4", "v4.6.0", "v4.1", "v4.2"], "v4.2"),
        ("4.2", ["v1.2.4", "v4.6.0", "v4.1", "v4.2"], "v4.2"),
        # TODO Future: `v` prefix in the input should match a tag without the pre-fix.
        # ("v4.2", ["1.2.4", "4.6.0", "4.1", "4.2"], "4.2"),
        ("4.2", ["release-1.2.4", "release-4.6.0", "release-4.1", "release-4.2"], "release-4.2"),
        ("4.2", ["release-v1.2.4", "release-v4.6.0", "release-v4.1", "release-v4.2"], "release-v4.2"),
        ("4.2", ["v1.2.4+build.1", "v4.6.0+build.42", "v4.1+build.36", "v4.2+build.10"], "v4.2+build.10"),
    ],
)
def test_match_tag_from_version(version: str, tags: list[str], expected: Optional[str]) -> None:
    """
    Attempts to match a Conda version string with tags found on a `git` repo. This attempts to handle variations
    between version strings (like including a `v` pre-fix).

    :param version: Target version.
    :param tags: List of tags to try to match against.
    :expected: Expected value to be returned by the function.
    """
    assert GitArtifactFetcher.match_tag_from_version(version, tags) == expected
