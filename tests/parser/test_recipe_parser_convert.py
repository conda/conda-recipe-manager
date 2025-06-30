"""
:Description: Unit tests for the RecipeParserConvert class
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from conda_recipe_manager.parser.recipe_parser_convert import RecipeParserConvert
from conda_recipe_manager.types import MessageCategory
from tests.file_loading import load_file, load_recipe


@pytest.mark.parametrize(
    "input_file,expected_file",
    [
        # {{ hash_type }} as a sha256 key replacement
        ("hash_type_replacement.yaml", "pre_processor/pp_hash_type_replacement.yaml"),
        # Environment syntax replacement
        ("simple-recipe_environ.yaml", "pre_processor/pp_simple-recipe_environ.yaml"),
        # Dot-function for pipe equivalent replacement
        ("dot_function_replacement.yaml", "pre_processor/pp_dot_function_replacement.yaml"),
        # Upgrading multiline quoted strings
        ("quoted_multiline_str.yaml", "pre_processor/pp_quoted_multiline_str.yaml"),
        # Issue #271 environ.get() conversions
        ("unprocessed_environ_get.yaml", "pre_processor/pp_environ_get.yaml"),
        # Min/max pin upgrades to new upper/lower bound syntax
        ("min_max_pin.yaml", "pre_processor/pp_min_max_pin.yaml"),
        # Unchanged file
        ("simple-recipe.yaml", "simple-recipe.yaml"),
    ],
)
def test_pre_process_recipe_text(input_file: str, expected_file: str) -> None:
    """
    Validates the pre-processor phase of the conversion process. A recipe file should come in
    as a string and return a modified string, if applicable.

    :param input_file: Test input recipe file name
    :param expected_file: Name of the file containing the expected output of a test instance
    """
    assert RecipeParserConvert.pre_process_recipe_text(load_file(input_file)) == load_file(expected_file)


@pytest.mark.parametrize(
    "file,errors,warnings",
    [
        (
            "simple-recipe.yaml",
            [],
            [
                "A non-list item had a selector at: /package/name",
                "A non-list item had a selector at: /requirements/empty_field2",
                "Could not patch unrecognized license: `Apache-2.0 AND MIT`",
            ],
        ),
        (
            "multi-output.yaml",
            ["Could not parse dependencies when attempting to upgrade ambiguous version numbers."],
            [],
        ),
        (
            "huggingface_hub.yaml",
            [],
            [
                "Field at `/about/license_family` is no longer supported.",
            ],
        ),
        (
            "types-toml.yaml",
            [],
            [
                "Could not patch unrecognized license: `Apache-2.0 AND MIT`",
                "Field at `/about/license_family` is no longer supported.",
            ],
        ),
        # Regression test: Contains a `test` section that caused an empty dictionary to be inserted in the conversion
        # process, causing an index-out-of-range exception.
        (
            "pytest-pep8.yaml",
            [],
            [
                "Field at `/about/doc_source_url` is no longer supported.",
            ],
        ),
        # Regression test: Contains selectors and test section data that caused previous conversion issues.
        (
            "google-cloud-cpp.yaml",
            [],
            [
                "Recipe upgrades cannot currently upgrade ambiguous version constraints on "
                "dependencies that use variables: {{ compiler('c') }}",
                "Recipe upgrades cannot currently upgrade ambiguous version constraints on "
                "dependencies that use variables: {{ compiler('cxx') }}",
                "Recipe upgrades cannot currently upgrade ambiguous version constraints on "
                "dependencies that use variables: {{ compiler('c') }}",
                "Recipe upgrades cannot currently upgrade ambiguous version constraints on "
                "dependencies that use variables: {{ compiler('cxx') }}",
                "Recipe upgrades cannot currently upgrade ambiguous version constraints on "
                "dependencies that use variables: {{ compiler('c') }}",
                "Recipe upgrades cannot currently upgrade ambiguous version constraints on "
                "dependencies that use variables: {{ compiler('cxx') }}",
                "Recipe upgrades cannot currently upgrade ambiguous version constraints on "
                "dependencies that use variables: {{ compiler('c') }}",
                "Recipe upgrades cannot currently upgrade ambiguous version constraints on "
                "dependencies that use variables: {{ compiler('cxx') }}",
                "Recipe upgrades cannot currently upgrade ambiguous version constraints on "
                'dependencies that use variables: {{ pin_subpackage("libgoogle-cloud-all", '
                "exact=True) }}",
                "Recipe upgrades cannot currently upgrade ambiguous version constraints on "
                "dependencies that use variables: {{ compiler('c') }}",
                "Recipe upgrades cannot currently upgrade ambiguous version constraints on "
                "dependencies that use variables: {{ compiler('cxx') }}",
                "Recipe upgrades cannot currently upgrade ambiguous version constraints on "
                "dependencies that use variables: {{ "
                'pin_subpackage("libgoogle-cloud-all-devel", exact=True) }}',
                "Recipe upgrades cannot currently upgrade ambiguous version constraints on "
                "dependencies that use variables: {{ "
                'pin_subpackage("libgoogle-cloud-all-devel", exact=True) }}',
                "Recipe upgrades cannot currently upgrade ambiguous version constraints on "
                "dependencies that use variables: {{ compiler('c') }}",
                "Recipe upgrades cannot currently upgrade ambiguous version constraints on "
                "dependencies that use variables: {{ compiler('cxx') }}",
                "A non-list item had a selector at: /outputs/0/script",
                "A non-list item had a selector at: /outputs/1/script",
                "A non-list item had a selector at: /outputs/0/script",
                "A non-list item had a selector at: /outputs/1/script",
                "Field at `/about/license_family` is no longer supported.",
            ],
        ),
        # Tests for transformations related to the new `build/dynamic_linking` section
        (
            "dynamic-linking.yaml",
            [],
            [
                "Could not patch unrecognized license: `Apache-2.0 AND MIT`",
                "Field at `/about/license_family` is no longer supported.",
            ],
        ),
        # Regression: Tests for proper indentation of a list item inside a collection node element
        (
            "boto.yaml",
            [],
            [
                "Field at `/about/doc_source_url` is no longer supported.",
            ],
        ),
        # Regression: Tests a recipe that has multiple `source`` objects in `/source` AND an `about` per `output`
        # TODO Issue #50 tracks an edge case caused by this project that is not currently handled.
        (
            "cctools-ld64.yaml",
            [],
            [
                "Changed /outputs/0/about/license from `Apple Public Source License 2.0` to " "`APSL-2.0`",
                "Field at `/outputs/0/about/license_family` is no longer supported.",
                "Changed /outputs/1/about/license from `Apple Public Source License 2.0` to " "`APSL-2.0`",
                "Field at `/outputs/1/about/license_family` is no longer supported.",
            ],
        ),
        # Regression: Tests scenarios where the newer `${{ }}` substitutions got doubled up, causing: `$${{ foo }}`
        (
            "parser_regressions/regression_jinja_sub.yaml",
            [],
            [
                (
                    "Recipe upgrades cannot currently upgrade ambiguous version constraints on dependencies that"
                    ' use variables: {{ pin_subpackage("libnvpl-fft" ~ somajor ) }}'
                ),
                "The following key(s) contain partially unsupported syntax: soversion",
                "No `license` provided in `/about`",
            ],
        ),
        # Regressions found and fixed while working on Issue #366
        (
            "parser_regressions/issue-366_quote_regressions.yaml",
            [],
            [
                "The following key(s) contain partially unsupported syntax: soversion",
                "No `license` provided in `/about`",
            ],
        ),
        # Regressions found and fixed while working on Issue #378
        (
            "parser_regressions/issue-378_colon_quote_regression.yaml",
            [
                "Could not parse dependencies when attempting to upgrade ambiguous version numbers.",
            ],
            ["Field at `/about/license_family` is no longer supported."],
        ),
        # Tests upgrading the `/build/script` when `script_env` is present (this is essentially a test for
        # `_upgrade_build_script_section()`)
        (
            "script-env.yaml",
            [
                "Converting `{'if': 'osx', 'then': 'MACOS_SECRET_SAUCE=BAZ'}` found in "
                "/build/script_env is not supported. Manually replace the selector with a "
                "`cmp()` function.",
            ],
            [],
        ),
        # build/force_used_keys migration
        (
            "use_keys.yaml",
            [],
            [],
        ),
        # build/ignore_run_exports migration
        (
            "ignore_run_exports.yaml",
            [],
            [],
        ),
        # Ensures that multiline summary sections that don't use | or > are converted correctly.
        (
            "non_marked_multiline_summary.yaml",
            [],
            [],
        ),
        # Ensures git source fields are transformed properly
        (
            "git-src.yaml",
            [],
            [],
        ),
        # Ensures common comparison selectors can be upgraded
        (
            "selector-match-upgrades.yaml",
            [],
            [],
        ),
        # Regression test. Ensures we don't emit a bad `script` section if there are no test scripts, other than
        # `pip check` (which got upgraded to a new flag).
        (
            "pip_check_only.yaml",
            [],
            [],
        ),
        # Regression test. `sub_vars.yaml` contains many JINJA edge cases.
        (
            "sub_vars.yaml",
            [],
            [
                (
                    "Recipe upgrades cannot currently upgrade ambiguous version constraints on dependencies that"
                    " use variables: {{ compiler('rust') }} >=1.65.0"
                ),
                "Could not patch unrecognized license: `Apache-2.0 AND MIT`",
                "Field at `/about/license_family` is no longer supported.",
            ],
        ),
        # Issue #271 properly elevate environ.get() into context
        (
            "environ_get.yaml",
            [],
            [],
        ),
        # Issue #276 ambiguous dependency upgrade now required by rattler-build. Also checks against a regression for
        # determining if a recipe is for a python package. The previous check was too specific.
        (
            "types-toml_ambiguous_deps.yaml",
            [],
            [
                "Version on dependency changed to: python 3.11.*",
                "Version on dependency changed to: bar-bar >=1.2",
                "Version on dependency changed to: typo-1 <= 1.2.3",
                "Version on dependency changed to: typo-2 >=1.2.3",
                "Could not patch unrecognized license: `Apache-2.0 AND MIT`",
                "Field at `/about/license_family` is no longer supported.",
            ],
        ),
        # Issue #289: Compiled projects that use Python are not "pure python" packages. Such packages should not receive
        # a Python section with a `pip_check: False` field
        (
            "parser_regressions/issue-289_regression.yaml",
            [],
            [
                "Recipe upgrades cannot currently upgrade ambiguous version constraints on dependencies that"
                " use variables: {{ stdlib('c') }}",
                "Recipe upgrades cannot currently upgrade ambiguous version constraints on dependencies that"
                " use variables: {{ compiler('c') }}",
                "Recipe upgrades cannot currently upgrade ambiguous version constraints on dependencies that"
                " use variables: {{ compiler('cxx') }}",
                "Field at `/about/license_family` is no longer supported.",
            ],
        ),
        # TODO complete: The `rust.yaml` test contains many edge cases and selectors that aren't directly supported in
        # the V1 recipe format
        # (
        #    "rust.yaml",
        #    [],
        #    [],
        # ),
        # TODO Complete: The `curl.yaml` test is far from perfect. It is very much a work in progress.
        # (
        #    "curl.yaml",
        #    [],
        #    [
        #        "A non-list item had a selector at: /outputs/0/build/ignore_run_exports",
        #    ],
        # ),
    ],
)
def test_render_to_v1_recipe_format(file: str, errors: list[str], warnings: list[str]) -> None:
    """
    Validates rendering a recipe in the V1 format.

    :param file: File path for the input that is also used to calculate the expected output, by convention.
    """
    file_path: Final = Path(file)
    parser = load_recipe(file_path, RecipeParserConvert)
    result, tbl, _ = parser.render_to_v1_recipe_format()
    assert result == load_file(f"{file_path.parent}/v1_format/v1_{file_path.name}")
    assert tbl.get_messages(MessageCategory.ERROR) == errors
    assert tbl.get_messages(MessageCategory.WARNING) == warnings
    # Ensure that the original file was untouched
    assert not parser.is_modified()
    assert parser.diff() == ""
