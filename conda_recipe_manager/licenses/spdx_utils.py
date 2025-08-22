"""
:Description: Provides a class that reads in the SPDX licensing database file to support SPDX utilities.

              This is a read-only class that cannot be modified once initialized.

                SPDX Data Source (freely available for use):
                  - https://github.com/spdx/license-list-data/blob/main/json/licenses.json

"""

from __future__ import annotations

import difflib
import json
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Final, Optional, cast

# Path to the SPDX JSON database. This should remain inside this module. This is stored as the raw JSON file so that
# we can easily update from the SPDX source on GitHub.
SPDX_LICENSE_JSON_FILE: Final[Traversable] = files("conda_recipe_manager.licenses").joinpath("spdx_licenses.json")

# SPDX expression operators
SPDX_EXPRESSION_OPS: Final[set[str]] = {"AND", "OR", "WITH"}


class SpdxUtils:
    """
    Class that provides SPDX tooling from the SPDX license database file.
    """

    def __init__(self) -> None:
        """
        Constructs a SPDX utility instance. Reads data from the JSON file provided by the module.
        """
        # Initialize the raw data
        self._raw_spdx_data = cast(
            dict[str, list[dict[str, str]]], json.loads(SPDX_LICENSE_JSON_FILE.read_text(encoding="utf-8"))
        )

        # Generate a few look-up tables for license matching once during initialization for faster future look-ups.
        self._license_matching_table: dict[str, str] = {}
        self._license_ids: set[str] = set()
        for license_data in self._raw_spdx_data["licenses"]:
            # Filter-out deprecated licenses. Fixes #423.
            if "isDeprecatedLicenseId" in license_data and license_data["isDeprecatedLicenseId"]:
                continue

            license_id = license_data["licenseId"]
            license_name = license_data["name"]
            # SPDX IDs are unique and used for SPDX validation. Commonly recipes use variations on names or IDs, so we
            # want to map both options to the same ID.
            self._license_matching_table[license_name] = license_id
            self._license_matching_table[license_id] = license_id
            # TODO make this a normalized -> actual name table. Add mixed-case tests for GPL.
            self._license_ids.add(license_id)

        # Custom patch table that attempts to correct common SPDX licensing mistakes that our other methodologies cannot
        # handle. Maps: `MISTAKE` (all uppercase) -> `Corrected`
        self._license_matching_patch_tbl: Final[dict[str, str]] = {
            # This commonly used name is not close enough for `difflib` to recognize
            'BSD 2-CLAUSE "SIMPLIFIED"': "BSD-2-Clause",
            # Some R packages use "Unlimited". This is the mapping the team agreed to use in a Slack thread.
            "UNLIMITED": "NOASSERTION",
        }

        # There are enough GPL license variants that maintaining all of them in the patch table would be painful.
        # So we attempt to upgrade the older names to the newer by appending the appropriate suffix.
        self._gpl_only_suffixes: Final[list[str]] = [
            "-only",
            ".0-only",  # In case someone has written something like "GPL 3"
        ]
        self._gpl_or_later_suffixes: Final[list[str]] = [
            "-or-later",
            ".0-or-later",
        ]

    def _match_gpl_license(self, sanitized_license: str) -> Optional[str]:
        """
        Attempt to upgrade GPL licenses to their newer naming schemes. Annoyingly the JSON data does not map old
        to new names for us.

        :param sanitized_license: Clean license name to start with.
        :returns: An adjusted GPL license name, if one is matched. Otherwise, `None`.
        """
        # Determine if we are in the "-or-later" case.
        # NOTE: In the future, we could look into making a network call to match old to new(?)
        target_suffixes: Final = (
            self._gpl_or_later_suffixes if sanitized_license[-1] == "+" else self._gpl_only_suffixes
        )
        sanitized_gpl_license: Final = sanitized_license[:-1] if sanitized_license[-1] == "+" else sanitized_license

        for suffix in target_suffixes:
            license_with_suffix = f"{sanitized_gpl_license}{suffix}"
            if license_with_suffix in self._license_ids:
                return license_with_suffix

        return None

    def find_closest_license_match(self, license_field: str) -> Optional[str]:
        """
        Given a license string from a recipe file (from `/about/license`), return the most likely ID in the SPDX
        database by string approximation.

        TODO Future: We might want to evaluate these tools for future use as they likely do a better job at matching
        licenses to the SPDX standard.
        * https://github.com/spdx/spdx-license-matcher
        * https://github.com/nexB/license-expression

        :param license_field: License string provided by the recipe to match
        :returns: The closest matching SPDX identifier, if found
        """
        sanitized_license: Final = license_field.strip()
        # Used when finding EXACT matches in the the patch table.
        sanitized_license_upper: Final = sanitized_license.upper()

        # Short-circuit on perfect matches
        if sanitized_license in self._license_ids:
            return sanitized_license

        # Correct known commonly used licenses that can't be handled by `difflib`. NOTE: This table normalizes around
        # upper-cased keys.
        if sanitized_license_upper in self._license_matching_patch_tbl:
            return self._license_matching_patch_tbl[sanitized_license_upper]

        # Short-circuit on known deprecation upgrade paths.
        if (gpl_match := self._match_gpl_license(sanitized_license)) is not None:
            return gpl_match

        # TODO: Improve this logic to support SPDX expressions.
        # Don't simplify compound licenses that might get accidentally simplified
        for op in SPDX_EXPRESSION_OPS:
            if op in sanitized_license:
                return None
        if "," in sanitized_license:
            return None

        match_list = difflib.get_close_matches(license_field, self._license_matching_table.keys(), 1)
        if not match_list:
            return None

        match_key = match_list[0]
        # This shouldn't be possible, but we'll guard against it to prevent an illegal dictionary access anyways
        if match_key not in self._license_matching_table:
            return None

        return self._license_matching_table[match_key]
