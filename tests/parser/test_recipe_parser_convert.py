"""
:Description: Unit tests for the RecipeParserConvert class
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from conda_recipe_manager.parser._message_table import MessageCategory
from conda_recipe_manager.parser.recipe_parser_convert import RecipeParserConvert
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
                "A key item had a selector at: /requirements/empty_field2",
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
        # Regressions found and fixed while working on Issue #220.
        (
            "parser_regressions/issue-220_raw_multiline_str_01.yaml",
            [],
            [
                "Version on dependency changed to: _libgcc_mutex 0.1 main.*",
                "Version on dependency changed to: _openmp_mutex 5.1 1_gnu.*",
                "Version on dependency changed to: binutils_impl_linux-64 2.44 h4b9a079_2.*",
                "Version on dependency changed to: binutils_linux-64 2.44 hc03a8fd_2.*",
                "Version on dependency changed to: gcc_impl_linux-64 14.3.0 h4943218_4.*",
                "Version on dependency changed to: gcc_linux-64 14.3.0 hda73cce_12.*",
                "Version on dependency changed to: gxx_impl_linux-64 14.3.0 he634eba_4.*",
                "Version on dependency changed to: gxx_linux-64 14.3.0 hca8765c_12.*",
                "Version on dependency changed to: kernel-headers_linux-64 4.18.0 h3108a97_1.*",
                "Version on dependency changed to: ld_impl_linux-64 2.44 h153f514_2.*",
                "Version on dependency changed to: libgcc 15.2.0 h69a1729_7.*",
                "Version on dependency changed to: libgcc-devel_linux-64 14.3.0 he7458c1_104.*",
                "Version on dependency changed to: libgcc-ng 15.2.0 h166f726_7.*",
                "Version on dependency changed to: libgomp 15.2.0 h4751f2c_7.*",
                "Version on dependency changed to: libsanitizer 14.3.0 hd4faa28_4.*",
                "Version on dependency changed to: libstdcxx 15.2.0 h39759b7_7.*",
                "Version on dependency changed to: libstdcxx-devel_linux-64 14.3.0 he7458c1_104.*",
                "Version on dependency changed to: ninja-base 1.13.1 h0f57076_0.*",
                "Version on dependency changed to: pkg-config 0.29.2 h1bed415_8.*",
                "Version on dependency changed to: sysroot_linux-64 2.28 h3108a97_1.*",
                "Version on dependency changed to: tzdata 2025b h04d1e81_0.*",
                "Version on dependency changed to: _libgcc_mutex 0.1 main.*",
                "Version on dependency changed to: _openmp_mutex 5.1 1_gnu.*",
                "Version on dependency changed to: blas 1.0 openblas.*",
                "Version on dependency changed to: bzip2 1.0.8 h5eee18b_6.*",
                "Version on dependency changed to: ca-certificates 2025.12.2 h06a4308_0.*",
                "Version on dependency changed to: cython 3.2.2 py314h47b2149_0.*",
                "Version on dependency changed to: ld_impl_linux-64 2.44 h153f514_2.*",
                "Version on dependency changed to: libexpat 2.7.3 h7354ed3_4.*",
                "Version on dependency changed to: libffi 3.4.4 h6a678d5_1.*",
                "Version on dependency changed to: libgcc 15.2.0 h69a1729_7.*",
                "Version on dependency changed to: libgcc-ng 15.2.0 h166f726_7.*",
                "Version on dependency changed to: libgfortran 15.2.0 h166f726_7.*",
                "Version on dependency changed to: libgfortran-ng 15.2.0 h166f726_7.*",
                "Version on dependency changed to: libgfortran5 15.2.0 hc633d37_7.*",
                "Version on dependency changed to: libgomp 15.2.0 h4751f2c_7.*",
                "Version on dependency changed to: libmpdec 4.0.0 h5eee18b_0.*",
                "Version on dependency changed to: libopenblas 0.3.30 h46f56fc_2.*",
                "Version on dependency changed to: libstdcxx 15.2.0 h39759b7_7.*",
                "Version on dependency changed to: libstdcxx-ng 15.2.0 hc03a8fd_7.*",
                "Version on dependency changed to: libuuid 1.41.5 h5eee18b_0.*",
                "Version on dependency changed to: libxcb 1.17.0 h9b100fa_0.*",
                "Version on dependency changed to: libzlib 1.3.1 hb25bd0a_0.*",
                "Version on dependency changed to: lz4-c 1.9.4 h6a678d5_1.*",
                "Version on dependency changed to: meson 1.9.0 py314h06a4308_0.*",
                "Version on dependency changed to: meson-python 0.18.0 py314h5eee18b_1.*",
                "Version on dependency changed to: ncurses 6.5 h7934f7d_0.*",
                "Version on dependency changed to: ninja-base 1.13.1 h0f57076_0.*",
                "Version on dependency changed to: nomkl 3.0 0.*",
                "Version on dependency changed to: openblas-devel 0.3.30 h557178c_2.*",
                "Version on dependency changed to: openssl 3.0.18 hd6dcaed_0.*",
                "Version on dependency changed to: packaging 25.0 py314h06a4308_1.*",
                "Version on dependency changed to: pip 25.3 pyh0d26453_0.*",
                "Version on dependency changed to: pthread-stubs 0.3 h0ce48e5_1.*",
                "Version on dependency changed to: pyproject-metadata 0.9.0 py314h06a4308_0.*",
                "Version on dependency changed to: pyproject_hooks 1.2.0 py314h06a4308_1.*",
                "Version on dependency changed to: python 3.14.2 h90eec9f_101_cp314.*",
                "Version on dependency changed to: python-build 1.3.0 py314h06a4308_1.*",
                "Version on dependency changed to: python_abi 3.14 2_cp314.*",
                "Version on dependency changed to: readline 8.3 hc2a1206_0.*",
                "Version on dependency changed to: sqlite 3.51.1 he0a8d7e_0.*",
                "Version on dependency changed to: tk 8.6.15 h54e0aa7_0.*",
                "Version on dependency changed to: tzdata 2025b h04d1e81_0.*",
                "Version on dependency changed to: xorg-libx11 1.8.12 h9b100fa_1.*",
                "Version on dependency changed to: xorg-libxau 1.0.12 h9b100fa_0.*",
                "Version on dependency changed to: xorg-libxdmcp 1.1.5 h9b100fa_0.*",
                "Version on dependency changed to: xorg-xorgproto 2024.1 h5eee18b_1.*",
                "Version on dependency changed to: xz 5.6.4 h5eee18b_1.*",
                "Version on dependency changed to: zlib 1.3.1 hb25bd0a_0.*",
                "Version on dependency changed to: zstd 1.5.7 h11fc155_0.*",
                "Could not patch unrecognized license: `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0`",
                "Field at `/about/license_family` is no longer supported.",
            ],
        ),
        (
            "parser_regressions/issue-220_raw_multiline_str_02.yaml",
            ["Could not parse dependencies when attempting to upgrade ambiguous version numbers."],
            [],
        ),
        (
            "parser_regressions/issue-220_raw_multiline_str_03.yaml",
            ["Could not parse dependencies when attempting to upgrade ambiguous version numbers."],
            [],
        ),
        (
            "parser_regressions/issue-220_raw_multiline_str_04.yaml",
            ["Could not parse dependencies when attempting to upgrade ambiguous version numbers."],
            [],
        ),
        (
            "parser_regressions/issue-220_raw_multiline_str_05.yaml",
            ["Could not parse dependencies when attempting to upgrade ambiguous version numbers."],
            [],
        ),
        (
            "parser_regressions/issue-220_raw_multiline_str_06.yaml",
            [],
            [
                "Version on dependency changed to: _libgcc_mutex 0.1 main.*",
                "Version on dependency changed to: _openmp_mutex 5.1 1_gnu.*",
                "Version on dependency changed to: binutils_impl_linux-64 2.40 h5293946_0.*",
                "Version on dependency changed to: binutils_linux-64 2.40.0 hc2dff05_2.*",
                "Version on dependency changed to: gcc_impl_linux-64 11.2.0 h1234567_1.*",
                "Version on dependency changed to: gcc_linux-64 11.2.0 h5c386dc_2.*",
                "Version on dependency changed to: gfortran_impl_linux-64 11.2.0 h1234567_1.*",
                "Version on dependency changed to: gfortran_linux-64 11.2.0 hc2dff05_2.*",
                "Version on dependency changed to: gxx_impl_linux-64 11.2.0 h1234567_1.*",
                "Version on dependency changed to: gxx_linux-64 11.2.0 hc2dff05_2.*",
                "Version on dependency changed to: kernel-headers_linux-64 4.18.0 h528b178_0.*",
                "Version on dependency changed to: ld_impl_linux-64 2.40 h12ee557_0.*",
                "Version on dependency changed to: libgcc-devel_linux-64 11.2.0 h1234567_1.*",
                "Version on dependency changed to: libgcc-ng 11.2.0 h1234567_1.*",
                "Version on dependency changed to: libgfortran5 11.2.0 h1234567_1.*",
                "Version on dependency changed to: libgomp 11.2.0 h1234567_1.*",
                "Version on dependency changed to: libstdcxx-devel_linux-64 11.2.0 h1234567_1.*",
                "Version on dependency changed to: libstdcxx-ng 11.2.0 h1234567_1.*",
                "Version on dependency changed to: pkg-config 0.29.2 h1bed415_8.*",
                "Version on dependency changed to: sysroot_linux-64 2.28 h528b178_0.*",
                "Version on dependency changed to: tzdata 2025b h04d1e81_0.*",
                "Version on dependency changed to: _libgcc_mutex 0.1 main.*",
                "Version on dependency changed to: _openmp_mutex 5.1 1_gnu.*",
                "Version on dependency changed to: _sysroot_linux-64_curr_repodata_hack 3 haa98f57_10.*",
                "Version on dependency changed to: beniget 0.4.2.post1 py313h06a4308_1.*",
                "Version on dependency changed to: binutils_impl_linux-64 2.40 h5293946_0.*",
                "Version on dependency changed to: binutils_linux-64 2.40.0 hc2dff05_2.*",
                "Version on dependency changed to: blas 1.0 openblas.*",
                "Version on dependency changed to: bzip2 1.0.8 h5eee18b_6.*",
                "Version on dependency changed to: ca-certificates 2025.9.9 h06a4308_0.*",
                "Version on dependency changed to: cython 3.1.4 py313hee96239_0.*",
                "Version on dependency changed to: expat 2.7.1 h6a678d5_0.*",
                "Version on dependency changed to: gast 0.6.0 pyhd3eb1b0_0.*",
                "Version on dependency changed to: gcc_impl_linux-64 11.2.0 h1234567_1.*",
                "Version on dependency changed to: gcc_linux-64 11.2.0 h5c386dc_2.*",
                "Version on dependency changed to: gxx_impl_linux-64 11.2.0 h1234567_1.*",
                "Version on dependency changed to: gxx_linux-64 11.2.0 hc2dff05_2.*",
                "Version on dependency changed to: kernel-headers_linux-64 3.10.0 h57e8cba_10.*",
                "Version on dependency changed to: ld_impl_linux-64 2.40 h12ee557_0.*",
                "Version on dependency changed to: libffi 3.4.4 h6a678d5_1.*",
                "Version on dependency changed to: libgcc-devel_linux-64 11.2.0 h1234567_1.*",
                "Version on dependency changed to: libgcc-ng 11.2.0 h1234567_1.*",
                "Version on dependency changed to: libgfortran-ng 11.2.0 h00389a5_1.*",
                "Version on dependency changed to: libgfortran5 11.2.0 h1234567_1.*",
                "Version on dependency changed to: libgomp 11.2.0 h1234567_1.*",
                "Version on dependency changed to: libmpdec 4.0.0 h5eee18b_0.*",
                "Version on dependency changed to: libopenblas 0.3.30 h46f56fc_0.*",
                "Version on dependency changed to: libstdcxx-devel_linux-64 11.2.0 h1234567_1.*",
                "Version on dependency changed to: libstdcxx-ng 11.2.0 h1234567_1.*",
                "Version on dependency changed to: libuuid 1.41.5 h5eee18b_0.*",
                "Version on dependency changed to: libxcb 1.17.0 h9b100fa_0.*",
                "Version on dependency changed to: libzlib 1.3.1 hb25bd0a_0.*",
                "Version on dependency changed to: meson 1.9.0 py313h06a4308_0.*",
                "Version on dependency changed to: meson-python 0.18.0 py313h5eee18b_1.*",
                "Version on dependency changed to: ncurses 6.5 h7934f7d_0.*",
                "Version on dependency changed to: ninja-base 1.12.1 hdb19cb5_0.*",
                "Version on dependency changed to: nomkl 3.0 0.*",
                "Version on dependency changed to: numpy 2.1.3 py313h816806e_3.*",
                "Version on dependency changed to: numpy-base 2.1.3 py313h7203c5b_3.*",
                "Version on dependency changed to: openblas-devel 0.3.30 h557178c_0.*",
                "Version on dependency changed to: openssl 3.0.18 hd6dcaed_0.*",
                "Version on dependency changed to: packaging 25.0 py313h06a4308_1.*",
                "Version on dependency changed to: pip 25.2 pyhc872135_1.*",
                "Version on dependency changed to: ply 3.11 py313h06a4308_1.*",
                "Version on dependency changed to: pthread-stubs 0.3 h0ce48e5_1.*",
                "Version on dependency changed to: pybind11 2.13.6 py313hdb19cb5_1.*",
                "Version on dependency changed to: pybind11-global 2.13.6 py313hdb19cb5_1.*",
                "Version on dependency changed to: pyproject-metadata 0.9.0 py313h06a4308_0.*",
                "Version on dependency changed to: pyproject_hooks 1.2.0 py313h06a4308_1.*",
                "Version on dependency changed to: python 3.13.9 h7e8bc2b_100_cp313.*",
                "Version on dependency changed to: python-build 1.3.0 py313h06a4308_1.*",
                "Version on dependency changed to: python_abi 3.13 1_cp313.*",
                "Version on dependency changed to: pythran 0.18.0 py313hd6c1e4e_0.*",
                "Version on dependency changed to: readline 8.3 hc2a1206_0.*",
                "Version on dependency changed to: setuptools 72.1.0 py313h06a4308_0.*",
                "Version on dependency changed to: sqlite 3.50.2 hb25bd0a_1.*",
                "Version on dependency changed to: sysroot_linux-64 2.17 h57e8cba_10.*",
                "Version on dependency changed to: tk 8.6.15 h54e0aa7_0.*",
                "Version on dependency changed to: tzdata 2025b h04d1e81_0.*",
                "Version on dependency changed to: wheel 0.45.1 py313h06a4308_0.*",
                "Version on dependency changed to: xorg-libx11 1.8.12 h9b100fa_1.*",
                "Version on dependency changed to: xorg-libxau 1.0.12 h9b100fa_0.*",
                "Version on dependency changed to: xorg-libxdmcp 1.1.5 h9b100fa_0.*",
                "Version on dependency changed to: xorg-xorgproto 2024.1 h5eee18b_1.*",
                "Version on dependency changed to: xz 5.6.4 h5eee18b_1.*",
                "Version on dependency changed to: zlib 1.3.1 hb25bd0a_0.*",
                "Could not patch unrecognized license: `BSD-3-Clause AND MIT AND BSD-3-Clause-Attribution AND"
                " BSD-2-Clause AND BSL-1.0`",
                "Field at `/about/license_family` is no longer supported.",
            ],
        ),
        (
            "parser_regressions/issue-220_raw_multiline_str_07.yaml",
            ["Could not parse dependencies when attempting to upgrade ambiguous version numbers."],
            ["No `license` provided in `/about`"],
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
        # Issue #394: variable with a "+" (version with local version identifier) not treated as string
        (
            "parser_regressions/issue-394_regression.yaml",
            [],
            [],
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
        #        "A key item had a selector at: /outputs/0/build/ignore_run_exports",
        #    ],
        # ),
        # Test JINJA2 lists conversion to context objects
        (
            "jinja2_statements/furl.yaml",
            [],
            [
                "Field at `/about/license_family` is no longer supported.",
            ],
        ),
        (
            "more-itertools.yaml",
            [],
            [],
        ),
        # Issue #479: noarch python recipes should use `python_min` instead of `python` in skip conditions
        (
            "noarch-python-skip.yaml",
            [],
            [],
        ),
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


@pytest.mark.parametrize(
    "file,errors,warnings",
    [
        # Ensures a V0 `run_exports` field gets upgraded to a list if a single value is present.
        (
            "parser_regressions/run_exports_as_list.yaml",
            [],
            [],
        ),
    ],
)
def test_render_to_v1_recipe_format_with_preprocess(file: str, errors: list[str], warnings: list[str]) -> None:
    """
    Validates rendering a recipe in the V1 format in combination with the text pre-processor. This simulates
    what `crm convert` actually does and doesn't hold the two phases in isolation.

    :param file: File path for the input that is also used to calculate the expected output, by convention.
    """
    file_path: Final = Path(file)
    parser = RecipeParserConvert(RecipeParserConvert.pre_process_recipe_text(load_file(file)))
    result, tbl, _ = parser.render_to_v1_recipe_format()
    assert result == load_file(f"{file_path.parent}/v1_format/v1_{file_path.name}")
    assert tbl.get_messages(MessageCategory.ERROR) == errors
    assert tbl.get_messages(MessageCategory.WARNING) == warnings
    # Ensure that the original file was untouched
    assert not parser.is_modified()
    assert parser.diff() == ""
