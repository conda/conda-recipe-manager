"""
:Description: Tests the hashing utility module.
"""

from __future__ import annotations

import hashlib
from typing import Callable

import pytest

from conda_recipe_manager.utils.cryptography.hashing import hash_file, hash_str
from tests.file_loading import get_test_path, load_file


@pytest.mark.parametrize(
    "file,algo,expected",
    [
        ("types-toml.yaml", "sha256", "d4c2fd9b24793a890e67dc58f5182981b4dd34c50967a8358de10eade8b2e415"),
        ("types-toml.yaml", hashlib.sha256, "d4c2fd9b24793a890e67dc58f5182981b4dd34c50967a8358de10eade8b2e415"),
        (
            "types-toml.yaml",
            "sha512",
            "b343b159400058f74a01f95c856094b1add15e516592d5102a09738ba6a3c2ddb044ee0e7d461d16515925483a5bcf5f516b2725924f2900f88ec6641b1d6e72",  # pylint: disable=line-too-long
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
        ("types-toml.yaml", hashlib.sha256, "d4c2fd9b24793a890e67dc58f5182981b4dd34c50967a8358de10eade8b2e415"),
        (
            "types-toml.yaml",
            hashlib.sha512,
            "b343b159400058f74a01f95c856094b1add15e516592d5102a09738ba6a3c2ddb044ee0e7d461d16515925483a5bcf5f516b2725924f2900f88ec6641b1d6e72",  # pylint: disable=line-too-long
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
