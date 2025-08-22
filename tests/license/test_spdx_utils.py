"""
:Description: Unit tests for the SpdxUtils class
"""

from __future__ import annotations

import pytest

from conda_recipe_manager.licenses.spdx_utils import SpdxUtils


@pytest.mark.parametrize(
    "license_field,expected",
    [
        #### Apache ####
        ("Apache License 1.0", "Apache-1.0"),
        ("Apache License 1.1", "Apache-1.1"),
        ("Apache License 2.0", "Apache-2.0"),
        #### BSD ####
        ("BSD 1-Clause", "BSD-1-Clause"),
        ("BSD_2_Clause", "BSD-2-Clause"),
        ("BSD 3-Clause", "BSD-3-Clause"),
        ("BSD_3_Clause", "BSD-3-Clause"),
        #### GPL ####
        ("GPL-2.0-only", "GPL-2.0-only"),
        ("GPL-3.0-only", "GPL-3.0-only"),
        ("AGPL-1.0-only", "AGPL-1.0-only"),
        ("LGPL-2.1-or-later", "LGPL-2.1-or-later"),
        # See Issue #423 for more details about converting to use `-only`/`-or-later` names.
        ("GPL-2", "GPL-2.0-only"),
        ("GPL-3", "GPL-3.0-only"),
        ("GPL-2.0", "GPL-2.0-only"),
        ("GPL-3.0", "GPL-3.0-only"),
        ("AGPL-1.0", "AGPL-1.0-only"),
        ("AGPL-1", "AGPL-1.0-only"),
        ("GPL-1.0+", "GPL-1.0-or-later"),
        ("GPL-1+", "GPL-1.0-or-later"),
        ("LGPL-2.1+", "LGPL-2.1-or-later"),
        ("LGPL-2.1", "LGPL-2.1-only"),
        #### Special cases that are "manually" handled outside of `difflib` ####
        ('BSD 2-Clause "SIMPLIFIED"', "BSD-2-Clause"),
    ],
)
def test_find_closest_license_match_common_issues(license_field: str, expected: str) -> None:
    """
    Validates license matching with commonly used "incorrect" license names and attempts to upgrade deprecated license
    names.
    """
    # TODO fixture
    spdx_utils = SpdxUtils()
    assert spdx_utils.find_closest_license_match(license_field) == expected


@pytest.mark.parametrize(
    "license_field",
    [
        "foobar",
        # Batman no longer works because `Gutmann` is a legitimate license with a close-enough name. So we're stuck with
        # the sidekick, I guess.
        "robin",
        "fadsjkl;adshbfjkasd",
    ],
)
def test_find_closest_license_match_failed_to_find_match(license_field: str) -> None:
    """
    Validates that the license matcher returns `None` on very far-off inputs
    """
    # TODO fixture
    spdx_utils = SpdxUtils()
    assert spdx_utils.find_closest_license_match(license_field) is None
