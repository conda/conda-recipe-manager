"""
:Description: Provides an Artifact Fetcher capable of acquiring source code from a remote git repository.
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import Final, NamedTuple, Optional

from git import Repo
from git import exc as git_exceptions

from conda_recipe_manager.fetcher.base_artifact_fetcher import BaseArtifactFetcher
from conda_recipe_manager.fetcher.exceptions import FetchError

log: Final = logging.getLogger(__name__)


class _GitTarget(NamedTuple):
    """
    Convenience structure that contains all the information to target a `git` repo at a point in time.
    """

    url: str
    branch: Optional[str] = None
    tag: Optional[str] = None
    rev: Optional[str] = None


class GitArtifactFetcher(BaseArtifactFetcher):
    """
    Artifact Fetcher capable of cloning a remote git repository.
    """

    def __init__(
        self, name: str, url: str, branch: Optional[str] = None, tag: Optional[str] = None, rev: Optional[str] = None
    ):
        """
        Constructs a `GitArtifactFetcher` instance.

        :param name: Identifies the artifact. Ideally, this is the package name. In multi-sourced/mirrored scenarios,
            this might be the package name combined with some identifying information.
        :param url: Remote or local path to the target repository
        :param branch: (Optional) Target git branch name
        :param tag: (Optional) Target git tag name
        :param rev: (Optional) Target git revision ID
        """
        super().__init__(name)

        self._is_remote = not Path(url).exists()
        self._git_target = _GitTarget(
            url=url,
            branch=branch,
            tag=tag,
            rev=rev,
        )
        # This will remain empty until it is populated by `fetch()`
        self._git_tags: Final[list[str]] = []

    def _clone(self) -> Repo:
        """
        Helper function that clones a git repository from a local or remote source.

        :raises GitError: If there was an issue cloning the target git repository.
        :raises IOError: If there is an issue with the file system.
        """
        match self._is_remote:
            case True:
                return Repo.clone_from(self._git_target.url, self._temp_dir_path)  # type: ignore[misc]
            case False:
                shutil.copytree(self._git_target.url, self._temp_dir_path)
                return Repo(self._temp_dir_path)

    def _resolve_checkout_target(self) -> Optional[str]:
        """
        Returns the appropriate target to checkout in the git repository, if available.

        :returns: If provided, returns the appropriate string to use during `git checkout`.
        """
        # In V1 recipes, branch, tag, and rev are mutually exclusive and that check should be enforced by a recipe
        # schema. In V0 recipes, we have no guarantee other than logically you cannot have more than one specified.
        # With that said, we maintain an order of operations to ensure the interpretation is deterministic. We prefer
        # tagged versions as that makes the most sense for most feedstock repositories.
        # NOTE: These checkout commands will leave the temp repo in a detached head state.\
        if self._git_target.tag is not None:
            return self._git_target.tag
        elif self._git_target.rev is not None:
            return self._git_target.rev
        elif self._git_target.branch is not None:
            return self._git_target.branch
        return None

    def fetch(self) -> None:
        """
        Retrieves source code from a remote or local git repository and stores the files in a secure temporary
        directory.

        :raises FetchError: If an issue occurred while cloning the repository.
        """
        try:
            repo: Final = self._clone()
            for t in repo.tags:
                if t.tag is not None and isinstance(t.tag.tag, str):
                    self._git_tags.append(t.tag.tag)

        except git_exceptions.GitError as e:
            raise FetchError(f"Failed to git clone from: {self._git_target.url}") from e
        except IOError as e:
            raise FetchError(f"A file system error occurred while cloning from: {self._git_target.url}") from e

        git_target: Final[Optional[str]] = self._resolve_checkout_target()
        if git_target:
            try:
                repo.git.checkout(self._git_target.branch, force=True)
            except git_exceptions.GitError as e:
                raise FetchError(f"Failed to git checkout target: {git_target}") from e

        self._successfully_fetched = True

    def get_path_to_source_code(self) -> Path:
        """
        Returns the directory containing the artifact's bundled source code.

        :raises FetchRequiredError: If a call to `fetch()` is required before using this function.
        """
        self._fetch_guard("Repository has not been cloned, so the source code is unavailable.")

        # Since we clone directly to the target temp directory, that is all we need to return. GitPython does not create
        # a folder with the name of the repository in this case.
        return self._temp_dir_path

    def get_repo_tags(self) -> list[str]:
        """
        Returns the list of `git` tags found with the target repository.

        :raises FetchRequiredError: If a call to `fetch()` is required before using this function.
        :returns: A list of tags found in the `git` repo.
        """
        self._fetch_guard("Repository has not been cloned, so the list of available `git` tags is unknown.")

        return self._git_tags

    @staticmethod
    def _version_matches_tag(version: str, tag: str) -> bool:
        """
        Check if a version string matches a tag using a comprehensive regex pattern.

        This handles major stable release tag formats (excludes pre-release versions):
          - Exact: 1.0.0
          - v-prefix: v1.0.0
          - release-prefix: release-1.0.0, release-v1.0.0
          - Build metadata: v1.0.0+build.1

        Note: Pre-release versions (e.g., v1.0.0-rc1, v1.0.0-beta.1) are excluded.

        :param version: Version string to match
        :param tag: Tag name to match against
        :returns: True if the version matches the tag
        """
        # Escape the version string for regex
        escaped_version: Final = re.escape(version.strip())

        # TODO Future: consider using a fuzzy matcher.
        # Comprehensive regex pattern that matches stable release tag formats only
        pattern: Final[str] = (
            r"^"  # Start of string
            r"(?:v|release-|release-v)?"  # Optional prefixes (non-capturing)
            r"(?P<version>" + escaped_version + r")"  # The version (captured)
            r"(?:\+.*)?"  # Optional build metadata (+build.1, etc.)
            r"$"  # End of string
        )

        return bool(re.match(pattern, tag, re.IGNORECASE))

    @staticmethod
    def match_tag_from_version(version: str, tags: list[str]) -> Optional[str]:
        """
        Attempts to match a version string to a corresponding `git` tag. These results may not be perfect.

        :param version: Version string to find the tag for
        :param tags: List of tags to check against.
        :returns: The matching tag name if found, otherwise `None`.
        """
        # NOTE: This is a linear search that performs a custom regex match.
        for tag in tags:
            if tag and GitArtifactFetcher._version_matches_tag(version, tag):
                log.debug("Found matching tag '%s' for version '%s'", tag, version)
                return tag

        log.warning("No matching tag found for version '%s'", version)
        return None
