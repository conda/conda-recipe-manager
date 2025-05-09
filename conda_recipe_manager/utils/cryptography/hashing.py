"""
:Description: Provides hashing utilities.
"""

from __future__ import annotations

import hashlib
import string
from collections.abc import Callable
from pathlib import Path
from typing import Final

# Default buffer size to use with hashing algorithms.
_HASH_BUFFER_SIZE: Final[int] = 65536  # 64KiB


def hash_file(file: str | Path, hash_algo: str | Callable[[], hashlib._Hash]) -> str:
    """
    Hashes a file from disk with the given algorithm and returns the hash as a hexadecimal string.

    :param file: Target file.
    :param hash_algo: Hash algorithm function defined provided by `hashlib`. This can be a string name recognized by
       `hashlib` or a reference to a hash constructor.
    :returns: The hash of the file, as a hexadecimal string.
    """
    # As of Python 3.11, this is the preferred approach. Prior to this we would have had to roll-our-own buffering
    # scheme.
    with open(file, "rb") as fptr:
        return hashlib.file_digest(fptr, hash_algo).hexdigest()


def hash_str(s: str, hash_algo: Callable[[bytes], hashlib._Hash], encoding: str = "utf-8") -> str:
    """
    Hashes an in-memory string with the given algorithm and returns the hash as a hexadecimal string.

    :param s: Target string.
    :param hash_algo: Hash algorithm function defined provided by `hashlib`. For example pass-in `hashlib.sha256` to
        to perform a SHA-256 hash.
    :param encoding: (Optional) String encoding to use when interpreting the string as bytes. Defaults to `utf-8`.
    :returns: The hash of the string contents, as a hexadecimal string.
    """
    # If the string is small enough to fit in memory, we should not need to worry about buffering it.
    return hash_algo(s.encode(encoding=encoding)).hexdigest()


def is_valid_hex(s: str) -> bool:
    """
    Checks if a string is a valid hex string.

    :param s: String to validate
    :returns: True if the string is a valid hex string. False otherwise.
    """
    return all(c in string.hexdigits for c in s)


def is_valid_md5(s: str) -> bool:
    """
    Checks if a string is a valid MD5 hash.

    :param s: String to validate
    :returns: True if the string is a valid MD5 hash. False otherwise.
    """
    return len(s) == 32 and is_valid_hex(s)


def is_valid_sha256(s: str) -> bool:
    """
    Checks if a string is a valid SHA-256 hash.

    :param s: String to validate
    :returns: True if the string is a valid SHA-256 hash. False otherwise.
    """
    return len(s) == 64 and is_valid_hex(s)


def is_valid_sha1(s: str) -> bool:
    """
    Checks if a string is a valid SHA-1 hash. This is used by git/GitHub.

    :param s: String to validate
    :returns: True if the string is a valid SHA-1 hash. False otherwise.
    """
    return len(s) == 40 and is_valid_hex(s)
