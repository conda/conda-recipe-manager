"""
:Description: Unit tests for the RecipeReader class
"""

from __future__ import annotations

from typing import Final

import pytest

from conda_recipe_manager.parser._node_var import NodeVar
from conda_recipe_manager.parser.enums import SchemaVersion
from conda_recipe_manager.parser.recipe_parser import RecipeReader
from conda_recipe_manager.types import JsonType, Primitives
from tests.constants import SIMPLE_DESCRIPTION
from tests.file_loading import load_file, load_recipe

# Multiline string used to validate interpretation of the various multiline variations YAML allows
QUICK_FOX_PIPE: Final[str] = "The quick brown\n{{fox}}\n\njumped over the lazy dog\n"
QUICK_FOX_PIPE_PLUS: Final[str] = "The quick brown\n{{fox}}\n\njumped over the lazy dog\n"
QUICK_FOX_PIPE_MINUS: Final[str] = "The quick brown\n{{fox}}\n\njumped over the lazy dog"
QUICK_FOX_R_ANGLE: Final[str] = "The quick brown {{fox}}\njumped over the lazy dog\n"
QUICK_FOX_R_ANGLE_PLUS: Final[str] = "The quick brown {{fox}}\njumped over the lazy dog\n"
QUICK_FOX_R_ANGLE_MINUS: Final[str] = "The quick brown {{fox}}\njumped over the lazy dog"
# Substitution variants of the multiline string
QUICK_FOX_SUB_PIPE: Final[str] = "The quick brown\ntiger\n\njumped over the lazy dog\n"
QUICK_FOX_SUB_PIPE_PLUS: Final[str] = "The quick brown\ntiger\n\njumped over the lazy dog\n"
QUICK_FOX_SUB_PIPE_MINUS: Final[str] = "The quick brown\ntiger\n\njumped over the lazy dog"
QUICK_FOX_L_ANGLE: Final[str] = "The quick brown tiger\njumped over the lazy dog\n"
QUICK_FOX_L_ANGLE_PLUS: Final[str] = "The quick brown tiger\njumped over the lazy dog\n"
QUICK_FOX_L_ANGLE_MINUS: Final[str] = "The quick brown tiger\njumped over the lazy dog"


## Construction and rendering sanity checks ##


@pytest.mark.parametrize(
    "file,schema_version",
    [
        ("types-toml.yaml", SchemaVersion.V0),
        ("v1_format/v1_types-toml.yaml", SchemaVersion.V1),
    ],
)
def test_construction(file: str, schema_version: SchemaVersion) -> None:
    """
    Tests the construction of a recipe parser instance with a simple, common example file.

    :param file: Recipe file to test with
    :param schema_version: Schema version to match
    """
    types_toml = load_file(file)
    parser = RecipeReader(types_toml)
    assert parser._init_content == types_toml  # pylint: disable=protected-access
    assert parser._vars_tbl == {  # pylint: disable=protected-access
        "name": NodeVar("types-toml", None),
        "version": NodeVar("0.10.8.6", None),
    }
    assert parser.get_schema_version() == schema_version
    assert not parser.is_modified()
    # TODO assert on selectors table

    # TODO assert on tree structure
    # assert parser._root == TODO


@pytest.mark.parametrize(
    "file,out_file",
    [
        ("simple-recipe.yaml", "simple-recipe_to_str.out"),
        ("v1_format/v1_simple-recipe.yaml", "v1_format/v1_simple-recipe_to_str.out"),
    ],
)
def test_str(file: str, out_file: str) -> None:
    """
    Tests rendering to a debug string

    :param file: Recipe file to test with
    :param out_file: Output string to match
    """
    parser = load_recipe(file, RecipeReader)
    assert str(parser) == load_file(out_file)
    # Regression test: Run a function a second time to ensure that `SelectorInfo::__str__()` doesn't accidentally purge
    # the underlying stack when the string is being rendered.
    assert str(parser) == load_file(out_file)
    assert not parser.is_modified()


@pytest.mark.parametrize(
    "file,other_file",
    [
        ("simple-recipe.yaml", "types-toml.yaml"),
        ("v1_format/v1_simple-recipe.yaml", "v1_format/v1_types-toml.yaml"),
        ("v1_format/v1_simple-recipe.yaml", "simple-recipe.yaml"),
    ],
)
def test_eq(file: str, other_file: str) -> None:
    """
    Tests equivalency function

    :param file: Recipe file to test with
    :param other_file: "Other" recipe file to check against
    """
    parser0 = load_recipe(file, RecipeReader)
    parser1 = load_recipe(file, RecipeReader)
    parser2 = load_recipe(other_file, RecipeReader)
    assert parser0 == parser1
    assert parser0 != parser2
    assert not parser0.is_modified()
    assert not parser1.is_modified()
    assert not parser2.is_modified()


def test_loading_obj_in_list() -> None:
    """
    Regression test: at one point, the parser would crash loading this file, containing an object in a list.
    """
    replace = load_file("simple-recipe_test_patch_replace.yaml")
    parser = RecipeReader(replace)
    assert parser.render() == replace


@pytest.mark.parametrize(
    "file",
    [
        # V0 Recipe Files
        "types-toml.yaml",  # "Easy-difficulty" recipe, representative of common/simple recipes.
        "simple-recipe.yaml",  # "Medium-difficulty" recipe, containing several contrived examples
        "multi-output.yaml",  # Contains a multi-output recipe
        "huggingface_hub.yaml",  # Contains a blank lines in a multiline string
        "simple-recipe_multiline_strings.yaml",  # Contains multiple multiline strings, using various operators
        "curl.yaml",  # Complex, multi-output recipe
        "gsm-amzn2-aarch64.yaml",  # Regression test: Contains `- '*'` string that failed to parse
        "pytest-pep8.yaml",
        "google-cloud-cpp.yaml",
        "dynamic-linking.yaml",
        "sub_vars.yaml",
        "h5py.yaml",  # `numpy {{ numpy }}` regression example.
        # TODO Fix: string quotes around concatenation are not correct when round-tripped.
        "x264.yaml",
        "parser_regressions/issue-366_quote_regressions_round_trip.yaml",
        "parser_regressions/issue-378_colon_quote_regression.yaml",
        # V1 Recipe Files
        "v1_format/v1_types-toml.yaml",
        "v1_format/v1_simple-recipe.yaml",
        "v1_format/v1_multi-output.yaml",
        "v1_format/v1_huggingface_hub.yaml",
        "v1_format/v1_curl.yaml",
        "v1_format/v1_pytest-pep8.yaml",
        "v1_format/v1_google-cloud-cpp.yaml",
        "v1_format/v1_dynamic-linking.yaml",
        "v1_format/v1_sub_vars.yaml",
        "parser_regressions/v1_format/v1_issue-366_quote_regressions.yaml",
        "parser_regressions/v1_format/v1_issue-378_colon_quote_regression.yaml",
    ],
)
def test_round_trip(file: str) -> None:
    """
    Test "eating our own dog food"/round-tripping the parser: Take a recipe, construct a parser, re-render and
    ensure the output matches the input.
    """
    expected: Final[str] = load_file(file)
    parser = RecipeReader(expected)
    assert parser.render() == expected


@pytest.mark.parametrize(
    "file,substitute,expected",
    [
        # V0 Recipes
        (
            "simple-recipe.yaml",
            False,
            {
                "about": {
                    "description": SIMPLE_DESCRIPTION,
                    "license": "Apache-2.0 AND MIT",
                    "summary": "This is a small recipe for testing",
                },
                "test_var_usage": {
                    "foo": "{{ version }}",
                    "bar": [
                        "baz",
                        "{{ zz_non_alpha_first }}",
                        "blah",
                        "This {{ name }} is silly",
                        "last",
                    ],
                },
                "build": {"is_true": True, "skip": True, "number": 0},
                "package": {"name": "{{ name|lower }}"},
                "requirements": {
                    "empty_field1": None,
                    "host": ["setuptools", "fakereq"],
                    "empty_field2": None,
                    "run": ["python"],
                    "empty_field3": None,
                },
                "multi_level": {
                    "list_3": ["ls", "sl", "cowsay"],
                    "list_2": ["cat", "bat", "mat"],
                    "list_1": ["foo", "bar"],
                },
            },
        ),
        (
            "simple-recipe.yaml",
            True,
            {
                "about": {
                    "description": SIMPLE_DESCRIPTION,
                    "license": "Apache-2.0 AND MIT",
                    "summary": "This is a small recipe for testing",
                },
                "test_var_usage": {
                    "foo": "0.10.8.6",
                    "bar": [
                        "baz",
                        42,
                        "blah",
                        "This types-toml is silly",
                        "last",
                    ],
                },
                "build": {"is_true": True, "skip": True, "number": 0},
                "package": {"name": "types-toml"},
                "requirements": {
                    "empty_field1": None,
                    "host": ["setuptools", "fakereq"],
                    "empty_field2": None,
                    "run": ["python"],
                    "empty_field3": None,
                },
                "multi_level": {
                    "list_3": ["ls", "sl", "cowsay"],
                    "list_2": ["cat", "bat", "mat"],
                    "list_1": ["foo", "bar"],
                },
            },
        ),
        (
            "simple-recipe_multiline_strings.yaml",
            False,
            {
                "about": {
                    "description0": QUICK_FOX_PIPE,
                    "description1": QUICK_FOX_PIPE_PLUS,
                    "description2": QUICK_FOX_PIPE_MINUS,
                    "description3": QUICK_FOX_R_ANGLE,
                    "description4": QUICK_FOX_R_ANGLE_PLUS,
                    "description5": QUICK_FOX_R_ANGLE_MINUS,
                    "license": "Apache-2.0 AND MIT",
                    "summary": "This is a small recipe for testing",
                },
                "test_var_usage": {
                    "foo": "{{ version }}",
                    "bar": [
                        "baz",
                        "{{ zz_non_alpha_first }}",
                        "blah",
                        "This {{ name }} is silly",
                        "last",
                    ],
                },
                "build": {"is_true": True, "skip": True, "number": 0},
                "package": {"name": "{{ name|lower }}"},
            },
        ),
        (
            "simple-recipe_multiline_strings.yaml",
            True,
            {
                "about": {
                    "description0": QUICK_FOX_SUB_PIPE,
                    "description1": QUICK_FOX_SUB_PIPE_PLUS,
                    "description2": QUICK_FOX_SUB_PIPE_MINUS,
                    "description3": QUICK_FOX_L_ANGLE,
                    "description4": QUICK_FOX_L_ANGLE_PLUS,
                    "description5": QUICK_FOX_L_ANGLE_MINUS,
                    "license": "Apache-2.0 AND MIT",
                    "summary": "This is a small recipe for testing",
                },
                "test_var_usage": {
                    "foo": "0.10.8.6",
                    "bar": [
                        "baz",
                        42,
                        "blah",
                        "This types-toml is silly",
                        "last",
                    ],
                },
                "build": {"is_true": True, "skip": True, "number": 0},
                "package": {"name": "types-toml"},
            },
        ),
    ],
)
def test_render_to_object(file: str, substitute: bool, expected: JsonType) -> None:
    """
    Tests rendering a recipe to an object format.
    TODO: Does not work with V1 recipes; if/then selectors crash with KeyError

    :param file: File to load and test against
    :param substitute: True to run the function with JINJA substitutions on, False for off
    :param expected: Expected value to return
    """
    parser = load_recipe(file, RecipeReader)
    assert parser.render_to_object(substitute) == expected


def test_render_to_object_multi_output() -> None:
    """
    Tests rendering a recipe to an object format.
    """
    parser = load_recipe("multi-output.yaml", RecipeReader)
    assert parser.render_to_object() == {
        "outputs": [
            {
                "name": "libdb",
                "build": {
                    "run_exports": ["bar"],
                },
                "test": {
                    "commands": [
                        "test -f ${PREFIX}/lib/libdb${SHLIB_EXT}",
                        r"if not exist %LIBRARY_BIN%\libdb%SHLIB_EXT%",
                    ],
                },
            },
            {
                "name": "db",
                "requirements": {
                    "build": [
                        "foo3",
                        "foo2",
                        "{{ compiler('c') }}",
                        "{{ compiler('cxx') }}",
                    ],
                    "run": ["foo"],
                },
                "test": {
                    "commands": [
                        "db_archive -m hello",
                    ]
                },
            },
        ]
    }


## Values ##


@pytest.mark.parametrize(
    "file,expected",
    [
        (
            "simple-recipe.yaml",
            [
                "/package/name",
                "/build/number",
                "/build/skip",
                "/build/is_true",
                "/requirements/empty_field1",
                "/requirements/host/0",
                "/requirements/host/1",
                "/requirements/empty_field2",
                "/requirements/run/0",
                "/requirements/empty_field3",
                "/about/summary",
                "/about/description",
                "/about/license",
                "/multi_level/list_1/0",
                "/multi_level/list_1/1",
                "/multi_level/list_2/0",
                "/multi_level/list_2/1",
                "/multi_level/list_2/2",
                "/multi_level/list_3/0",
                "/multi_level/list_3/1",
                "/multi_level/list_3/2",
                "/test_var_usage/foo",
                "/test_var_usage/bar/0",
                "/test_var_usage/bar/1",
                "/test_var_usage/bar/2",
                "/test_var_usage/bar/3",
                "/test_var_usage/bar/4",
            ],
        ),
        (
            "v1_format/v1_simple-recipe.yaml",
            [
                "/schema_version",
                "/context/zz_non_alpha_first",
                "/context/name",
                "/context/version",
                "/package/name",
                "/build/number",
                "/build/skip",
                "/build/is_true",
                "/requirements/empty_field1",
                "/requirements/host/0/if",
                "/requirements/host/0/then",
                "/requirements/host/1/if",
                "/requirements/host/1/then",
                "/requirements/empty_field2",
                "/requirements/run/0",
                "/requirements/empty_field3",
                "/about/summary",
                "/about/description",
                "/about/license",
                "/multi_level/list_1/0",
                "/multi_level/list_1/1",
                "/multi_level/list_2/0",
                "/multi_level/list_2/1",
                "/multi_level/list_2/2",
                "/multi_level/list_3/0",
                "/multi_level/list_3/1",
                "/multi_level/list_3/2",
                "/test_var_usage/foo",
                "/test_var_usage/bar/0",
                "/test_var_usage/bar/1",
                "/test_var_usage/bar/2",
                "/test_var_usage/bar/3",
                "/test_var_usage/bar/4",
            ],
        ),
    ],
)
def test_list_value_paths(file: str, expected: list[str]) -> None:
    """
    Tests retrieval of all value paths

    :param file: Recipe file to test with
    :param expected: Expected result
    """
    parser = load_recipe(file, RecipeReader)
    assert parser.list_value_paths() == expected


@pytest.mark.parametrize(
    "file,path,expected",
    [
        ## simple-recipe.yaml ##
        ("simple-recipe.yaml", "/schema_version", False),
        ("simple-recipe.yaml", "/build/number", True),
        ("simple-recipe.yaml", "/build/number/", True),
        ("simple-recipe.yaml", "/build", True),
        ("simple-recipe.yaml", "/requirements/host/0", True),
        ("simple-recipe.yaml", "/requirements/host/1", True),
        ("simple-recipe.yaml", "/multi_level/list_1/1", True),  # Comments in lists could throw-off array indexing
        ("simple-recipe.yaml", "/invalid/fake/path", False),
        ## multi-output.yaml ##
        ("multi-output.yaml", "/outputs/0/build/run_exports", True),
        ("multi-output.yaml", "/outputs/1/build/run_exports", False),
        ("multi-output.yaml", "/outputs/1/requirements/0", False),  # Should fail as this is an object, not a list
        ("multi-output.yaml", "/outputs/1/requirements/build/0", True),
        ("multi-output.yaml", "/outputs/1/requirements/build/1", True),
        ("multi-output.yaml", "/outputs/1/requirements/build/2", True),
        ("multi-output.yaml", "/outputs/1/requirements/build/3", True),
        ("multi-output.yaml", "/outputs/1/requirements/build/4", False),
        ## v1_simple-recipe.yaml ##
        ("v1_format/v1_simple-recipe.yaml", "/schema_version", True),
        ("v1_format/v1_simple-recipe.yaml", "/build/number", True),
        ("v1_format/v1_simple-recipe.yaml", "/build/number/", True),
        ("v1_format/v1_simple-recipe.yaml", "/build", True),
        ("v1_format/v1_simple-recipe.yaml", "/requirements/host/0", True),
        ("v1_format/v1_simple-recipe.yaml", "/requirements/host/1", True),
        (
            "v1_format/v1_simple-recipe.yaml",
            "/multi_level/list_1/1",
            True,
        ),  # Comments in lists could throw-off array indexing
        ("v1_format/v1_simple-recipe.yaml", "/invalid/fake/path", False),
    ],
)
def test_contains_value(file: str, path: str, expected: bool) -> None:
    """
    Tests if a path exists in a parsed recipe file.

    :param file: File to work against
    :param path: Target input path
    :param expected: Expected result of the test
    """
    parser = load_recipe(file, RecipeReader)
    assert parser.contains_value(path) == expected
    assert not parser.is_modified()


@pytest.mark.parametrize(
    "file,path,sub_vars,expected",
    [
        ## simple-recipe.yaml ##
        # Return a single value
        ("simple-recipe.yaml", "/build/number", False, 0),
        ("simple-recipe.yaml", "/build/number/", False, 0),
        # Return a compound value
        (
            "simple-recipe.yaml",
            "/build",
            False,
            {
                "number": 0,
                "skip": True,
                "is_true": True,
            },
        ),
        (
            "simple-recipe.yaml",
            "/build/",
            False,
            {
                "number": 0,
                "skip": True,
                "is_true": True,
            },
        ),
        # Return a Jinja value
        ("simple-recipe.yaml", "/package/name", False, "{{ name|lower }}"),
        ("simple-recipe.yaml", "/package/name", True, "types-toml"),
        ("simple-recipe.yaml", "/test_var_usage/foo", False, "{{ version }}"),
        ("simple-recipe.yaml", "/test_var_usage/foo", True, "0.10.8.6"),
        ("simple-recipe.yaml", "/test_var_usage/bar/1", False, "{{ zz_non_alpha_first }}"),
        ("simple-recipe.yaml", "/test_var_usage/bar/1", True, 42),
        # Return a value in a list
        ("simple-recipe.yaml", "/requirements/host", False, ["setuptools", "fakereq"]),
        ("simple-recipe.yaml", "/requirements/host/", False, ["setuptools", "fakereq"]),
        ("simple-recipe.yaml", "/requirements/host", True, ["setuptools", "fakereq"]),
        ("simple-recipe.yaml", "/requirements/host/0", False, "setuptools"),
        ("simple-recipe.yaml", "/requirements/host/1", False, "fakereq"),
        # Regression: A list containing 1 value may be interpreted as the base type by YAML parsers. This can wreak
        # havoc on type safety.
        ("simple-recipe.yaml", "/requirements/run", False, ["python"]),
        # Return a multiline string
        ("simple-recipe.yaml", "/about/description", False, SIMPLE_DESCRIPTION),
        ("simple-recipe.yaml", "/about/description/", False, SIMPLE_DESCRIPTION),
        # Comments in lists could throw-off array indexing
        ("simple-recipe.yaml", "/multi_level/list_1/1", False, "bar"),
        # Render a recursive, complex type.
        (
            "simple-recipe.yaml",
            "/test_var_usage",
            False,
            {
                "foo": "{{ version }}",
                "bar": [
                    "baz",
                    "{{ zz_non_alpha_first }}",
                    "blah",
                    "This {{ name }} is silly",
                    "last",
                ],
            },
        ),
        (
            "simple-recipe.yaml",
            "/test_var_usage",
            True,
            {
                "foo": "0.10.8.6",
                "bar": [
                    "baz",
                    42,
                    "blah",
                    "This types-toml is silly",
                    "last",
                ],
            },
        ),
        (
            "simple-recipe.yaml",
            "/test_var_usage/bar",
            True,
            [
                "baz",
                42,
                "blah",
                "This types-toml is silly",
                "last",
            ],
        ),
        ## simple-recipe_multiline_strings.yaml ##
        # Return multiline string variants
        ("simple-recipe_multiline_strings.yaml", "/about/description0", False, QUICK_FOX_PIPE),
        ("simple-recipe_multiline_strings.yaml", "/about/description1", False, QUICK_FOX_PIPE_PLUS),
        ("simple-recipe_multiline_strings.yaml", "/about/description2", False, QUICK_FOX_PIPE_MINUS),
        ("simple-recipe_multiline_strings.yaml", "/about/description3", False, QUICK_FOX_R_ANGLE),
        ("simple-recipe_multiline_strings.yaml", "/about/description4", False, QUICK_FOX_R_ANGLE_PLUS),
        ("simple-recipe_multiline_strings.yaml", "/about/description5", False, QUICK_FOX_R_ANGLE_MINUS),
        # Return multiline string variants, with substitution
        ("simple-recipe_multiline_strings.yaml", "/about/description0", True, QUICK_FOX_SUB_PIPE),
        ("simple-recipe_multiline_strings.yaml", "/about/description1", True, QUICK_FOX_SUB_PIPE_PLUS),
        ("simple-recipe_multiline_strings.yaml", "/about/description2", True, QUICK_FOX_SUB_PIPE_MINUS),
        ("simple-recipe_multiline_strings.yaml", "/about/description3", True, QUICK_FOX_L_ANGLE),
        ("simple-recipe_multiline_strings.yaml", "/about/description4", True, QUICK_FOX_L_ANGLE_PLUS),
        ("simple-recipe_multiline_strings.yaml", "/about/description5", True, QUICK_FOX_L_ANGLE_MINUS),
        ## types-toml.yaml ##
        # Regression: `{ name[0] }` could not be evaluated.
        (
            "types-toml.yaml",
            "/source/url",
            True,
            "https://pypi.io/packages/source/t/types-toml/types-toml-0.10.8.6.tar.gz",
        ),
        (
            "types-toml.yaml",
            "/source",
            True,
            {
                "url": "https://pypi.io/packages/source/t/types-toml/types-toml-0.10.8.6.tar.gz",
                "sha256": "6d3ac79e36c9ee593c5d4fb33a50cca0e3adceb6ef5cff8b8e5aef67b4c4aaf2",
            },
        ),
        ## sub_vars.yaml ##
        (
            "sub_vars.yaml",
            "/package/name",
            True,
            "types-toml",
        ),
        (
            "sub_vars.yaml",
            "/source/url",
            True,
            "https://pypi.io/packages/source/t/TYPES-TOML/types-toml-6.tar.gz",
        ),
        (
            "sub_vars.yaml",
            "/source",
            True,
            {
                "url": "https://pypi.io/packages/source/t/TYPES-TOML/types-toml-6.tar.gz",
                "sha256": "6d3ac79e36c9ee593c5d4fb33a50cca0e3adceb6ef5cff8b8e5aef67b4c4aaf2",
            },
        ),
        # Add/concat cases
        ("sub_vars.yaml", "/requirements/fake_run_constrained/0", True, 43),
        ("sub_vars.yaml", "/requirements/fake_run_constrained/1", True, 43.3),
        ("sub_vars.yaml", "/requirements/fake_run_constrained/2", True, "421"),
        ("sub_vars.yaml", "/requirements/fake_run_constrained/3", True, "421.3"),
        ("sub_vars.yaml", "/requirements/fake_run_constrained/4", True, 43),
        ("sub_vars.yaml", "/requirements/fake_run_constrained/5", True, 43.3),
        ("sub_vars.yaml", "/requirements/fake_run_constrained/6", True, "142"),
        ("sub_vars.yaml", "/requirements/fake_run_constrained/7", True, "1.342"),
        ("sub_vars.yaml", "/requirements/fake_run_constrained/8", True, "0.10.8.61.3"),
        ("sub_vars.yaml", "/requirements/fake_run_constrained/9", True, "0.10.8.61.3"),
        ("sub_vars.yaml", "/requirements/fake_run_constrained/10", True, "1.30.10.8.6"),
        ("sub_vars.yaml", "/requirements/fake_run_constrained/11", True, "1.30.10.8.6"),
        ("sub_vars.yaml", "/requirements/fake_run_constrained/12", True, 6),
        ("sub_vars.yaml", "/requirements/fake_run_constrained/13", True, "42"),
        ("sub_vars.yaml", "/requirements/fake_run_constrained/14", True, "dne42"),
        ("sub_vars.yaml", "/requirements/fake_run_constrained/15", True, 'foo > "42"'),
        ("sub_vars.yaml", "/requirements/fake_run_constrained/16", True, "foo > 6"),
        # Replace cases
        ("sub_vars.yaml", "/requirements/fake_run_constrained/17", True, "TYPES_toml"),
        ("sub_vars.yaml", "/requirements/fake_run_constrained/18", True, "types_toml"),
        ("sub_vars.yaml", "/requirements/fake_run_constrained/19", True, "TYPES_toml"),
        ("sub_vars.yaml", "/requirements/fake_run_constrained/20", True, "types_toml"),
        ("sub_vars.yaml", "/requirements/fake_run_constrained/21", True, "TYPES_TOML"),
        # Complex split and join cases. Note that we do not replace if split/join would result in a non-string value.
        ("sub_vars.yaml", "/requirements/fake_run_constrained/22", True, "{{ name.split('-') }}"),
        ("sub_vars.yaml", "/requirements/fake_run_constrained/23", True, "{{ '.'.join(name) }}"),
        ("sub_vars.yaml", "/requirements/fake_run_constrained/24", True, "TYPES.toml"),
        ("sub_vars.yaml", "/requirements/fake_run_constrained/25", True, "TYPES"),
        ("sub_vars.yaml", "/requirements/fake_run_constrained/26", True, "TYPES.toml"),
        ("sub_vars.yaml", "/requirements/fake_run_constrained/27", True, "l"),
        ("sub_vars.yaml", "/requirements/fake_run_constrained/28", True, "T"),
        ("sub_vars.yaml", "/requirements/fake_run_constrained/29", True, "TYPES-toml"),
        ## v1_simple-recipe.yaml ##
        ("v1_format/v1_simple-recipe.yaml", "/build/number", False, 0),
        ("v1_format/v1_simple-recipe.yaml", "/build/number/", False, 0),
        (
            "v1_format/v1_simple-recipe.yaml",
            "/build",
            False,
            {
                "number": 0,
                "skip": 'match(python, "<3.7")',
                "is_true": True,
            },
        ),
        (
            "v1_format/v1_simple-recipe.yaml",
            "/build/",
            False,
            {
                "number": 0,
                "skip": 'match(python, "<3.7")',
                "is_true": True,
            },
        ),
        ("v1_format/v1_simple-recipe.yaml", "/package/name", False, "${{ name|lower }}"),
        ("v1_format/v1_simple-recipe.yaml", "/package/name", True, "types-toml"),
        ("v1_format/v1_simple-recipe.yaml", "/test_var_usage/foo", False, "${{ version }}"),
        ("v1_format/v1_simple-recipe.yaml", "/test_var_usage/foo", True, "0.10.8.6"),
        ("v1_format/v1_simple-recipe.yaml", "/test_var_usage/bar/1", False, "${{ zz_non_alpha_first }}"),
        ("v1_format/v1_simple-recipe.yaml", "/test_var_usage/bar/1", True, 42),
        (
            "v1_format/v1_simple-recipe.yaml",
            "/requirements/host",
            False,
            [{"if": "unix", "then": "setuptools"}, {"if": "unix", "then": "fakereq"}],
        ),
        (
            "v1_format/v1_simple-recipe.yaml",
            "/requirements/host/",
            False,
            [{"if": "unix", "then": "setuptools"}, {"if": "unix", "then": "fakereq"}],
        ),
        (
            "v1_format/v1_simple-recipe.yaml",
            "/requirements/host",
            True,
            [{"if": "unix", "then": "setuptools"}, {"if": "unix", "then": "fakereq"}],
        ),
        # TODO fix V1_SUPPORT: yaml.parser.ParserError: while parsing a block collection
        # ("v1_format/v1_simple-recipe.yaml", "/requirements/host/0", False, {"if": "unix", "then": "setuptools"}),
        # ("v1_format/v1_simple-recipe.yaml", "/requirements/host/1", False, {"if": "unix", "then": "fakereq"}),
        ("v1_format/v1_simple-recipe.yaml", "/requirements/host/0/then", False, "setuptools"),
        ("v1_format/v1_simple-recipe.yaml", "/requirements/host/1/then", False, "fakereq"),
        ("v1_format/v1_simple-recipe.yaml", "/requirements/run", False, ["python"]),
        ("v1_format/v1_simple-recipe.yaml", "/about/description", False, SIMPLE_DESCRIPTION),
        ("v1_format/v1_simple-recipe.yaml", "/about/description/", False, SIMPLE_DESCRIPTION),
        ("v1_format/v1_simple-recipe.yaml", "/multi_level/list_1/1", False, "bar"),
        (
            "v1_format/v1_simple-recipe.yaml",
            "/test_var_usage",
            False,
            {
                "foo": "${{ version }}",
                "bar": [
                    "baz",
                    "${{ zz_non_alpha_first }}",
                    "blah",
                    "This ${{ name }} is silly",
                    "last",
                ],
            },
        ),
        (
            "v1_format/v1_simple-recipe.yaml",
            "/test_var_usage",
            True,
            {
                "foo": "0.10.8.6",
                "bar": [
                    "baz",
                    42,
                    "blah",
                    "This types-toml is silly",
                    "last",
                ],
            },
        ),
        (
            "v1_format/v1_simple-recipe.yaml",
            "/test_var_usage/bar",
            True,
            [
                "baz",
                42,
                "blah",
                "This types-toml is silly",
                "last",
            ],
        ),
        ## v1_types-toml.yaml ##
        # Regression: `{ name[0] }` could not be evaluated.
        (
            "v1_format/v1_types-toml.yaml",
            "/source/url",
            True,
            "https://pypi.io/packages/source/t/types-toml/types-toml-0.10.8.6.tar.gz",
        ),
        (
            "v1_format/v1_types-toml.yaml",
            "/source",
            True,
            {
                "url": "https://pypi.io/packages/source/t/types-toml/types-toml-0.10.8.6.tar.gz",
                "sha256": "6d3ac79e36c9ee593c5d4fb33a50cca0e3adceb6ef5cff8b8e5aef67b4c4aaf2",
            },
        ),
        ## v1_sub_vars.yaml ##
        (
            "v1_format/v1_sub_vars.yaml",
            "/package/name",
            True,
            "types-toml",
        ),
        (
            "v1_format/v1_sub_vars.yaml",
            "/source/url",
            True,
            "https://pypi.io/packages/source/t/TYPES-TOML/types-toml-6.tar.gz",
        ),
        (
            "v1_format/v1_sub_vars.yaml",
            "/source",
            True,
            {
                "url": "https://pypi.io/packages/source/t/TYPES-TOML/types-toml-6.tar.gz",
                "sha256": "6d3ac79e36c9ee593c5d4fb33a50cca0e3adceb6ef5cff8b8e5aef67b4c4aaf2",
            },
        ),
        # Add/concat cases
        ("v1_format/v1_sub_vars.yaml", "/requirements/fake_run_constrained/0", True, 43),
        ("v1_format/v1_sub_vars.yaml", "/requirements/fake_run_constrained/1", True, 43.3),
        ("v1_format/v1_sub_vars.yaml", "/requirements/fake_run_constrained/2", True, "421"),
        ("v1_format/v1_sub_vars.yaml", "/requirements/fake_run_constrained/3", True, "421.3"),
        ("v1_format/v1_sub_vars.yaml", "/requirements/fake_run_constrained/4", True, 43),
        ("v1_format/v1_sub_vars.yaml", "/requirements/fake_run_constrained/5", True, 43.3),
        ("v1_format/v1_sub_vars.yaml", "/requirements/fake_run_constrained/6", True, "142"),
        ("v1_format/v1_sub_vars.yaml", "/requirements/fake_run_constrained/7", True, "1.342"),
        ("v1_format/v1_sub_vars.yaml", "/requirements/fake_run_constrained/8", True, "0.10.8.61.3"),
        ("v1_format/v1_sub_vars.yaml", "/requirements/fake_run_constrained/9", True, "0.10.8.61.3"),
        ("v1_format/v1_sub_vars.yaml", "/requirements/fake_run_constrained/10", True, "1.30.10.8.6"),
        ("v1_format/v1_sub_vars.yaml", "/requirements/fake_run_constrained/11", True, "1.30.10.8.6"),
        ("v1_format/v1_sub_vars.yaml", "/requirements/fake_run_constrained/12", True, 6),
        ("v1_format/v1_sub_vars.yaml", "/requirements/fake_run_constrained/13", True, "42"),
        ("v1_format/v1_sub_vars.yaml", "/requirements/fake_run_constrained/14", True, "dne42"),
        ("v1_format/v1_sub_vars.yaml", "/requirements/fake_run_constrained/15", True, 'foo > "42"'),
        ("v1_format/v1_sub_vars.yaml", "/requirements/fake_run_constrained/16", True, "foo > 6"),
        # Replace cases
        ("v1_format/v1_sub_vars.yaml", "/requirements/fake_run_constrained/17", True, "TYPES_toml"),
        ("v1_format/v1_sub_vars.yaml", "/requirements/fake_run_constrained/18", True, "types_toml"),
        ("v1_format/v1_sub_vars.yaml", "/requirements/fake_run_constrained/19", True, "TYPES_toml"),
        ("v1_format/v1_sub_vars.yaml", "/requirements/fake_run_constrained/20", True, "types_toml"),
        ("v1_format/v1_sub_vars.yaml", "/requirements/fake_run_constrained/21", True, "TYPES_TOML"),
        # Complex split and join cases. Note that we do not replace if split/join would result in a non-string value.
        ("v1_format/v1_sub_vars.yaml", "/requirements/fake_run_constrained/22", True, "${{ name.split('-') }}"),
        ("v1_format/v1_sub_vars.yaml", "/requirements/fake_run_constrained/23", True, "${{ '.'.join(name) }}"),
        ("v1_format/v1_sub_vars.yaml", "/requirements/fake_run_constrained/24", True, "TYPES.toml"),
        ("v1_format/v1_sub_vars.yaml", "/requirements/fake_run_constrained/25", True, "TYPES"),
        ("v1_format/v1_sub_vars.yaml", "/requirements/fake_run_constrained/26", True, "TYPES.toml"),
        ("v1_format/v1_sub_vars.yaml", "/requirements/fake_run_constrained/27", True, "l"),
        ("v1_format/v1_sub_vars.yaml", "/requirements/fake_run_constrained/28", True, "T"),
        ("v1_format/v1_sub_vars.yaml", "/requirements/fake_run_constrained/29", True, "TYPES-toml"),
        ## multi-output.yaml ##
        ("multi-output.yaml", "/outputs/0/build/run_exports/0", False, "bar"),
        ("multi-output.yaml", "/outputs/0/build/run_exports", False, ["bar"]),
        ("multi-output.yaml", "/outputs/0/build", False, {"run_exports": ["bar"]}),
        # TODO FIX: This case
        # (
        #    "multi-output.yaml",
        #    "/outputs/1",
        #    False,
        #    {
        #        "name": "db",
        #        "requirements": {
        #            "build": ["foo3", "foo2", "{{ compiler('c') }}", "{{ compiler('cxx') }}"],
        #            "run": ["foo"],
        #        },
        #        "test": {"commands": ["db_archive -m hello"]},
        #    },
        # ),
        ## v1_multi-output.yaml ##
        ("v1_format/v1_multi-output.yaml", "/outputs/0/requirements/run_exports/0", False, "bar"),
        ("v1_format/v1_multi-output.yaml", "/outputs/0/requirements/run_exports", False, ["bar"]),
        # TODO FIX: This case
        # ("v1_format/v1_multi-output.yaml", "/outputs/0/build", False, None),
        ("v1_format/v1_multi-output.yaml", "/outputs/0/requirements", False, {"run_exports": ["bar"]}),
    ],
)
def test_get_value(file: str, path: str, sub_vars: bool, expected: JsonType) -> None:
    """
    Tests retrieval of a value from a parsed YAML example.

    :param file: File to work against
    :param path: Target input path
    :param sub_vars: True to substitute JINJA variables. False otherwise.
    :param expected: Expected result of the test
    """
    parser = load_recipe(file, RecipeReader)
    assert parser.get_value(path, sub_vars=sub_vars) == expected
    assert not parser.is_modified()


@pytest.mark.parametrize("file", ["simple-recipe.yaml", "v1_format/v1_simple-recipe.yaml"])
def test_get_value_not_found(file: str) -> None:
    """
    Tests failure to retrieve a value from a parsed YAML example.

    :param file: File to work against
    """
    parser = load_recipe(file, RecipeReader)
    # Path not found cases
    with pytest.raises(KeyError):
        parser.get_value("/invalid/fake/path")
    assert parser.get_value("/invalid/fake/path", 42) == 42
    # Tests that a user can pass `None` without throwing
    assert parser.get_value("/invalid/fake/path", None) is None
    assert not parser.is_modified()


@pytest.mark.parametrize(
    "file,value,expected",
    [
        ## V0 Format ##
        (
            "simple-recipe.yaml",
            None,
            [
                "/requirements/empty_field1",
                "/requirements/empty_field2",
                "/requirements/empty_field3",
            ],
        ),
        ("simple-recipe.yaml", "fakereq", ["/requirements/host/1"]),
        ("simple-recipe.yaml", True, ["/build/skip", "/build/is_true"]),
        ("simple-recipe.yaml", "foo", ["/multi_level/list_1/0"]),
        ("simple-recipe.yaml", "Apache-2.0 AND MIT", ["/about/license"]),
        ("simple-recipe.yaml", 43, []),
        ("simple-recipe.yaml", "fooz", []),
        ("simple-recipe.yaml", "", []),
        ## V1 Format ##
        (
            "v1_format/v1_simple-recipe.yaml",
            None,
            [
                "/requirements/empty_field1",
                "/requirements/empty_field2",
                "/requirements/empty_field3",
            ],
        ),
        ("v1_format/v1_simple-recipe.yaml", "fakereq", ["/requirements/host/1/then"]),
        ("v1_format/v1_simple-recipe.yaml", True, ["/build/is_true"]),
        ("v1_format/v1_simple-recipe.yaml", "foo", ["/multi_level/list_1/0"]),
        ("v1_format/v1_simple-recipe.yaml", "Apache-2.0 AND MIT", ["/about/license"]),
        ("v1_format/v1_simple-recipe.yaml", 43, []),
        ("v1_format/v1_simple-recipe.yaml", "fooz", []),
        ("v1_format/v1_simple-recipe.yaml", "", []),
    ],
)
def test_find_value(file: str, value: Primitives, expected: list[str]) -> None:
    """
    Tests finding a value from a parsed YAML example.

    :param file: File to work against
    :param value: Target value
    :param expected: Expected result of the test
    """
    parser = load_recipe(file, RecipeReader)
    assert parser.find_value(value) == expected
    assert not parser.is_modified()


@pytest.mark.parametrize(
    "file,expected",
    [
        ## V0 Format ##
        ("types-toml.yaml", "types-toml"),
        ("boto.yaml", "boto"),
        ("cctools-ld64.yaml", "cctools-and-ld64"),
        ("multi-output.yaml", None),
        ## V1 Format ##
        ("v1_format/v1_types-toml.yaml", "types-toml"),
        ("v1_format/v1_boto.yaml", "boto"),
        ("v1_format/v1_cctools-ld64.yaml", "cctools-and-ld64"),
        ("v1_format/v1_multi-output.yaml", None),
    ],
)
def test_get_recipe_name(file: str, expected: str) -> None:
    """
    Tests finding a value from a parsed YAML example.

    :param file: File to work against
    :param expected: Expected result of the test
    """
    parser = load_recipe(file, RecipeReader)
    assert parser.get_recipe_name() == expected
    assert not parser.is_modified()


@pytest.mark.parametrize(
    "file,value",
    [
        ("simple-recipe.yaml", ["foo", "bar"]),
        ("simple-recipe.yaml", ("foo", "bar")),
        ("simple-recipe.yaml", {"foo": "bar"}),
        ("v1_format/v1_simple-recipe.yaml", ["foo", "bar"]),
        ("v1_format/v1_simple-recipe.yaml", ("foo", "bar")),
        ("v1_format/v1_simple-recipe.yaml", {"foo": "bar"}),
    ],
)
def test_find_value_raises(file: str, value: Primitives) -> None:
    """
    Tests finding a value from a parsed YAML example that should throw a `ValueError`.

    :param file: File to work against
    :param value: Target value
    """
    parser = load_recipe(file, RecipeReader)
    with pytest.raises(ValueError):
        parser.find_value(value)
    assert not parser.is_modified()


## Convenience Functions ##


@pytest.mark.parametrize(
    "file,expected",
    [
        ("multi-output.yaml", True),
        ("simple-recipe.yaml", False),
        ("types-toml.yaml", False),
        ("boto.yaml", False),
        ("cctools-ld64.yaml", True),
        ("v1_format/v1_multi-output.yaml", True),
        ("v1_format/v1_simple-recipe.yaml", False),
        ("v1_format/v1_types-toml.yaml", False),
        ("v1_format/v1_boto.yaml", False),
        ("v1_format/v1_cctools-ld64.yaml", True),
    ],
)
def test_is_multi_output(file: str, expected: bool) -> None:
    """
    Validates if a recipe is in the multi-output format

    :param file: File to test against
    :param expected: Expected output
    """
    assert load_recipe(file, RecipeReader).is_multi_output() == expected


@pytest.mark.parametrize(
    "file,expected",
    [
        ("multi-output.yaml", False),
        ("simple-recipe.yaml", False),
        ("types-toml.yaml", True),
        ("boto.yaml", True),
        ("cctools-ld64.yaml", False),
        ("v1_format/v1_multi-output.yaml", False),
        ("v1_format/v1_simple-recipe.yaml", False),
        ("v1_format/v1_types-toml.yaml", True),
        ("v1_format/v1_boto.yaml", True),
        ("v1_format/v1_cctools-ld64.yaml", False),
        # Regression test for Issue 289. Compiled projects that use Python are not "pure python" packages.
        ("parser_regressions/issue-289_regression.yaml", False),
        ("parser_regressions/v1_format/v1_issue-289_regression.yaml", False),
    ],
)
def test_is_python_recipe(file: str, expected: bool) -> None:
    """
    Validates if a recipe is a "pure Python" package.

    :param file: File to test against
    :param expected: Expected output
    """
    assert load_recipe(file, RecipeReader).is_python_recipe() == expected


@pytest.mark.parametrize(
    "file,expected",
    [
        ("multi-output.yaml", ["/", "/outputs/0", "/outputs/1"]),
        ("simple-recipe.yaml", ["/"]),
        ("simple-recipe_comment_in_requirements.yaml", ["/"]),
        ("huggingface_hub.yaml", ["/"]),
        ("v1_format/v1_simple-recipe.yaml", ["/"]),
        ("v1_format/v1_multi-output.yaml", ["/", "/outputs/0", "/outputs/1"]),
    ],
)
def test_get_package_paths(file: str, expected: list[str]) -> None:
    """
    Validates fetching paths containing recipe dependencies

    :param file: File to test against
    :param expected: Expected output
    """
    assert load_recipe(file, RecipeReader).get_package_paths() == expected


@pytest.mark.parametrize(
    "base,ext,expected",
    [
        ("", "", "/"),
        ("/", "/foo/bar", "/foo/bar"),
        ("/", "foo/bar", "/foo/bar"),
        ("/foo/bar", "baz", "/foo/bar/baz"),
        ("/foo/bar", "/baz", "/foo/bar/baz"),
    ],
)
def test_append_to_path(base: str, ext: str, expected: str) -> None:
    """
    Validates expanding recipe structure paths.

    :param base: Base string path
    :param ext: Path to extend the base path with
    :param expected: Expected output
    """
    assert RecipeReader.append_to_path(base, ext) == expected


@pytest.mark.parametrize(
    "file,expected",
    [
        (
            "multi-output.yaml",
            [
                "/outputs/1/requirements/build/0",
                "/outputs/1/requirements/build/1",
                "/outputs/1/requirements/build/2",
                "/outputs/1/requirements/build/3",
                "/outputs/1/requirements/run/0",
            ],
        ),
        ("simple-recipe.yaml", ["/requirements/host/0", "/requirements/host/1", "/requirements/run/0"]),
        (
            "simple-recipe_comment_in_requirements.yaml",
            ["/requirements/host/0", "/requirements/host/1", "/requirements/run/0"],
        ),
        (
            "cctools-ld64.yaml",
            [
                "/requirements/build/0",
                "/requirements/build/1",
                "/requirements/build/2",
                "/requirements/build/3",
                "/requirements/host/0",
                "/requirements/host/1",
                "/requirements/host/2",
                "/outputs/0/requirements/run/0",
                "/outputs/1/requirements/host/0",
                "/outputs/1/requirements/host/1",
                "/outputs/1/requirements/run/0",
                "/outputs/1/requirements/run/1",
            ],
        ),
        (
            "huggingface_hub.yaml",
            [
                "/requirements/host/0",
                "/requirements/host/1",
                "/requirements/host/2",
                "/requirements/host/3",
                "/requirements/run/0",
                "/requirements/run/1",
                "/requirements/run/2",
                "/requirements/run/3",
                "/requirements/run/4",
                "/requirements/run/5",
                "/requirements/run/6",
                "/requirements/run/7",
                "/requirements/run/8",
                "/requirements/run_constrained/0",
                "/requirements/run_constrained/1",
                "/requirements/run_constrained/2",
            ],
        ),
        (
            "v1_format/v1_multi-output.yaml",
            [
                "/outputs/1/requirements/build/0",
                "/outputs/1/requirements/build/1",
                "/outputs/1/requirements/build/2",
                "/outputs/1/requirements/build/3",
                "/outputs/1/requirements/run/0",
            ],
        ),
        ("v1_format/v1_simple-recipe.yaml", ["/requirements/host/0", "/requirements/host/1", "/requirements/run/0"]),
        (
            "v1_format/v1_cctools-ld64.yaml",
            [
                "/requirements/build/0",
                "/requirements/build/1",
                "/requirements/build/2",
                "/requirements/build/3",
                "/requirements/host/0",
                "/requirements/host/1",
                "/requirements/host/2",
                "/outputs/0/requirements/run/0",
                "/outputs/1/requirements/host/0",
                "/outputs/1/requirements/host/1",
                "/outputs/1/requirements/run/0",
                "/outputs/1/requirements/run/1",
            ],
        ),
    ],
)
def test_get_dependency_paths(file: str, expected: list[str]) -> None:
    """
    Validates fetching paths containing recipe dependencies

    :param file: File to test against
    :param expected: Expected output
    """
    assert load_recipe(file, RecipeReader).get_dependency_paths() == expected


## Variables ##


@pytest.mark.parametrize(
    "file,expected",
    [
        ("simple-recipe.yaml", ["zz_non_alpha_first", "name", "version"]),
        (
            "cctools-ld64.yaml",
            [
                "cctools_version",
                "cctools_sha256",
                "ld64_version",
                "ld64_sha256",
                "dyld_version",
                "dyld_sha256",
                "clang_version",
                "clang_sha256",
                "native_compiler_subdir",
            ],
        ),
        ("v1_format/v1_simple-recipe.yaml", ["zz_non_alpha_first", "name", "version"]),
        (
            "v1_format/v1_cctools-ld64.yaml",
            [
                "cctools_version",
                "cctools_sha256",
                "ld64_version",
                "ld64_sha256",
                "dyld_version",
                "dyld_sha256",
                "clang_version",
                "clang_sha256",
                "native_compiler_subdir",
            ],
        ),
    ],
)
def test_list_variable(file: str, expected: list[str]) -> None:
    """
    Validates the list of variables found

    :param file: File to test against
    :param expected: Expected output
    """
    parser = load_recipe(file, RecipeReader)
    assert parser.list_variables() == expected
    assert not parser.is_modified()


@pytest.mark.parametrize(
    "file,var,expected",
    [
        ("simple-recipe.yaml", "zz_non_alpha_first", True),
        ("simple-recipe.yaml", "name", True),
        ("simple-recipe.yaml", "version", True),
        ("simple-recipe.yaml", "fake_var", False),
        ("cctools-ld64.yaml", "cctools_version", True),
        ("cctools-ld64.yaml", "ld64_sha256", True),
        ("cctools-ld64.yaml", "native_compiler_subdir", True),
        ("cctools-ld64.yaml", "native_compiler_subdirs", False),
        ("v1_format/v1_simple-recipe.yaml", "zz_non_alpha_first", True),
        ("v1_format/v1_simple-recipe.yaml", "name", True),
        ("v1_format/v1_simple-recipe.yaml", "version", True),
        ("v1_format/v1_simple-recipe.yaml", "fake_var", False),
        ("v1_format/v1_cctools-ld64.yaml", "cctools_version", True),
        ("v1_format/v1_cctools-ld64.yaml", "ld64_sha256", True),
        ("v1_format/v1_cctools-ld64.yaml", "native_compiler_subdir", True),
        ("v1_format/v1_cctools-ld64.yaml", "native_compiler_subdirs", False),
    ],
)
def test_contains_variable(file: str, var: str, expected: bool) -> None:
    """
    Validates checking if a variable exists in a recipe

    :param file: File to test against
    :param var: Target JINJA variable
    :param expected: Expected output
    """
    parser = load_recipe(file, RecipeReader)
    assert parser.contains_variable(var) == expected
    assert not parser.is_modified()


@pytest.mark.parametrize(
    "file,var,expected",
    [
        ("simple-recipe.yaml", "zz_non_alpha_first", 42),
        ("simple-recipe.yaml", "name", "types-toml"),
        ("simple-recipe.yaml", "version", "0.10.8.6"),
        ("v1_format/v1_simple-recipe.yaml", "zz_non_alpha_first", 42),
        ("v1_format/v1_simple-recipe.yaml", "name", "types-toml"),
        ("v1_format/v1_simple-recipe.yaml", "version", "0.10.8.6"),
    ],
)
def test_get_variable(file: str, var: str, expected: JsonType) -> None:
    """
    Tests the value returned from fetching a variable

    :param file: File to test against
    :param var: Target JINJA variable
    :param expected: Expected output
    """
    parser = load_recipe(file, RecipeReader)
    assert parser.get_variable(var) == expected
    assert not parser.is_modified()


@pytest.mark.parametrize(
    "file",
    [
        "simple-recipe.yaml",
        "v1_format/v1_simple-recipe.yaml",
    ],
)
def test_get_variable_dne(file: str) -> None:
    """
    Tests the value returned from fetching a variable when the variable does not exist

    :param file: File to test against
    """
    parser = load_recipe(file, RecipeReader)
    with pytest.raises(KeyError):
        parser.get_variable("fake_var")
    assert parser.get_variable("fake_var", 43) == 43
    # Tests that a user can pass `None` without throwing (Python sentinel test)
    assert parser.get_variable("fake_var", None) is None
    assert not parser.is_modified()


@pytest.mark.parametrize(
    "file,var,expected",
    [
        ("simple-recipe.yaml", "version", ["/test_var_usage/foo"]),
        ("simple-recipe.yaml", "zz_non_alpha_first", ["/test_var_usage/bar/1"]),
        ("simple-recipe.yaml", "name", ["/package/name", "/test_var_usage/bar/3"]),
        ("v1_format/v1_simple-recipe.yaml", "version", ["/test_var_usage/foo"]),
        ("v1_format/v1_simple-recipe.yaml", "zz_non_alpha_first", ["/test_var_usage/bar/1"]),
        ("v1_format/v1_simple-recipe.yaml", "name", ["/package/name", "/test_var_usage/bar/3"]),
    ],
)
def test_get_variable_references(file: str, var: str, expected: list[str]) -> None:
    """
    Tests generating a list of paths that use a variable

    :param file: File to test against
    :param var: Target JINJA variable
    :param expected: Expected output
    """
    parser = load_recipe(file, RecipeReader)
    assert parser.get_variable_references(var) == expected
    assert not parser.is_modified()


## Selectors ##


def test_list_selectors() -> None:
    """
    Validates the list of selectors found
    """
    parser = load_recipe("simple-recipe.yaml", RecipeReader)
    assert parser.list_selectors() == ["[unix]", "[py<37]", "[unix and win]"]
    assert not parser.is_modified()


def test_contains_selectors() -> None:
    """
    Validates checking if a selector exists in a recipe
    """
    parser = load_recipe("simple-recipe.yaml", RecipeReader)
    assert parser.contains_selector("[py<37]")
    assert parser.contains_selector("[unix]")
    assert not parser.contains_selector("[fake selector]")
    assert not parser.is_modified()


def test_get_selector_paths() -> None:
    """
    Tests the paths returned from fetching a selector
    """
    parser = load_recipe("simple-recipe.yaml", RecipeReader)
    assert parser.get_selector_paths("[py<37]") == ["/build/skip"]
    assert parser.get_selector_paths("[unix]") == [
        "/package/name",
        "/requirements/host/0",
        "/requirements/host/1",
    ]
    assert not parser.get_selector_paths("[fake selector]")
    assert not parser.is_modified()


@pytest.mark.parametrize(
    "file,path,expected",
    [
        ("simple-recipe.yaml", "/build/skip", True),
        ("simple-recipe.yaml", "/requirements/host/0", True),
        ("simple-recipe.yaml", "/requirements/host/1", True),
        ("simple-recipe.yaml", "/requirements/empty_field2", True),
        ("simple-recipe.yaml", "/requirements/run/0", False),
        ("simple-recipe.yaml", "/requirements/run", False),
        ("simple-recipe.yaml", "/fake/path", False),
    ],
)
def test_contains_selector_at_path(file: str, path: str, expected: bool) -> None:
    """
    Tests checking if a selector exists on a given path

    :param file: File to run against
    :param path: Path to check
    :param expected: Expected value
    """
    assert load_recipe(file, RecipeReader).contains_selector_at_path(path) == expected


@pytest.mark.parametrize(
    "file,path,expected",
    [
        ("simple-recipe.yaml", "/build/skip", "[py<37]"),
        ("simple-recipe.yaml", "/requirements/host/0", "[unix]"),
        ("simple-recipe.yaml", "/requirements/host/1", "[unix]"),
        ("simple-recipe.yaml", "/requirements/empty_field2", "[unix and win]"),
    ],
)
def test_get_selector_at_path_exists(file: str, path: str, expected: str) -> None:
    """
    Tests cases where a selector exists on a path

    :param file: File to run against
    :param path: Path to check
    :param expected: Expected value
    """
    assert load_recipe(file, RecipeReader).get_selector_at_path(path) == expected


def test_get_selector_at_path_dne() -> None:
    """
    Tests edge cases where `get_selector_at_path()` should fail correctly OR
    handles non-existent selectors gracefully
    """
    parser = load_recipe("simple-recipe.yaml", RecipeReader)
    # Path does not exist
    with pytest.raises(KeyError):
        parser.get_selector_at_path("/fake/path")
    # No default was provided
    with pytest.raises(KeyError):
        parser.get_selector_at_path("/requirements/run/0")
    # Invalid default was provided
    with pytest.raises(ValueError):
        parser.get_selector_at_path("/requirements/run/0", "not a selector")

    # Valid default was provided
    assert parser.get_selector_at_path("/requirements/run/0", "[unix]") == "[unix]"


## Comments ##


@pytest.mark.parametrize(
    "file,expected",
    [
        (
            "simple-recipe.yaml",
            {
                "/requirements/host/1": "# selector with comment",
                "/requirements/empty_field2": "# selector with comment with comment symbol",
                "/requirements/run/0": "# not a selector",
            },
        ),
        ("huggingface_hub.yaml", {}),
        ("multi-output.yaml", {}),
        (
            "curl.yaml",
            {
                "/outputs/0/requirements/run/2": "# exact pin handled through openssl run_exports",
                "/outputs/2/requirements/host/0": "# Only required to produce all openssl variants.",
            },
        ),
    ],
)
def test_get_comments_table(file: str, expected: dict[str, str]) -> None:
    """
    Tests generating a table of comment locations

    :param file: File to run against
    :param expected: Expected value
    """
    parser = load_recipe(file, RecipeReader)
    assert parser.get_comments_table() == expected


def test_search() -> None:
    """
    Tests searching for values
    """
    parser = load_recipe("simple-recipe.yaml", RecipeReader)
    assert parser.search(r"fake") == ["/requirements/host/1"]
    assert parser.search(r"^0$") == ["/build/number"]
    assert parser.search(r"true") == ["/build/skip", "/build/is_true"]
    assert parser.search(r"py.*") == ["/requirements/run/0", "/about/description"]
    assert parser.search(r"py.*", True) == ["/build/skip", "/requirements/run/0", "/about/description"]
    assert not parser.is_modified()


@pytest.mark.parametrize(
    "file,expected",
    [
        ("simple-recipe.yaml", "695b05c43362eb43c22eae23f0129f41f61413912225184cb7234a4d2c15f353"),
        ("v1_format/v1_simple-recipe.yaml", "dfe5bb7ad4a0c9477d0bf0dc56219f2810d75d0e5aa72b12f7210ff9946d4ab7"),
        ("types-toml.yaml", "e117d210da9ea6507fdea856ee96407265aec40cbc58432aa6e1c7e31998a686"),
        ("v1_format/v1_types-toml.yaml", "3474ed870eea9c8efbd248d24de8bdf54ad8651a7aed06d240f118272d8a3fd1"),
        ("v1_format/v1_boto.yaml", "b42349254d020ffeda77f3068e8ad8804a92d1c7b89eb0f3d45632b38fc0a3bc"),
    ],
)
def test_calc_sha256(file: str, expected: str) -> None:
    """
    Tests hashing a recipe parser's state with SHA-256
    """
    parser = load_recipe(file, RecipeReader)
    assert parser.calc_sha256() == expected
