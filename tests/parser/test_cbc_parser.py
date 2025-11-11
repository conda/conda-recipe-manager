"""
:Description: Provides unit tests for the CBC Parser module
"""

from pathlib import Path
from typing import Final, cast

import pytest

from conda_recipe_manager.parser.cbc_parser import _SPECIAL_KEYS, CbcOutputType, CbcParser, GeneratedVariantsType
from conda_recipe_manager.parser.platform_types import Platform
from conda_recipe_manager.parser.selector_query import SelectorQuery
from conda_recipe_manager.types import JsonType, Primitives
from tests.file_loading import get_test_path, load_cbc, load_json_file

CONDA_BUILD_VARIANTS_PATH: Final[Path] = get_test_path() / "variants"


@pytest.mark.parametrize(
    "file0,file1,expected",
    [
        ("anaconda_cbc_01.yaml", "anaconda_cbc_01.yaml", True),
    ],
)
def test_eq(file0: str, file1: str, expected: bool) -> None:
    """
    Ensures that two CBC Parsers can be checked for equality.

    :param file0: File to initialize the LHS-parser in the expression
    :param file1: File to initialize the RHS-parser in the expression
    :param expected: Expected result of the test
    """
    assert (load_cbc(file0) == load_cbc(file1)) == expected


@pytest.mark.parametrize(
    "file,variable,expected",
    [
        ("anaconda_cbc_01.yaml", "DNE", False),
        ("anaconda_cbc_01.yaml", "apr", True),
        ("anaconda_cbc_01.yaml", "dbus", True),
        ("anaconda_cbc_01.yaml", "expat", True),
        ("anaconda_cbc_01.yaml", "ExPat", False),
        ("anaconda_cbc_01.yaml", "zstd", True),
        ("anaconda_cbc_01.yaml", 42, False),
    ],
)
def test_contains(file: str, variable: str, expected: bool) -> None:
    """
    Ensures that the `in` operator can be used to determine if a variable is defined in a CBC file.

    :param file: File to test against
    :param variable: Target variable name
    :param expected: Expected result of the test
    """
    parser = load_cbc(file)
    assert (variable in parser) == expected


@pytest.mark.parametrize(
    "file,expected",
    [
        (
            "anaconda_cbc_01.yaml",
            [
                "apr",
                "blas_impl",
                "boost",
                "boost_cpp",
                "bzip2",
                "cairo",
                "c_compiler",
                "cxx_compiler",
                "fortran_compiler",
                "m2w64_c_compiler",
                "m2w64_cxx_compiler",
                "m2w64_fortran_compiler",
                "rust_compiler",
                "rust_compiler_version",
                "rust_gnu_compiler",
                "rust_gnu_compiler_version",
                "CONDA_BUILD_SYSROOT",
                "VERBOSE_AT",
                "VERBOSE_CM",
                "cran_mirror",
                "c_compiler_version",
                "cxx_compiler_version",
                "fortran_compiler_version",
                "clang_variant",
                "cyrus_sasl",
                "dbus",
                "expat",
                "fontconfig",
                "freetype",
                "g2clib",
                "gstreamer",
                "gst_plugins_base",
                "geos",
                "giflib",
                "glib",
                "gmp",
                "gnu",
                "harfbuzz",
                "hdf4",
                "hdf5",
                "hdfeos2",
                "hdfeos5",
                "icu",
                "jpeg",
                "libcurl",
                "libdap4",
                "libffi",
                "libgd",
                "libgdal",
                "libgsasl",
                "libkml",
                "libnetcdf",
                "libpng",
                "libtiff",
                "libwebp",
                "libxml2",
                "libxslt",
                "llvm_variant",
                "lzo",
                "macos_min_version",
                "macos_machine",
                "MACOSX_DEPLOYMENT_TARGET",
                "mkl",
                "mpfr",
                "numpy",
                "openblas",
                "openjpeg",
                "openssl",
                "perl",
                "pixman",
                "proj4",
                "proj",
                "libprotobuf",
                "python",
                "python_implementation",
                "python_impl",
                "r_version",
                "r_implementation",
                "readline",
                "serf",
                "sqlite",
                "cross_compiler_target_platform",
                "target_platform",
                "tk",
                "vc",
                "zlib",
                "xz",
                "channel_targets",
                "cdt_name",
                "zstd",
            ],
        )
    ],
)
def test_list_cbc_variables(file: str, expected: list[str]) -> None:
    """
    Validates fetching all variables defined in a CBC parser instance.

    :param file: File to test against
    :param expected: Expected result of the test
    """
    parser = load_cbc(file)
    assert parser.list_cbc_variables() == expected


@pytest.mark.parametrize(
    "file,variable,query,expected",
    [
        ("anaconda_cbc_01.yaml", "zstd", SelectorQuery(), ["1.5.2"]),
        ("anaconda_cbc_01.yaml", "perl", SelectorQuery(platform=Platform.WIN_64), ["5.26"]),
        ("anaconda_cbc_01.yaml", "perl", SelectorQuery(platform=Platform.LINUX_64), ["5.34"]),
        # Test build environment variable selectors
        (
            "anaconda_cbc_02.yaml",
            "python",
            SelectorQuery(platform=Platform.OSX_64),
            ["3.9", "3.10", "3.11", "3.12", "3.13"],
        ),
        (
            "anaconda_cbc_02.yaml",
            "python",
            SelectorQuery(platform=Platform.OSX_64, build_env_vars={"ANACONDA_ROCKET_ENABLE_PY314": 1}),
            ["3.9", "3.10", "3.11", "3.12", "3.13", "3.14"],
        ),
        ("anaconda_cbc_02.yaml", "numpy", SelectorQuery(platform=Platform.OSX_64), ["2.0", "2.0", "2.0", "2.0", "2.1"]),
        (
            "anaconda_cbc_02.yaml",
            "numpy",
            SelectorQuery(platform=Platform.OSX_64, build_env_vars={"ANACONDA_ROCKET_ENABLE_PY314": 1}),
            ["2.0", "2.0", "2.0", "2.0", "2.1", "2.3"],
        ),
    ],
)
def test_get_cbc_variable_values(file: str, variable: str, query: SelectorQuery, expected: list[Primitives]) -> None:
    """
    Validates fetching the value of a CBC variable without specifying a default value.

    :param file: File to test against
    :param variable: Target variable name
    :param query: Target selector query
    :param expected: Expected result of the test
    """
    parser = load_cbc(file)
    assert parser.get_cbc_variable_values(variable, query) == expected


@pytest.mark.parametrize(
    "file,variable,query,exception",
    [
        ("anaconda_cbc_01.yaml", "The Limit Does Not Exist", SelectorQuery(), KeyError),
        ("anaconda_cbc_01.yaml", "perl", SelectorQuery(), ValueError),
        ("anaconda_cbc_01.yaml", "macos_machine", SelectorQuery(platform=Platform.WIN_64), ValueError),
    ],
)
def test_get_cbc_variable_values_raises(file: str, variable: str, query: SelectorQuery, exception: Exception) -> None:
    """
    Validates that an error is thrown when a variable does not exist in a CBC file or is not found for the provided
    selector.

    :param file: File to test against
    :param variable: Target variable name
    :param query: Target selector query
    :param exception: Exception expected to be raised
    """
    parser = load_cbc(file)
    with pytest.raises(exception):  # type: ignore
        parser.get_cbc_variable_values(variable, query)


@pytest.mark.parametrize(
    "file,variable,query,default,expected",
    [
        ("anaconda_cbc_01.yaml", "DNE", SelectorQuery(), None, None),
        ("anaconda_cbc_01.yaml", "DNE", SelectorQuery(), 42, 42),
        ("anaconda_cbc_01.yaml", "zstd", SelectorQuery(), 42, ["1.5.2"]),
        # Returns a default value when the query parameters are not a match
        ("anaconda_cbc_01.yaml", "macos_machine", SelectorQuery(platform=Platform.WIN_64), "not_a_mac", "not_a_mac"),
    ],
)
def test_get_cbc_variable_values_with_default(
    file: str, variable: str, query: SelectorQuery, default: Primitives, expected: Primitives | list[Primitives]
) -> None:
    """
    Validates fetching the value of a CBC variable when specifying a default value.

    :param file: File to test against
    :param variable: Target variable name
    :param query: Target selector query
    :param default: Default value to use if the value could not be found
    :param expected: Expected result of the test
    """
    parser = load_cbc(file)
    assert parser.get_cbc_variable_values(variable, query, default) == expected


@pytest.mark.parametrize(
    "file,query,expected",
    [
        # Complete CBC file
        ("anaconda_cbc_01.yaml", SelectorQuery(Platform.WIN_64), [{"python", "numpy"}]),
        ("anaconda_cbc_01.yaml", SelectorQuery(Platform.LINUX_64), [{"python", "numpy"}]),
        ("anaconda_cbc_01.yaml", SelectorQuery(Platform.OSX_64), [{"python", "numpy"}]),
        # ZIP Keys CBC file with simple list
        (
            "zip_keys_simple_list.yaml",
            SelectorQuery(Platform.LINUX_ARM_V6L),
            [{"libpng", "libtiff", "rust_compiler_version", "rust_gnu_compiler_version"}],
        ),
        (
            "zip_keys_simple_list.yaml",
            SelectorQuery(Platform.LINUX_ARM_V7L),
            [{"lzo", "lz4", "rust_compiler_version", "rust_gnu_compiler_version"}],
        ),
        (
            "zip_keys_simple_list.yaml",
            SelectorQuery(Platform.LINUX_PPC_64_LE),
            [{"xz", "zstd", "rust_compiler_version", "rust_gnu_compiler_version"}],
        ),
        (
            "zip_keys_simple_list.yaml",
            SelectorQuery(Platform.LINUX_SYS_390),
            [{"liblzma", "libzstd", "rust_compiler_version", "rust_gnu_compiler_version"}],
        ),
        (
            "zip_keys_simple_list.yaml",
            SelectorQuery(Platform.LINUX_32),
            [{"r_version", "r_implementation", "rust_compiler_version", "rust_gnu_compiler_version"}],
        ),
        (
            "zip_keys_simple_list.yaml",
            SelectorQuery(Platform.LINUX_AARCH_64),
            [{"boost", "boost_cpp", "rust_compiler_version", "rust_gnu_compiler_version"}],
        ),
        (
            "zip_keys_simple_list.yaml",
            SelectorQuery(Platform.LINUX_64),
            [
                {
                    "m2w64_c_compiler_version",
                    "m2w64_cxx_compiler_version",
                    "m2w64_fortran_compiler_version",
                    "rust_compiler_version",
                    "rust_gnu_compiler_version",
                }
            ],
        ),
        ("zip_keys_simple_list.yaml", SelectorQuery(Platform.OSX_ARM_64), [{"pypy", "pypy3"}]),
        ("zip_keys_simple_list.yaml", SelectorQuery(Platform.WIN_64), [{"python", "numpy"}]),
        # ZIP Keys CBC file with multiple lists and several selector combinations
        (
            "zip_keys_multiple_lists.yaml",
            SelectorQuery(Platform.LINUX_ARM_V6L),
            [{"libpng", "libtiff"}, {"rust_compiler_version", "rust_gnu_compiler_version"}],
        ),
        (
            "zip_keys_multiple_lists.yaml",
            SelectorQuery(Platform.LINUX_ARM_V7L),
            [{"lzo", "lz4"}, {"rust_compiler_version", "rust_gnu_compiler_version"}],
        ),
        (
            "zip_keys_multiple_lists.yaml",
            SelectorQuery(Platform.LINUX_PPC_64_LE),
            [{"xz", "zstd"}, {"rust_compiler_version", "rust_gnu_compiler_version"}],
        ),
        (
            "zip_keys_multiple_lists.yaml",
            SelectorQuery(Platform.LINUX_SYS_390),
            [{"liblzma", "libzstd"}, {"rust_compiler_version", "rust_gnu_compiler_version"}],
        ),
        (
            "zip_keys_multiple_lists.yaml",
            SelectorQuery(Platform.LINUX_32),
            [{"rust_compiler_version", "rust_gnu_compiler_version"}, {"r_version", "r_implementation"}],
        ),
        (
            "zip_keys_multiple_lists.yaml",
            SelectorQuery(Platform.LINUX_AARCH_64),
            [{"boost", "boost_cpp"}, {"rust_compiler_version", "rust_gnu_compiler_version"}],
        ),
        (
            "zip_keys_multiple_lists.yaml",
            SelectorQuery(Platform.LINUX_64),
            [
                {"m2w64_c_compiler_version", "m2w64_cxx_compiler_version", "m2w64_fortran_compiler_version"},
                {"rust_compiler_version", "rust_gnu_compiler_version"},
            ],
        ),
        ("zip_keys_multiple_lists.yaml", SelectorQuery(Platform.OSX_ARM_64), [{"pypy", "pypy3"}]),
        ("zip_keys_multiple_lists.yaml", SelectorQuery(Platform.WIN_64), [{"python", "numpy"}]),
    ],
)
def test_get_zip_keys(file: str, query: SelectorQuery, expected: list[set[str]]) -> None:
    """
    Validates fetching the zip keys from a CBC file.
    """
    parser = load_cbc(file)
    assert parser.get_zip_keys(query) == expected


@pytest.mark.parametrize(
    "files,query,expected",
    [
        (
            [load_cbc("aggregate_cbc_trimmed.yaml"), load_cbc("boost_cbc.yaml")],
            SelectorQuery(Platform.OSX_64, build_env_vars={"ANACONDA_ROCKET_ENABLE_PY314": 1}),
            (
                {
                    # --- Default variants ---
                    "cpu_optimization_target": ["nocona"],
                    "lua": ["5"],
                    "perl": ["5.26.2"],
                    # --- End default variants ---
                    "blas_impl": ["openblas"],
                    "c_compiler": ["clang"],
                    "c_stdlib": ["macosx_deployment_target"],
                    "cxx_compiler": ["clangxx"],
                    "cuda_compiler": ["cuda-nvcc"],
                    "fortran_compiler": ["gfortran"],
                    "rust_compiler": ["rust"],
                    "rust_nightly_compiler": ["rust-nightly"],
                    "rust_compiler_version": ["1.89.0"],
                    "rust_nightly_compiler_version": ["1.92.0_2025-10-13"],
                    "VERBOSE_AT": ["V=1"],
                    "VERBOSE_CM": ["VERBOSE=1"],
                    "cran_mirror": ["https://cran.r-project.org"],
                    "c_compiler_version": ["17.0.6"],
                    "c_stdlib_version": ["10.15"],
                    "cxx_compiler_version": ["17.0.6"],
                    "cuda_compiler_version": ["12.4"],
                    "fortran_compiler_version": ["11.2.0"],
                    "clang_variant": ["clang"],
                    "go_compiler": ["go-nocgo"],
                    "go_compiler_version": ["1.21"],
                    "cgo_compiler": ["go-cgo"],
                    "cgo_compiler_version": ["1.21"],
                    "python": ["3.9", "3.10", "3.11", "3.12", "3.13", "3.14"],
                    "numpy": ["2.0", "2.0", "2.0", "2.0", "2.1", "2.3"],
                    "python_implementation": ["cpython"],
                    "python_impl": ["cpython"],
                    "r_base": ["4.3.1"],
                    "r_version": ["4.3.1"],
                    "channel_targets": ["defaults"],
                    "OSX_SDK_DIR": ["/opt"],
                    "CONDA_BUILD_SYSROOT": ["/opt/MacOSX10.15.sdk"],
                    "macos_min_version": ["10.15"],
                    "macos_machine": ["x86_64-apple-darwin13.4.0"],
                    "MACOSX_DEPLOYMENT_TARGET": ["10.15"],
                },
                [{"python", "numpy"}],
            ),
        ),
    ],
)
def test_generate_cbc_values(files: list[CbcParser], query: SelectorQuery, expected: CbcOutputType) -> None:
    """
    Validates generating the CBC variable values from a list of CBC files.

    :param files: List of CBC files to generate the values from.
    :param query: Selector query to generate the values for.
    :param expected: Expected result of the test.
    """
    assert CbcParser.generate_cbc_values(files, query) == expected


def _remove_special_keys(variant: dict[str, JsonType]) -> dict[str, JsonType]:
    """
    Removes the special keys from a variant.

    :param variant: Variant to remove special keys from.
    :returns: Variant with special keys removed.
    """
    for key in _SPECIAL_KEYS:
        variant.pop(key, None)
    return variant


def _transform_integers_to_strings(variant: dict[str, JsonType]) -> dict[str, JsonType]:
    """
    Transforms integers to strings in a variant.

    :param variant: Variant to transform.
    :returns: Variant with integers transformed to strings.
    """
    for key, value in variant.items():
        if isinstance(value, int):
            variant[key] = str(value)
    return variant


def _find_matching_variant(var_to_find: dict[str, JsonType], variants: list[dict[str, JsonType]]) -> bool:
    """
    Finds a matching variant in a tuple of variants.

    :param var_to_find: Variant to find.
    :param variants: List of variants to search through.
    :returns: True if a matching variant is found. False otherwise.
    """
    for var in variants:
        for key, value in var_to_find.items():
            variants_value = var[key]
            if key == "zip_keys":
                variants_value_set = [set(elem) for elem in cast(list[list[str]], variants_value)]
                value_set = [set(elem) for elem in cast(list[list[str]], value)]
                if variants_value_set != value_set:
                    break
                continue
            if variants_value != value:
                break
        else:
            return True
    return False


@pytest.mark.parametrize(
    "cbc_files,query,conda_build_variants",
    [
        (
            [load_cbc("aggregate_cbc.yaml"), load_cbc("boost_cbc.yaml")],
            SelectorQuery(platform=Platform.OSX_ARM_64),
            load_json_file(CONDA_BUILD_VARIANTS_PATH / "no_env" / "conda_build_variants_osx-arm64.json"),
        ),
        (
            [load_cbc("aggregate_cbc.yaml"), load_cbc("boost_cbc.yaml")],
            SelectorQuery(platform=Platform.LINUX_AARCH_64),
            load_json_file(CONDA_BUILD_VARIANTS_PATH / "no_env" / "conda_build_variants_linux-aarch64.json"),
        ),
        (
            [load_cbc("aggregate_cbc.yaml"), load_cbc("boost_cbc.yaml")],
            SelectorQuery(platform=Platform.LINUX_64),
            load_json_file(CONDA_BUILD_VARIANTS_PATH / "no_env" / "conda_build_variants_linux-64.json"),
        ),
        (
            [load_cbc("aggregate_cbc.yaml"), load_cbc("boost_cbc.yaml")],
            SelectorQuery(platform=Platform.WIN_64),
            load_json_file(CONDA_BUILD_VARIANTS_PATH / "no_env" / "conda_build_variants_win-64.json"),
        ),
        (
            [load_cbc("aggregate_cbc.yaml"), load_cbc("boost_cbc.yaml")],
            SelectorQuery(platform=Platform.OSX_ARM_64, build_env_vars={"ANACONDA_ROCKET_ENABLE_PY314": 1}),
            load_json_file(CONDA_BUILD_VARIANTS_PATH / "py314_env" / "conda_build_variants_osx-arm64.json"),
        ),
        (
            [load_cbc("aggregate_cbc.yaml"), load_cbc("boost_cbc.yaml")],
            SelectorQuery(platform=Platform.LINUX_AARCH_64, build_env_vars={"ANACONDA_ROCKET_ENABLE_PY314": 1}),
            load_json_file(CONDA_BUILD_VARIANTS_PATH / "py314_env" / "conda_build_variants_linux-aarch64.json"),
        ),
        (
            [load_cbc("aggregate_cbc.yaml"), load_cbc("boost_cbc.yaml")],
            SelectorQuery(platform=Platform.LINUX_64, build_env_vars={"ANACONDA_ROCKET_ENABLE_PY314": 1}),
            load_json_file(CONDA_BUILD_VARIANTS_PATH / "py314_env" / "conda_build_variants_linux-64.json"),
        ),
        (
            [load_cbc("aggregate_cbc.yaml"), load_cbc("boost_cbc.yaml")],
            SelectorQuery(platform=Platform.WIN_64, build_env_vars={"ANACONDA_ROCKET_ENABLE_PY314": 1}),
            load_json_file(CONDA_BUILD_VARIANTS_PATH / "py314_env" / "conda_build_variants_win-64.json"),
        ),
    ],
)
def test_generate_variants(
    cbc_files: list[CbcParser], query: SelectorQuery, conda_build_variants: list[dict[str, JsonType]]
) -> None:
    """
    Validates generating the variants from a list of CBC files.

    :param cbc_files: List of CBC files to generate the variants from.
    :param query: Selector query to generate the variants for.
    :param conda_build_variants: Conda build variants to compare against.
    """
    # Generate the variants
    generated_variants_original: GeneratedVariantsType = CbcParser.generate_variants(cbc_files, query)
    # Remove the ignored special keys from the expected variants
    expected_variants = [_remove_special_keys(variant) for variant in conda_build_variants]
    # Transform integers into their string representation in the generated variants to match conda_build's output
    generated_variants = [_transform_integers_to_strings(variant) for variant in generated_variants_original]

    # Check that the keys are the same
    generated_var_keys = generated_variants[0].keys()
    expected_var_keys = expected_variants[0].keys()
    mismatch_message = f"Generated keys that are not in expected: {generated_var_keys - expected_var_keys}\n"
    mismatch_message += f"Expected keys that are not in generated: {expected_var_keys - generated_var_keys}"
    assert generated_var_keys == expected_var_keys, mismatch_message
    for gen_var in generated_variants:
        assert gen_var.keys() == generated_var_keys
    for expected_var in expected_variants:
        assert expected_var.keys() == expected_var_keys

    # Check that the values are the same
    for exp_var in expected_variants:
        assert _find_matching_variant(exp_var, generated_variants)
    for gen_var in generated_variants:
        assert _find_matching_variant(gen_var, expected_variants)
