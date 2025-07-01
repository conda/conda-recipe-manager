"""
:Description: Provides an Artifact Fetcher capable of acquiring a software archive from an HTTP/HTTPS source.
"""

from __future__ import annotations

import tarfile
import zipfile
from enum import Enum, auto
from pathlib import Path
from typing import Final, Iterator, cast
from urllib.parse import urlparse

import requests

from conda_recipe_manager.fetcher.base_artifact_fetcher import BaseArtifactFetcher
from conda_recipe_manager.fetcher.exceptions import FetchError
from conda_recipe_manager.utils.cryptography.hashing import hash_file

# Default download timeout for artifacts
_DOWNLOAD_TIMEOUT: Final[int] = 5 * 60  # 5 minutes


class ArtifactArchiveType(Enum):
    """
    Enumerates the types of archive file formats that are supported.
    """

    ZIP = auto()
    # TODO determine how to do this in Python
    ZIP_7 = auto()  # 7zip
    TARBALL = auto()
    UNKNOWN = auto()  # Could not determine the artifact type


class HttpArtifactFetcher(BaseArtifactFetcher):
    """
    Artifact Fetcher capable of downloading a software archive from a remote HTTP/HTTPS source.
    """

    def __init__(self, name: str, archive_url: str):
        """
        Constructs an `HttpArtifactFetcher` instance.

        :param name: Identifies the artifact. Ideally, this is the package name. In multi-sourced/mirrored scenarios,
            this might be the package name combined with some identifying information.
        :param archive_url: URL that points to the target software archive.
        """
        super().__init__(name)
        self._archive_url = archive_url
        self._archive_type = ArtifactArchiveType.UNKNOWN

        # We use `urlparse` to extract the file path containing the archive. This can be used to get the archive's file
        # name. Many of the archive files we deal with contain the version number with period markings. We also work
        # with archives with many different file extensions. To avoid the many pitfalls here of trying to calculate the
        # "true basename" of the file, we just pre-pend `extracted_` to indicate this is the folder containing the
        # extracted archive.
        archive_file_name: Final[str] = Path(urlparse(self._archive_url).path).name
        extracted_dir_name: Final[str] = f"extracted_{archive_file_name}"

        self._archive_path: Final[Path] = self._temp_dir_path / archive_file_name
        self._uncompressed_archive_path: Final[Path] = self._temp_dir_path / extracted_dir_name

    def _extract(self) -> None:
        """
        Retrieves the build artifact and source code and dumps it to a secure temporary location.

        :raises FetchError: If an issue occurred while extracting the archive.
        """
        try:
            match self._archive_path:
                case path if tarfile.is_tarfile(path):
                    self._archive_type = ArtifactArchiveType.TARBALL
                    with tarfile.open(self._archive_path, mode="r") as tar_file:
                        # The `filter="data"` parameter guards against "the most dangerous security issues"
                        tar_file.extractall(path=self._uncompressed_archive_path, filter="data")
                case path if zipfile.is_zipfile(path):
                    self._archive_type = ArtifactArchiveType.ZIP
                    with zipfile.ZipFile(self._archive_path) as zip_file:
                        # TODO improve security checks
                        zip_file.extractall(path=self._uncompressed_archive_path)
                # TODO 7-zip support
                case _:
                    raise FetchError("The archive type could not be identified.")
        except (tarfile.TarError, zipfile.BadZipFile, ValueError) as e:
            raise FetchError("An extraction error occurred while extracting the archive.") from e
        except IOError as e:
            raise FetchError("A file system error occurred while extracting the archive.") from e

    def fetch(self) -> None:
        """
        Retrieves a software archive from a remote HTTP/HTTPS host and stores the files in a secure temporary directory.

        :raises FetchError: If an issue occurred while downloading or extracting the archive.
        """
        # Buffered download approach
        try:
            response = requests.get(str(self._archive_url), stream=True, timeout=_DOWNLOAD_TIMEOUT)
            with open(self._archive_path, "wb") as archive:
                for chunk in cast(Iterator[bytes], response.iter_content(chunk_size=1024)):
                    if not chunk:
                        break
                    archive.write(chunk)
        except requests.exceptions.RequestException as e:  # type: ignore[misc]
            raise FetchError("An HTTP error occurred while fetching the archive.") from e
        except IOError as e:
            raise FetchError("A file system error occurred while fetching the archive.") from e

        self._extract()

        # If we have not thrown at this point, we have successfully fetched the archive.
        self._successfully_fetched = True

    def get_path_to_source_code(self) -> Path:
        """
        Returns the directory containing the artifact's bundled source code.
        NOTE: If the target archive compresses top-level folder that contains the source code, this path will point to a
        directory containing that uncompressed top-level folder.

        :raises FetchRequiredError: If `fetch()` has not been successfully invoked.
        """
        self._fetch_guard("Archive has not been downloaded, so the source code is unavailable.")

        return self._uncompressed_archive_path

    def get_archive_sha256(self) -> str:
        """
        Calculates a SHA-256 hash on the downloaded software archive.

        :raises FetchRequiredError: If `fetch()` has not been successfully invoked.
        """
        self._fetch_guard("Archive has not been downloaded, so the file can't be hashed.")

        return hash_file(self._archive_path, "sha256")

    def get_archive_type(self) -> ArtifactArchiveType:
        """
        Returns the type of archive that was retrieved. This evaluation was determined by evaluating the file and not by
        the file name.

        :raises FetchRequiredError: If `fetch()` has not been successfully invoked.
        """
        self._fetch_guard("Archive has not been downloaded, so the type can't be determined.")

        return self._archive_type

    def get_archive_url(self) -> str:
        """
        Returns the URL where the archive can be found. This may be useful if the URL needs to be corrected or modified.

        :returns: The URL where the archive can be found.
        """
        return self._archive_url
