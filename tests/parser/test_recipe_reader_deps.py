"""
:Description: Tests for the advanced dependency tools for the `RecipeReader`.
"""

from __future__ import annotations

import pytest
from conda.models.match_spec import MatchSpec

from conda_recipe_manager.parser.dependency import Dependency, DependencyMap, DependencySection, DependencyVariable
from conda_recipe_manager.parser.recipe_reader_deps import RecipeReaderDeps
from conda_recipe_manager.parser.selector_parser import SchemaVersion, SelectorParser
from tests.file_loading import load_recipe


@pytest.mark.parametrize(
    "file,expected",
    [
        ("types-toml.yaml", {"types-toml": "/"}),
        ("v1_format/v1_types-toml.yaml", {"types-toml": "/"}),
        ("boto.yaml", {"boto": "/"}),
        ("v1_format/v1_boto.yaml", {"boto": "/"}),
        (
            "google-cloud-cpp.yaml",
            {
                "google-cloud-cpp-split": "/",
                "libgoogle-cloud-all": "/outputs/0",
                "libgoogle-cloud-all-devel": "/outputs/1",
                "google-cloud-cpp": "/outputs/2",
            },
        ),
        (
            "v1_format/v1_google-cloud-cpp.yaml",
            {
                "google-cloud-cpp-split": "/",
                "libgoogle-cloud-all": "/outputs/0",
                "libgoogle-cloud-all-devel": "/outputs/1",
                "google-cloud-cpp": "/outputs/2",
            },
        ),
        (
            "libprotobuf.yaml",
            {"libprotobuf-suite": "/", "libprotobuf": "/outputs/0", "libprotobuf-static": "/outputs/1"},
        ),
    ],
)
def test_get_package_names_to_path(file: str, expected: dict[str, str]) -> None:
    """
    Validates generating a map of package names to locations in the recipe file

    :param file: File to test against
    :param expected: Expected output
    """
    parser = load_recipe(file, RecipeReaderDeps)
    assert parser.get_package_names_to_path() == expected


@pytest.mark.parametrize(
    "file,expected",
    [
        (
            "types-toml.yaml",
            {
                "types-toml": [
                    Dependency(
                        "types-toml", "/requirements/host/0", DependencySection.HOST, MatchSpec("setuptools"), None
                    ),
                    Dependency("types-toml", "/requirements/host/1", DependencySection.HOST, MatchSpec("wheel"), None),
                    Dependency("types-toml", "/requirements/host/2", DependencySection.HOST, MatchSpec("pip"), None),
                    Dependency("types-toml", "/requirements/host/3", DependencySection.HOST, MatchSpec("python"), None),
                    Dependency("types-toml", "/requirements/run/0", DependencySection.RUN, MatchSpec("python"), None),
                ]
            },
        ),
        (
            "v1_format/v1_types-toml.yaml",
            {
                "types-toml": [
                    Dependency(
                        "types-toml", "/requirements/host/0", DependencySection.HOST, MatchSpec("setuptools"), None
                    ),
                    Dependency("types-toml", "/requirements/host/1", DependencySection.HOST, MatchSpec("wheel"), None),
                    Dependency("types-toml", "/requirements/host/2", DependencySection.HOST, MatchSpec("pip"), None),
                    Dependency("types-toml", "/requirements/host/3", DependencySection.HOST, MatchSpec("python"), None),
                    Dependency("types-toml", "/requirements/run/0", DependencySection.RUN, MatchSpec("python"), None),
                ]
            },
        ),
        # simple-recipe.yaml tests that unrecognized requirements fields are ignored
        (
            "simple-recipe.yaml",
            {
                "types-toml": [
                    Dependency(
                        "types-toml",
                        "/requirements/host/0",
                        DependencySection.HOST,
                        MatchSpec("setuptools"),
                        SelectorParser("[unix]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "types-toml",
                        "/requirements/host/1",
                        DependencySection.HOST,
                        MatchSpec("fakereq"),
                        SelectorParser("[unix]", SchemaVersion.V0),
                    ),
                    Dependency("types-toml", "/requirements/run/0", DependencySection.RUN, MatchSpec("python"), None),
                ]
            },
        ),
        (
            "boto.yaml",
            {
                "boto": [
                    Dependency("boto", "/requirements/host/0", DependencySection.HOST, MatchSpec("python"), None),
                    Dependency("boto", "/requirements/run/0", DependencySection.RUN, MatchSpec("python"), None),
                ]
            },
        ),
        (
            "v1_format/v1_boto.yaml",
            {
                "boto": [
                    Dependency("boto", "/requirements/host/0", DependencySection.HOST, MatchSpec("python"), None),
                    Dependency("boto", "/requirements/run/0", DependencySection.RUN, MatchSpec("python"), None),
                ]
            },
        ),
        # TODO Future: Add V1 variant of this test when V1 selector support is added.
        (
            "cctools-ld64.yaml",
            {
                "cctools-and-ld64": [
                    Dependency(
                        "cctools-and-ld64",
                        "/requirements/build/0",
                        DependencySection.BUILD,
                        MatchSpec("gcc_linux-64"),
                        SelectorParser("[linux]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "cctools-and-ld64",
                        "/requirements/build/1",
                        DependencySection.BUILD,
                        MatchSpec("gxx_linux-64"),
                        SelectorParser("[linux]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "cctools-and-ld64",
                        "/requirements/build/2",
                        DependencySection.BUILD,
                        MatchSpec("autoconf"),
                        None,
                    ),
                    Dependency(
                        "cctools-and-ld64",
                        "/requirements/build/3",
                        DependencySection.BUILD,
                        MatchSpec("automake"),
                        None,
                    ),
                    Dependency(
                        "cctools-and-ld64",
                        "/requirements/host/0",
                        DependencySection.HOST,
                        MatchSpec("xar-bootstrap"),
                        None,
                    ),
                    Dependency(
                        "cctools-and-ld64", "/requirements/host/1", DependencySection.HOST, MatchSpec("zlib"), None
                    ),
                    Dependency(
                        "cctools-and-ld64",
                        "/requirements/host/2",
                        DependencySection.HOST,
                        MatchSpec("llvm-lto-tapi"),
                        None,
                    ),
                ],
                "cctools": [
                    Dependency(
                        "cctools",
                        "/outputs/0/requirements/run/0",
                        DependencySection.RUN,
                        MatchSpec("llvm-lto-tapi"),
                        None,
                    ),
                    Dependency(
                        "cctools",
                        "/requirements/build/0",
                        DependencySection.BUILD,
                        MatchSpec("gcc_linux-64"),
                        SelectorParser("[linux]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "cctools",
                        "/requirements/build/1",
                        DependencySection.BUILD,
                        MatchSpec("gxx_linux-64"),
                        SelectorParser("[linux]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "cctools", "/requirements/build/2", DependencySection.BUILD, MatchSpec("autoconf"), None
                    ),
                    Dependency(
                        "cctools", "/requirements/build/3", DependencySection.BUILD, MatchSpec("automake"), None
                    ),
                    Dependency(
                        "cctools", "/requirements/host/0", DependencySection.HOST, MatchSpec("xar-bootstrap"), None
                    ),
                    Dependency("cctools", "/requirements/host/1", DependencySection.HOST, MatchSpec("zlib"), None),
                    Dependency(
                        "cctools", "/requirements/host/2", DependencySection.HOST, MatchSpec("llvm-lto-tapi"), None
                    ),
                ],
                "ld64": [
                    Dependency(
                        "ld64",
                        "/outputs/1/requirements/host/0",
                        DependencySection.HOST,
                        MatchSpec("llvm-lto-tapi"),
                        None,
                    ),
                    Dependency(
                        "ld64",
                        "/outputs/1/requirements/host/1",
                        DependencySection.HOST,
                        MatchSpec("libcxx"),
                        SelectorParser("[osx]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "ld64", "/outputs/1/requirements/run/0", DependencySection.RUN, MatchSpec("llvm-lto-tapi"), None
                    ),
                    Dependency(
                        "ld64",
                        "/outputs/1/requirements/run/1",
                        DependencySection.RUN,
                        MatchSpec("libcxx"),
                        SelectorParser("[osx]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "ld64",
                        "/requirements/build/0",
                        DependencySection.BUILD,
                        MatchSpec("gcc_linux-64"),
                        SelectorParser("[linux]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "ld64",
                        "/requirements/build/1",
                        DependencySection.BUILD,
                        MatchSpec("gxx_linux-64"),
                        SelectorParser("[linux]", SchemaVersion.V0),
                    ),
                    Dependency("ld64", "/requirements/build/2", DependencySection.BUILD, MatchSpec("autoconf"), None),
                    Dependency("ld64", "/requirements/build/3", DependencySection.BUILD, MatchSpec("automake"), None),
                    Dependency(
                        "ld64", "/requirements/host/0", DependencySection.HOST, MatchSpec("xar-bootstrap"), None
                    ),
                    Dependency("ld64", "/requirements/host/1", DependencySection.HOST, MatchSpec("zlib"), None),
                    Dependency(
                        "ld64", "/requirements/host/2", DependencySection.HOST, MatchSpec("llvm-lto-tapi"), None
                    ),
                ],
            },
        ),
        # Regression Test: The parser previously crashed when trying to substitute `{{ compiler('c' ) }}`
        (
            "libprotobuf.yaml",
            {
                "libprotobuf": [
                    Dependency(
                        "libprotobuf",
                        "/outputs/0/requirements/build/0",
                        DependencySection.BUILD,
                        DependencyVariable("{{ compiler('c') }}"),
                        selector=None,
                    ),
                    Dependency(
                        "libprotobuf",
                        "/outputs/0/requirements/build/1",
                        DependencySection.BUILD,
                        DependencyVariable("{{ compiler('cxx') }}"),
                        selector=None,
                    ),
                    Dependency(
                        "libprotobuf",
                        "/outputs/0/requirements/build/2",
                        DependencySection.BUILD,
                        MatchSpec("cmake"),
                        SelectorParser("[win]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "libprotobuf",
                        "/outputs/0/requirements/build/3",
                        DependencySection.BUILD,
                        MatchSpec("ninja"),
                        SelectorParser("[win]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "libprotobuf",
                        "/outputs/0/requirements/build/4",
                        DependencySection.BUILD,
                        MatchSpec("autoconf"),
                        SelectorParser("[not win]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "libprotobuf",
                        "/outputs/0/requirements/build/5",
                        DependencySection.BUILD,
                        MatchSpec("automake"),
                        SelectorParser("[not win]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "libprotobuf",
                        "/outputs/0/requirements/build/6",
                        DependencySection.BUILD,
                        MatchSpec("libtool"),
                        SelectorParser("[not win]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "libprotobuf",
                        "/outputs/0/requirements/build/7",
                        DependencySection.BUILD,
                        MatchSpec("pkg-config"),
                        SelectorParser("[not win]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "libprotobuf",
                        "/outputs/0/requirements/build/8",
                        DependencySection.BUILD,
                        MatchSpec("unzip"),
                        SelectorParser("[not win]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "libprotobuf",
                        "/outputs/0/requirements/build/9",
                        DependencySection.BUILD,
                        MatchSpec("make"),
                        SelectorParser("[not win]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "libprotobuf",
                        "/outputs/0/requirements/build/10",
                        DependencySection.BUILD,
                        MatchSpec("sed"),
                        SelectorParser("[osx and arm64]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "libprotobuf",
                        "/outputs/0/requirements/host/0",
                        DependencySection.HOST,
                        MatchSpec("zlib"),
                        selector=None,
                    ),
                    Dependency(
                        "libprotobuf",
                        "/outputs/0/requirements/run/0",
                        DependencySection.RUN,
                        MatchSpec("zlib"),
                        selector=None,
                    ),
                    Dependency(
                        "libprotobuf",
                        "/requirements/build/0",
                        DependencySection.BUILD,
                        MatchSpec("patch"),
                        SelectorParser("[linux]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "libprotobuf",
                        "/requirements/build/1",
                        DependencySection.BUILD,
                        MatchSpec("sed"),
                        SelectorParser("[osx and arm64]", SchemaVersion.V0),
                    ),
                ],
                "libprotobuf-static": [
                    Dependency(
                        "libprotobuf-static",
                        "/outputs/1/requirements/build/0",
                        DependencySection.BUILD,
                        DependencyVariable("{{ compiler('c') }}"),
                        selector=None,
                    ),
                    Dependency(
                        "libprotobuf-static",
                        "/outputs/1/requirements/build/1",
                        DependencySection.BUILD,
                        DependencyVariable("{{ compiler('cxx') }}"),
                        selector=None,
                    ),
                    Dependency(
                        "libprotobuf-static",
                        "/outputs/1/requirements/build/2",
                        DependencySection.BUILD,
                        MatchSpec("cmake"),
                        SelectorParser("win", SchemaVersion.V0),
                    ),
                    Dependency(
                        "libprotobuf-static",
                        "/outputs/1/requirements/build/3",
                        DependencySection.BUILD,
                        MatchSpec("ninja"),
                        SelectorParser("win", SchemaVersion.V0),
                    ),
                    Dependency(
                        "libprotobuf-static",
                        "/outputs/1/requirements/build/4",
                        DependencySection.BUILD,
                        MatchSpec("autoconf"),
                        SelectorParser("[not win]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "libprotobuf-static",
                        "/outputs/1/requirements/build/5",
                        DependencySection.BUILD,
                        MatchSpec("automake"),
                        SelectorParser("[not win]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "libprotobuf-static",
                        "/outputs/1/requirements/build/6",
                        DependencySection.BUILD,
                        MatchSpec("libtool"),
                        SelectorParser("[not win]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "libprotobuf-static",
                        "/outputs/1/requirements/build/7",
                        DependencySection.BUILD,
                        MatchSpec("pkg-config"),
                        SelectorParser("[not win]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "libprotobuf-static",
                        "/outputs/1/requirements/build/8",
                        DependencySection.BUILD,
                        MatchSpec("unzip"),
                        SelectorParser("[not win]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "libprotobuf-static",
                        "/outputs/1/requirements/build/9",
                        DependencySection.BUILD,
                        MatchSpec("make"),
                        SelectorParser("[not win]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "libprotobuf-static",
                        "/outputs/1/requirements/host/0",
                        DependencySection.HOST,
                        MatchSpec("zlib"),
                        SelectorParser("[not win]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "libprotobuf-static",
                        "/outputs/1/requirements/host/1",
                        DependencySection.HOST,
                        DependencyVariable("{{ pin_subpackage('libprotobuf', exact=True) }}"),
                        SelectorParser("[not win]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "libprotobuf-static",
                        "/outputs/1/requirements/run/0",
                        DependencySection.RUN,
                        MatchSpec("zlib"),
                        SelectorParser("[not win]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "libprotobuf-static",
                        "/outputs/1/requirements/run/1",
                        DependencySection.RUN,
                        DependencyVariable("{{ pin_subpackage('libprotobuf', exact=True) }}"),
                        SelectorParser("[not win]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "libprotobuf-static",
                        "/outputs/1/requirements/run_constrained/0",
                        DependencySection.RUN_CONSTRAINTS,
                        MatchSpec("libprotobuf[version='<0a0']"),
                        SelectorParser("[win]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "libprotobuf-static",
                        "/requirements/build/0",
                        DependencySection.BUILD,
                        MatchSpec("patch"),
                        SelectorParser("[linux]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "libprotobuf-static",
                        "/requirements/build/1",
                        DependencySection.BUILD,
                        MatchSpec("sed"),
                        SelectorParser("[osx and arm64]", SchemaVersion.V0),
                    ),
                ],
                "libprotobuf-suite": [
                    Dependency(
                        "libprotobuf-suite",
                        "/requirements/build/0",
                        DependencySection.BUILD,
                        MatchSpec("patch"),
                        SelectorParser("[linux]", SchemaVersion.V0),
                    ),
                    Dependency(
                        "libprotobuf-suite",
                        "/requirements/build/1",
                        DependencySection.BUILD,
                        MatchSpec("sed"),
                        SelectorParser("[osx and arm64]", SchemaVersion.V0),
                    ),
                ],
            },
        ),
    ],
)
def test_get_all_dependencies(file: str, expected: DependencyMap) -> None:
    """
    Validates generating all the dependency meta data associated with a recipe file.

    :param file: File to test against
    :param expected: Expected output
    """
    parser = load_recipe(file, RecipeReaderDeps)
    assert parser.get_all_dependencies() == expected
