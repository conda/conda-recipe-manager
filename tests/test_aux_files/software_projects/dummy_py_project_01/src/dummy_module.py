"""
:Description: Local dummy module used for unit testing.
"""

import hashlib  # pylint: disable=ignore-unused-import
import math

import requests  # pylint: disable=ignore-unused-import

# NOTE: These libraries are no longer part of this project. However, they still are imported to show we can detect
#       3rd-party library imports.
import matplotlib, networkx  # type: ignore[import-untyped,import-not-found] # fmt: skip # isort: skip # pylint: disable=ignore-unused-import


def meaning_of_life() -> None:
    print(int(math.pow(4, 2)) + 26)
