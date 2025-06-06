"""
:Description: Tests the hashing utility module.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable

import pytest

from conda_recipe_manager.utils.cryptography.hashing import (
    hash_file,
    hash_str,
    is_valid_hex,
    is_valid_md5,
    is_valid_sha1,
    is_valid_sha256,
)
from tests.file_loading import get_test_path, load_file


@pytest.mark.parametrize(
    "file,algo,expected",
    [
        ("types-toml.yaml", "sha256", "e117d210da9ea6507fdea856ee96407265aec40cbc58432aa6e1c7e31998a686"),
        ("types-toml.yaml", hashlib.sha256, "e117d210da9ea6507fdea856ee96407265aec40cbc58432aa6e1c7e31998a686"),
        (
            "types-toml.yaml",
            "sha512",
            "0055bcbefb34695caa35e487cdd4e94340ff08db19a3de45a0fb79a270b2cc1f5183b8ebbca018a747e3b3a6fb8ce2a70d090f8510de4712bb24645202d75b36",  # pylint: disable=line-too-long
        ),
    ],
)
def test_hash_file(file: str, algo: str | Callable[[], hashlib._Hash], expected: str) -> None:
    """
    Validates calculating a file's hash with a given algorithm.

    :param file: Target file
    :param algo: Target algorithm
    :param expected: Expected value to return
    """
    assert hash_file(get_test_path() / file, algo) == expected


@pytest.mark.parametrize(
    "s,algo,expected",
    [
        ("quick brown fox", hashlib.sha256, "8700be3b2fe64bd5f36be0b194f838c3aa475cbee660601f5acf19c99498d264"),
        (
            "foo bar baz",
            hashlib.sha512,
            "bce50343a56f01dc7cf2d4c82127be4fff3a83ddb8b783b1a28fb6574637ceb71ef594b1f03a8e9b7d754341831292bcad1a3cb8a12fd2ded7a57b1b173b3bf7",  # pylint: disable=line-too-long
        ),
    ],
)
def test_hash_str(s: str, algo: Callable[[bytes], hashlib._Hash], expected: str) -> None:
    """
    Validates calculating a strings's hash with a given algorithm. This tests large strings, so we read from test files.

    :param s: Target string
    :param algo: Target algorithm
    :param expected: Expected value to return
    """

    assert hash_str(s, algo) == expected


@pytest.mark.parametrize(
    "file,algo,expected",
    [
        ("types-toml.yaml", hashlib.sha256, "e117d210da9ea6507fdea856ee96407265aec40cbc58432aa6e1c7e31998a686"),
        (
            "types-toml.yaml",
            hashlib.sha512,
            "0055bcbefb34695caa35e487cdd4e94340ff08db19a3de45a0fb79a270b2cc1f5183b8ebbca018a747e3b3a6fb8ce2a70d090f8510de4712bb24645202d75b36",  # pylint: disable=line-too-long
        ),
    ],
)
def test_hash_str_from_file(file: str, algo: Callable[[bytes], hashlib._Hash], expected: str) -> None:
    """
    Validates calculating a strings's hash with a given algorithm. This tests large strings, so we read from test files.

    :param file: Target file (that the string is read from)
    :param algo: Target algorithm
    :param expected: Expected value to return
    """

    assert hash_str(load_file(file), algo) == expected


@pytest.mark.parametrize(
    "s,expected",
    [
        # Valid strings of various lengths pass
        ("044af71389ac2ad3d3ece24d0baf4c07", True),
        ("044AF71389AC2AD3D3ECE24D0BAF4C07", True),
        ("8dbd20507a8edbc05bd0cbc92ee4d5aba718415f4d1be289fa598cc2077b6243", True),
        ("42", True),
        ("0042", True),
        # Invalid strings fail
        ("044af71389ac2aq3d3ece24d0baf4c07", False),
        ("foobar", False),
        ("00:42", False),
    ],
)
def test_is_valid_hex(s: str, expected: bool) -> None:
    """
    Validates `is_valid_hex()` convenience function.
    """
    assert is_valid_hex(s) == expected


@pytest.mark.parametrize(
    "s,expected",
    [
        # Valid strings
        ("044af71389ac2ad3d3ece24d0baf4c07", True),
        ("044AF71389AC2AD3D3ECE24D0BAF4C07", True),
        # Invalid strings
        ("044af71389ac2aq3d3ece24d0baf4c07", False),
        ("044af71389ac2ad3d3ece24d0baf4c07a", False),
        ("044af71389ac2add3ece24d0baf4c07", False),
    ],
)
def test_is_valid_md5(s: str, expected: bool) -> None:
    """
    Validates `is_valid_md5()` convenience function.

    :param s: String to check against.
    :param expected: Expected result of the target function.
    """
    assert is_valid_md5(s) == expected


@pytest.mark.parametrize(
    "s,expected",
    [
        # Valid strings
        ("8dbd20507a8edbc05bd0cbc92ee4d5aba718415f4d1be289fa598cc2077b6243", True),
        ("8DBD20507A8EDBC05BD0CBC92EE4D5ABA718415F4D1BE289FA598CC2077B6243", True),
        # Invalid strings
        ("8dbd20507a8edbc05bd0cbc92ee4d5aba7184l5f4d1be289fa598cc2077b6243", False),
        ("8dbd20507a8edbc05bd0cbc92ee4d5aba718415f4d1be289fa598cc2077b6243f", False),
        ("8dbd20507a8edbc05bd0cbc92ee4d5aba718415f4d1be289fa598cc2077b624", False),
    ],
)
def test_is_valid_sha256(s: str, expected: bool) -> None:
    """
    Validates `is_valid_sha256()` convenience function.

    :param s: String to check against.
    :param expected: Expected result of the target function.
    """
    assert is_valid_sha256(s) == expected


@pytest.mark.parametrize(
    "s,expected",
    [
        # Valid strings
        ("5885a3b911f95660068923a12112b095e658bd84", True),
        ("5885A3B911F95660068923A12112B095E658BD84", True),
        # Invalid strings
        ("5885a3b911f95660068923a12112b095e658bd8", False),
        ("5885a3b911f95660068923a12112b095e658bd84f", False),
        ("5885a3b911f95660068923a12112b095g658bd84", False),
    ],
)
def test_is_valid_sha1(s: str, expected: bool) -> None:
    """
    Validates `is_valid_sha1()` convenience function.

    :param s: String to check against.
    :param expected: Expected result of the target function.
    """
    assert is_valid_sha1(s) == expected
