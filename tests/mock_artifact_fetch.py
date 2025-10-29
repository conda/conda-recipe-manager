"""
:Description: Provides tooling to mock the acquisition of remote artifacts. This is used by several tests relating to
    the artifact fetching tools.
"""

from __future__ import annotations

from typing import Final, cast

from tests.http_mocking import MockHttpJsonResponse, MockHttpResponse, MockHttpStreamResponse


def mock_artifact_requests_get(*args: tuple[str], **_: dict[str, str | int]) -> MockHttpResponse:
    """
    Mocking function for HTTP requests for remote software artifacts, used by several artifact-fetching tests.

    NOTE: The artifacts provided are not the real build artifacts. They are mocked archive files provided by as test
          data files.

    :param args: Arguments passed to the `requests.get()`
    :param _: Name-specified arguments passed to `requests.get()` (Unused)
    :returns: Mocked HTTP response object.
    """
    endpoint = cast(str, args[0])
    default_artifact_set: Final[set[str]] = {
        # types-toml.yaml, pre-version-bump values
        "https://pypi.io/packages/source/t/types-toml/types-toml-0.10.8.6.tar.gz",
        "https://pypi.org/packages/source/t/types-toml/types-toml-0.10.8.6.tar.gz",
        # types-toml.yaml
        "https://pypi.io/packages/source/t/types-toml/types-toml-0.10.8.20240310.tar.gz",
        "https://pypi.org/packages/source/t/types-toml/types-toml-0.10.8.20240310.tar.gz",
        # boto.yaml
        "https://pypi.org/packages/source/b/boto/boto-2.50.0.tar.gz",
        # huggingface_hub.yaml
        "https://pypi.io/packages/source/h/huggingface_hub/huggingface_hub-0.24.6.tar.gz",
        "https://pypi.org/packages/source/h/huggingface_hub/huggingface_hub-0.24.6.tar.gz",
        # gsm-amzn2-aarch64.yaml
        "https://graviton-rpms.s3.amazonaws.com/amzn2-core_2021_01_26/amzn2-core/gsm-1.0.13-11.amzn2.0.2.aarch64.rpm",
        (
            "https://graviton-rpms.s3.amazonaws.com/amzn2-core-source_2021_01_26/"
            "amzn2-core-source/gsm-1.0.13-11.amzn2.0.2.src.rpm"
        ),
        # pytest-pep8.yaml
        "https://pypi.io/packages/source/p/pytest-pep8/pytest-pep8-1.0.7.tar.gz",
        "https://pypi.org/packages/source/p/pytest-pep8/pytest-pep8-1.0.7.tar.gz",
        # google-cloud-cpp.yaml
        "https://github.com/googleapis/google-cloud-cpp/archive/v2.31.0.tar.gz",
        # x264
        "http://download.videolan.org/pub/videolan/x264/snapshots/x264-snapshot-20191217-2245-stable.tar.bz2",
        # curl.yaml
        "https://curl.se/download/curl-8.11.0.tar.bz2",
        # libprotobuf.yaml
        "https://github.com/protocolbuffers/protobuf/archive/v25.3/libprotobuf-v25.3.tar.gz",
        "https://github.com/google/benchmark/archive/5b7683f49e1e9223cf9927b24f6fd3d6bd82e3f8.tar.gz",
        "https://github.com/google/googletest/archive/5ec7f0c4a113e2f18ac2c6cc7df51ad6afc24081.tar.gz",
        # cctools-ld64.yaml, pre-version-bump values
        "https://opensource.apple.com/tarballs/cctools/cctools-921.tar.gz",
        "https://opensource.apple.com/tarballs/ld64/ld64-409.12.tar.gz",
        "https://opensource.apple.com/tarballs/dyld/dyld-551.4.tar.gz",
        "http://releases.llvm.org/7.0.0/clang+llvm-7.0.0-x86_64-apple-darwin.tar.xz",
    }
    # Maps mocked PyPi API requests to JSON test files containing the mocked API response.
    pypi_api_requests_map: Final[dict[str, str]] = {
        "https://pypi.org/pypi/types-toml/json": "api/pypi/get_types-toml_package.json",
        # types-toml, pre-version-bump
        "https://pypi.org/pypi/types-toml/0.10.8.6/json": "api/pypi/get_types-toml_package_version_0.10.8.6.json",  # pylint: disable=line-too-long
        # types-toml, post-version-bump
        "https://pypi.org/pypi/types-toml/0.10.8.20240310/json": "api/pypi/get_types-toml_package_version_0.10.8.20240310.json",  # pylint: disable=line-too-long
        "https://pypi.org/pypi/Types-toml/0.10.8.20240310/json": "api/pypi/get_types-toml_package_version_0.10.8.20240310.json",  # pylint: disable=line-too-long
    }
    match endpoint:
        case endpoint if endpoint in default_artifact_set:
            return MockHttpStreamResponse(200, "archive_files/dummy_project_01.tar.gz")
        case endpoint if endpoint in pypi_api_requests_map:
            return MockHttpJsonResponse(200, pypi_api_requests_map[endpoint])
        # Error cases
        case "https://pypi.io/error_500.html":
            return MockHttpStreamResponse(500, "archive_files/dummy_project_01.tar.gz")
        case _:
            # This points to an empty test file.
            return MockHttpStreamResponse(404, "null_file.txt")
