"""
:Description: Unit tests for the `HttpArtifactFetcher` class. NOTE: All tests in this file should use `pyfakefs` to
    prevent writing to disk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final, cast
from unittest.mock import patch

import pytest
from pyfakefs.fake_filesystem import FakeFilesystem

from conda_recipe_manager.fetcher.exceptions import FetchError, FetchRequiredError
from conda_recipe_manager.fetcher.http_artifact_fetcher import ArtifactArchiveType, HttpArtifactFetcher
from tests.file_loading import get_test_path
from tests.http_mocking import MockHttpStreamResponse


class MockUrl:
    """
    Namespace for mocked URLs
    """

    # URL base to use for "working" endpoints. Allows for easy comparisons in tests.
    URL_BASE: Final[str] = "https://this-is-a-test.anaconda.com/foo/bar/baz/"

    DUMMY_PROJECT_01_TAR_URL: Final[str] = f"{URL_BASE}dummy_project_01.tar.gz"
    DUMMY_PROJECT_01_ZIP_URL: Final[str] = f"{URL_BASE}dummy_project_01.zip"

    # Failed URL
    HTTP_500: Final[str] = f"{URL_BASE}dummy_failure.zip"


@pytest.fixture(name="http_fetcher_p01_tar")
def fixture_http_fetcher_p01_tar() -> HttpArtifactFetcher:
    """
    `HttpArtifactFetcher` test fixture for a simple tar'd project.
    """
    # NOTE: This creates a temp directory on construction. That should be safe enough for some tests to not have to
    #       worry about managing a fake filesystem.
    return HttpArtifactFetcher("dummy_project_01_tar", MockUrl.DUMMY_PROJECT_01_TAR_URL)


@pytest.fixture(name="http_fetcher_p01_zip")
def fixture_http_fetcher_p01_zip() -> HttpArtifactFetcher:
    """
    `HttpArtifactFetcher` test fixture for a simple zipped project.
    """
    # NOTE: This creates a temp directory on construction. That should be safe enough for some tests to not have to
    #       worry about managing a fake filesystem.
    return HttpArtifactFetcher("dummy_project_01_zip", MockUrl.DUMMY_PROJECT_01_ZIP_URL)


@pytest.fixture(name="http_fetcher_failure")
def fixture_http_fetcher_failure() -> HttpArtifactFetcher:
    """
    Single-instance `HttpArtifactFetcher` test fixture. This can be used for error cases that don't need multiple tests
    to be run or need to simulate a failed HTTP request.
    """
    # NOTE: This creates a temp directory on construction. That should be safe enough for some tests to not have to
    #       worry about managing a fake filesystem.
    return HttpArtifactFetcher("dummy_project_failure", MockUrl.HTTP_500)


def mock_requests_get(*args: tuple[str], **_: dict[str, str | int]) -> MockHttpStreamResponse:
    """
    Mocking function for HTTP requests made in this test file.

    :param args: Arguments passed to the `requests.get()`
    :param _: Name-specified arguments passed to `requests.get()` (Unused)
    """
    endpoint = cast(str, args[0])
    match endpoint:
        case MockUrl.DUMMY_PROJECT_01_TAR_URL:
            return MockHttpStreamResponse(200, "archive_files/dummy_project_01.tar.gz")
        case MockUrl.DUMMY_PROJECT_01_ZIP_URL:
            return MockHttpStreamResponse(200, "archive_files/dummy_project_01.zip")
        case MockUrl.HTTP_500:
            return MockHttpStreamResponse(500, "archive_files/dummy_project_01.tar.gz")
        case _:
            # TODO fix: pyfakefs does include `/dev/null` by default, but this actually points to `<temp_dir>/dev/null`
            return MockHttpStreamResponse(404, "/dev/null")


def test_context_management(request: pytest.FixtureRequest) -> None:
    """
    Smoke test to ensure that this class can be context-managed properly.

    :param request: Pytest fixture request object.
    """
    # Make the test directory accessible to the HTTP mocker
    request.getfixturevalue("fs").add_real_directory(get_test_path() / "archive_files")  # type: ignore[misc]

    with HttpArtifactFetcher("context_management_test", MockUrl.DUMMY_PROJECT_01_TAR_URL) as haf:
        assert not haf.fetched()
        with patch("requests.get", new=mock_requests_get):
            haf.fetch()
        assert haf.fetched()

    # Verify the disk space has been cleared
    assert not haf.fetched()
    assert not haf._temp_dir_path.exists()  # pylint: disable=protected-access


def test_cleanup(request: pytest.FixtureRequest) -> None:
    """
    Smoke test to ensure that this class can be cleaned-up manually.

    :param request: Pytest fixture request object.
    """
    # Make the test directory accessible to the HTTP mocker
    request.getfixturevalue("fs").add_real_directory(get_test_path() / "archive_files")  # type: ignore[misc]

    haf: Final = HttpArtifactFetcher("context_management_test", MockUrl.DUMMY_PROJECT_01_TAR_URL)
    assert not haf.fetched()
    with patch("requests.get", new=mock_requests_get):
        haf.fetch()
    assert haf.fetched()

    haf.cleanup()

    # Verify the disk space has been cleared
    assert not haf.fetched()
    assert not haf._temp_dir_path.exists()  # pylint: disable=protected-access


@pytest.mark.parametrize(
    "http_fixture,expected_archive,expected_files",
    [
        ("http_fetcher_p01_tar", "dummy_project_01.tar.gz", ["homer.py", "README.md"]),
        ("http_fetcher_p01_zip", "dummy_project_01.zip", ["homer.py", "README.md"]),
    ],
)
def test_fetch(
    http_fixture: str, expected_archive: str, expected_files: list[str], request: pytest.FixtureRequest
) -> None:
    """
    Tests fetching and extracting a software archive.

    :param http_fixture: Name of the target `HttpArtifactFetcher` test fixture
    :param expected_archive: Expected name of the archive file that is being retrieved
    :param expected_files: Expected files to be in the extracted archive
    :param request: Pytest fixture request object.
    """
    # Make the test directory accessible to the HTTP mocker
    request.getfixturevalue("fs").add_real_directory(get_test_path() / "archive_files")  # type: ignore[misc]

    http_fetcher = cast(HttpArtifactFetcher, request.getfixturevalue(http_fixture))
    with patch("requests.get", new=mock_requests_get):
        http_fetcher.fetch()

    # Validate the state of the file system. We must use the private path variable as the directory path changes on
    # every run.
    temp_dir_path: Final[Path] = http_fetcher._temp_dir_path  # pylint: disable=protected-access
    assert temp_dir_path.exists()

    assert Path(temp_dir_path / expected_archive).exists()
    for expected_file in expected_files:
        assert Path(temp_dir_path / f"extracted_{expected_archive}/{expected_file}").exists()


def test_fetch_file_io_failure(
    fs: FakeFilesystem, http_fetcher_failure: HttpArtifactFetcher  # pylint: disable=unused-argument
) -> None:
    """
    Tests that a file I/O error raises the correct exception.

    :param fs: pyfakefs fixture used to replace the file system
    :param http_fetcher_failure: HttpArtifactFetcher test fixture
    """
    # NOTE: We deliberately don't add the test file to the fake file system to force a file error.
    with pytest.raises(FetchError) as e:
        with patch("requests.get", new=mock_requests_get):
            http_fetcher_failure.fetch()

    assert str(e.value) == "A file system error occurred while fetching the archive."


def test_fetch_http_failure(fs: FakeFilesystem, http_fetcher_failure: HttpArtifactFetcher) -> None:
    """
    Tests that an HTTP error raises the correct exception.

    :param fs: pyfakefs fixture used to replace the file system
    :param http_fetcher_failure: HttpArtifactFetcher test fixture
    """
    fs.add_real_directory(get_test_path() / "archive_files")

    with pytest.raises(FetchError) as e:
        with patch("requests.get", new=mock_requests_get):
            http_fetcher_failure.fetch()

    assert str(e.value) == "An HTTP error occurred while fetching the archive."


@pytest.mark.parametrize(
    "http_fixture,expected_src",
    [
        ("http_fetcher_p01_tar", "extracted_dummy_project_01.tar.gz"),
        ("http_fetcher_p01_zip", "extracted_dummy_project_01.zip"),
    ],
)
def test_get_path_to_source_code(http_fixture: str, expected_src: str, request: pytest.FixtureRequest) -> None:
    """
    Tests getting the path to the extracted source code.

    :param http_fixture: Name of the target `HttpArtifactFetcher` test fixture.
    :param expected_src: Expected name of the extracted source directory.
    :param request: Pytest fixture request object.
    """
    # Make the test directory accessible to the HTTP mocker
    request.getfixturevalue("fs").add_real_directory(get_test_path() / "archive_files")  # type: ignore[misc]

    http_fetcher = cast(HttpArtifactFetcher, request.getfixturevalue(http_fixture))
    with patch("requests.get", new=mock_requests_get):
        http_fetcher.fetch()

    src_path: Final[Path] = http_fetcher.get_path_to_source_code()
    assert str(src_path).endswith(expected_src)
    assert src_path.exists()


def test_get_path_to_source_code_raises_no_fetch(
    http_fetcher_failure: HttpArtifactFetcher,  # pylint: disable=unused-argument
) -> None:
    """
    Ensures `get_path_to_source_code()` throws if `fetch()` has not been called.

    :param http_fetcher_failure: HttpArtifactFetcher test fixture.
    """
    with pytest.raises(FetchRequiredError):
        http_fetcher_failure.get_path_to_source_code()


@pytest.mark.parametrize(
    "http_fixture,expected_archive",
    [
        ("http_fetcher_p01_tar", "dummy_project_01.tar.gz"),
        ("http_fetcher_p01_zip", "dummy_project_01.zip"),
    ],
)
def test_get_path_to_archive(http_fixture: str, expected_archive: str, request: pytest.FixtureRequest) -> None:
    """
    Tests getting the path to the compressed archive file code.

    :param http_fixture: Name of the target `HttpArtifactFetcher` test fixture.
    :param expected_archive: Expected name of the archive file.
    :param request: Pytest fixture request object.
    """
    # Make the test directory accessible to the HTTP mocker
    request.getfixturevalue("fs").add_real_directory(get_test_path() / "archive_files")  # type: ignore[misc]

    http_fetcher = cast(HttpArtifactFetcher, request.getfixturevalue(http_fixture))
    with patch("requests.get", new=mock_requests_get):
        http_fetcher.fetch()

    archive_path: Final[Path] = http_fetcher.get_path_to_archive()
    assert archive_path.name == expected_archive
    assert archive_path.exists()


def test_get_path_to_archive_raises_no_fetch(
    http_fetcher_failure: HttpArtifactFetcher,  # pylint: disable=unused-argument
) -> None:
    """
    Ensures `get_path_to_archive()` throws if `fetch()` has not been called.

    :param http_fetcher_failure: HttpArtifactFetcher test fixture.
    """
    with pytest.raises(FetchRequiredError):
        http_fetcher_failure.get_path_to_source_code()


@pytest.mark.parametrize(
    "http_fixture,expected_hash",
    [
        ("http_fetcher_p01_tar", "e594f5bc141acabe4b0298d05234e80195116667edad3d6a9cd610cab36bc4e1"),
        ("http_fetcher_p01_zip", "7afeff0da0fdd9df4fb14d6b77bbc297e23bb1451dad4530a7241eaf95363067"),
    ],
)
def test_get_archive_sha256(http_fixture: str, expected_hash: str, request: pytest.FixtureRequest) -> None:
    """
    Tests calculating the SHA-256 hash of the downloaded archive file.

    :param http_fixture: Name of the target `HttpArtifactFetcher` test fixture.
    :param expected_hash: Expected hash of the archive file.
    :param request: Pytest fixture request object.
    """
    # Make the test directory accessible to the HTTP mocker
    request.getfixturevalue("fs").add_real_directory(get_test_path() / "archive_files")  # type: ignore[misc]

    http_fetcher = cast(HttpArtifactFetcher, request.getfixturevalue(http_fixture))
    with patch("requests.get", new=mock_requests_get):
        http_fetcher.fetch()

    assert http_fetcher.get_archive_sha256() == expected_hash


def test_get_archive_sha256_raises_no_fetch(
    http_fetcher_failure: HttpArtifactFetcher,  # pylint: disable=unused-argument
) -> None:
    """
    Ensures `get_archive_sha256()` throws if `fetch()` has not been called.

    :param http_fetcher_failure: HttpArtifactFetcher test fixture
    """
    with pytest.raises(FetchRequiredError):
        http_fetcher_failure.get_archive_sha256()


@pytest.mark.parametrize(
    "http_fixture,expected_type",
    [
        ("http_fetcher_p01_tar", ArtifactArchiveType.TARBALL),
        ("http_fetcher_p01_zip", ArtifactArchiveType.ZIP),
    ],
)
def test_get_archive_type(
    http_fixture: str, expected_type: ArtifactArchiveType, request: pytest.FixtureRequest
) -> None:
    """
    Tests getting the archive type of the downloaded archive file.

    :param http_fixture: Name of the target `HttpArtifactFetcher` test fixture
    :param expected_type: Expected type of the archive file
    :param request: Pytest fixture request object.
    """
    # Make the test directory accessible to the HTTP mocker
    request.getfixturevalue("fs").add_real_directory(get_test_path() / "archive_files")  # type: ignore[misc]

    http_fetcher = cast(HttpArtifactFetcher, request.getfixturevalue(http_fixture))
    with patch("requests.get", new=mock_requests_get):
        http_fetcher.fetch()

    assert http_fetcher.get_archive_type() == expected_type


def test_get_archive_type_raises_no_fetch(
    http_fetcher_failure: HttpArtifactFetcher,  # pylint: disable=unused-argument
) -> None:
    """
    Ensures `get_archive_type()` throws if `fetch()` has not been called.

    :param http_fetcher_failure: HttpArtifactFetcher test fixture
    """
    with pytest.raises(FetchRequiredError):
        http_fetcher_failure.get_archive_type()
