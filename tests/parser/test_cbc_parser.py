"""
:Description: Provides unit tests for the CBC Parser module
"""

import pytest

from conda_recipe_manager.parser.platform_types import Platform
from conda_recipe_manager.parser.selector_query import SelectorQuery
from conda_recipe_manager.types import Primitives
from tests.file_loading import load_cbc


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
        ("anaconda_cbc_01.yaml", "zstd", SelectorQuery(), "1.5.2"),
        # TODO Determine if picking the 1st option is appropriate when the SelectorQuery is ambiguous
        ("anaconda_cbc_01.yaml", "perl", SelectorQuery(), 5.26),
        # TODO Figure out typing for this 1-dot versioning edge case
        ("anaconda_cbc_01.yaml", "perl", SelectorQuery(platform=Platform.WIN_64), 5.26),
        ("anaconda_cbc_01.yaml", "perl", SelectorQuery(platform=Platform.LINUX_64), 5.34),
    ],
)
def test_get_cbc_variable_value(file: str, variable: str, query: SelectorQuery, expected: Primitives) -> None:
    """
    Validates fetching the value of a CBC variable without specifying a default value.

    :param file: File to test against
    :param variable: Target variable name
    :param query: Target selector query
    :param expected: Expected result of the test
    """
    parser = load_cbc(file)
    assert parser.get_cbc_variable_value(variable, query) == expected


@pytest.mark.parametrize(
    "file,variable,query,exception",
    [
        ("anaconda_cbc_01.yaml", "The Limit Does Not Exist", SelectorQuery(), KeyError),
        ("anaconda_cbc_01.yaml", "macos_machine", SelectorQuery(platform=Platform.WIN_64), ValueError),
    ],
)
def test_get_cbc_variable_raises(file: str, variable: str, query: SelectorQuery, exception: Exception) -> None:
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
        parser.get_cbc_variable_value(variable, query)


@pytest.mark.parametrize(
    "file,variable,query,default,expected",
    [
        ("anaconda_cbc_01.yaml", "DNE", SelectorQuery(), None, None),
        ("anaconda_cbc_01.yaml", "DNE", SelectorQuery(), 42, 42),
        ("anaconda_cbc_01.yaml", "zstd", SelectorQuery(), 42, "1.5.2"),
        # Returns a default value when the query parameters are not a match
        ("anaconda_cbc_01.yaml", "macos_machine", SelectorQuery(platform=Platform.WIN_64), "not_a_mac", "not_a_mac"),
    ],
)
def test_get_cbc_variable_value_with_default(
    file: str, variable: str, query: SelectorQuery, default: Primitives, expected: Primitives
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
    assert parser.get_cbc_variable_value(variable, query, default) == expected


@pytest.mark.parametrize(
    "file,expected",
    [
        ("anaconda_cbc_01.yaml", [{"python", "numpy"}]),
        ("zip_keys_simple_list.yaml", [{"python", "numpy"}]),
        ("zip_keys_multiple_lists.yaml", [{"python", "numpy"}, {"pypy", "pypy3"}]),
    ],
)
def test_get_zip_keys(file: str, expected: list[set[str]]) -> None:
    """
    Validates fetching the zip keys from a CBC file.
    """
    parser = load_cbc(file)
    assert parser.get_zip_keys() == expected
