"""
:Description: Provides a base class that all Artifact Fetcher are derived from.
"""

from __future__ import annotations

from abc import ABCMeta, abstractmethod
from contextlib import AbstractContextManager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import TracebackType
from typing import Final, Optional

from conda_recipe_manager.fetcher.exceptions import FetchRequiredError

# Identifying string used to flag temp files and directories created by this module.
_ARTIFACT_FETCHER_FILE_ID: Final[str] = "crm_artifact_fetcher"


class BaseArtifactFetcher(AbstractContextManager["BaseArtifactFetcher"], metaclass=ABCMeta):
    """
    Base class for all `ArtifactFetcher` classes. An `ArtifactFetcher` provides a standard set of tools to retrieve
    bundles of source code.

    Files retrieved from any artifact fetcher are stored in a secure temporary directory. The underlying resource can
    be cleaned up manually or automatically if the artifact fetcher class is used as a context-managed resource.
    """

    def __init__(self, name: str) -> None:
        """
        Constructs a BaseArtifactFetcher.

        :param name: Identifies the artifact. Ideally, this is the package name. In multi-sourced/mirrored scenarios,
            this might be the package name combined with some identifying information.
        """
        self._name = name
        # NOTE: There is an open issue about this pylint edge case: https://github.com/pylint-dev/pylint/issues/7658
        self._temp_dir: Final[TemporaryDirectory[str]] = TemporaryDirectory(  # pylint: disable=consider-using-with
            prefix=f"{_ARTIFACT_FETCHER_FILE_ID}_", suffix=f"_{self._name}"
        )
        self._temp_dir_path: Final[Path] = Path(self._temp_dir.name)
        # Flag to track if `fetch()` has been called successfully once.
        self._successfully_fetched = False

    def cleanup(self) -> None:
        """
        Allows the caller to manually clean-up resources used by this artifact-fetching class.
        """
        self._temp_dir.cleanup()
        self._successfully_fetched = False

    def __enter__(self) -> BaseArtifactFetcher:
        """
        Allows artifact fetching classes to be context-managed with a `with` statement.

        :returns: An instance of this class.
        """
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_value: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """
        Clean-up function called when a context-managed artifact fetching class exits a `with` statement.

        :param exc_type: Type of exception that was thrown in the `with` statement, if any occurred.
        :param exc_value: Exception that was thrown in the `with` statement, if any occurred.
        :param exc_tb: Exception traceback of the exception that was thrown in the `with` statement, if any occurred.
        """
        self.cleanup()

    def _fetch_guard(self, msg: str) -> None:
        """
        Convenience function that prevents executing functions that require the code to be downloaded or stored to the
        temporary directory.

        :param msg: Message to attach to the exception.
        :raises FetchRequiredError: If `fetch()` has not been successfully invoked.
        """
        if self._successfully_fetched:
            return
        raise FetchRequiredError(msg)

    def __str__(self) -> str:
        """
        Returns a simple string identifier that identifies an ArtifactFetcher instance.

        :returns: String identifier (name) of the ArtifactFetcher.
        """
        return self._name

    def fetched(self) -> bool:
        """
        Allows the caller to know if the target resource has been successfully fetched. In some scenarios this may be
        useful to know to prevent duplicated/wasted I/O calls.

        :returns: True if this object has successfully fetched the target resource AND that resource is still available.
            False otherwise.
        """
        return self._successfully_fetched

    @abstractmethod
    def fetch(self) -> None:
        """
        Retrieves the build artifact and source code and dumps it to a secure temporary location.

        "Gretchen, stop trying to make fetch happen! It's not going to happen!" - Regina George

        :raises FetchError: When the target artifact fails to be acquired.
        """

    @abstractmethod
    def get_path_to_source_code(self) -> Path:
        """
        Returns the directory containing the artifact's bundled source code.

        :raises FetchRequiredError: If a call to `fetch()` is required before using this function.
        """

    def apply_patches(self) -> None:
        """
        TODO Flush this mechanism out. It looks like the same mechanism is used for http and git sources(?)
        """
        pass
