"""
:Description: Unit tests for the top-level utils module.
"""

from __future__ import annotations

import re

from conda_recipe_manager.utils.meta import get_crm_version


def test_get_crm_version() -> None:
    """
    Verifies that we can retrieve the current version of the project.

    NOTE: This is not a perfect test. It merely checks that the string returned follows the `MAJOR.MINOR.PATCH` scheme
    (so that we don't have to change this test every release).
    """
    assert re.match(r"\d+\.\d+\.\d+", get_crm_version())
