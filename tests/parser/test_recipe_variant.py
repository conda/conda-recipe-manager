"""
:Description: Unit tests for the RecipeVariant class
"""

from __future__ import annotations

from typing import Final

import pytest

from conda_recipe_manager.parser.build_context import BuildContext
from conda_recipe_manager.parser.platform_types import Platform
from conda_recipe_manager.parser.recipe_variant import RecipeVariant
from tests.file_loading import load_file

## Build Variant Rendering ##


@pytest.mark.parametrize(
    "file,build_context,expected_file",
    [
        ("curl.yaml", BuildContext(platform=Platform.WIN_64), "selector_filtering/curl_win_64.yaml"),
        ("curl.yaml", BuildContext(platform=Platform.LINUX_AARCH_64), "selector_filtering/curl_linux_aarch_64.yaml"),
        ("curl.yaml", BuildContext(platform=Platform.OSX_ARM_64), "selector_filtering/curl_osx_arm_64.yaml"),
        (
            "huggingface_hub.yaml",
            BuildContext(platform=Platform.WIN_64, build_env_vars={"python": "3.6"}),
            "selector_filtering/huggingface_hub_py36.yaml",
        ),
        (
            "huggingface_hub.yaml",
            BuildContext(platform=Platform.WIN_64, build_env_vars={"python": "3.7"}),
            "selector_filtering/huggingface_hub_py37.yaml",
        ),
        (
            "huggingface_hub.yaml",
            BuildContext(platform=Platform.WIN_64, build_env_vars={"python": "3.8"}),
            "selector_filtering/huggingface_hub_py38.yaml",
        ),
        # Regression to check that comments are ignored when filtering by selectors.
        (
            "gluonts.yaml",
            BuildContext(platform=Platform.LINUX_AARCH_64, build_env_vars={"python": "3.7"}),
            "selector_filtering/gluonts_linux_aarch_64.yaml",
        ),
    ],
)
def test_filter_by_selectors(file: str, build_context: BuildContext, expected_file: str) -> None:
    """
    Tests the ability for the `RecipeParser` to filter the recipe by selectors.

    :param file: The file to load the recipe from.
    :param build_context: The build context to filter the recipe by.
    :param expected_file: The file to compare the filtered recipe to.
    """
    parser = RecipeVariant(load_file(file))
    parser._filter_by_selectors(build_context)  # pylint: disable=protected-access
    assert parser.render() == load_file(expected_file)


@pytest.mark.parametrize(
    "file,build_context,expected_file",
    [
        # Check that recipe JINJA variables take precedence over build context variables (openssl).
        (
            "jinja2_rendering/curl.yaml",
            BuildContext(
                platform=Platform.WIN_64,
                build_env_vars={"openssl": "7.0.0", "zlib": "1.2.13"},
            ),
            "jinja2_rendering/curl_rendered.yaml",
        ),
        (
            "jinja2_rendering/curl.yaml",
            BuildContext(
                platform=Platform.WIN_64,
                build_env_vars={"zlib": "1.2.13"},
            ),
            "jinja2_rendering/curl_rendered.yaml",
        ),
        # Regression test for #471: JINJA rendering should only operate on JINJA expressions.
        (
            "jinja2_rendering/curl_regression.yaml",
            BuildContext(
                platform=Platform.WIN_64,
                build_env_vars={"zlib": "1.2.13"},
            ),
            "jinja2_rendering/curl_regression_rendered.yaml",
        ),
    ],
)
def test_evaluate_jinja_expressions(file: str, build_context: BuildContext, expected_file: str) -> None:
    """
    Tests the ability for the `RecipeParser` to replace Jinja expressions in the recipe with their evaluated values.

    :param file: Recipe file to test against.
    :param build_context: The build context to evaluate recipe expressions with.
    :param expected_file: The file to compare the evaluated recipe to.
    """
    parser = RecipeVariant(load_file(file))
    parser._evaluate_jinja_expressions(build_context)  # pylint: disable=protected-access
    assert parser.render() == load_file(expected_file)


@pytest.mark.parametrize(
    ["file", "build_context", "expected"],
    [
        # TODO Future: Ensure that these are the same values returned by `conda-build`
        # Usually the `python` variable is provided by the CBC file.
        ("types-toml.yaml", BuildContext(platform=Platform.LINUX_64, build_env_vars={"python": "3.11"}), "py311h_0"),
        ("types-toml.yaml", BuildContext(platform=Platform.LINUX_64, build_env_vars={"python": "3.12"}), "py311h_0"),
        # Non-zero build number
        (
            "bump_recipe/build_num_42.yaml",
            BuildContext(platform=Platform.LINUX_64, build_env_vars={"python": "3.12"}),
            "py312h_42",
        ),
        # noarch: python
        ("more-itertools.yaml", BuildContext(platform=Platform.LINUX_64, build_env_vars={"python": "3.12"}), "pyh_0"),
        # noarch: generic
        (
            "bump_recipe/gsm-amzn2-aarch64_build_num_6.yaml",
            BuildContext(platform=Platform.LINUX_64, build_env_vars={"python": "3.12"}),
            "h_0",
        ),
        # TODO, handle tensorflow examples:
        #   string: cuda{{ cuda_compiler_version | replace('.', '') }}py{{ CONDA_PY }}h{{ PKG_HASH }}_{{ PKG_BUILDNUM }}  # [cuda_compiler_version != "None"]
        #   string: cpu_py{{ CONDA_PY }}h{{ PKG_HASH }}_{{ PKG_BUILDNUM }}  # [cuda_compiler_version == "None"]
        # TODO test against non-python package like jq
        # TODO Add V1 support (test cases)
    ],
)
def test_get_build_str(file: str, build_context: BuildContext, expected: str) -> None:
    """
    Ensures that `RecipeVariant`s can produce valid package build strings.

    :param file: Recipe file to test against.
    :param build_context: The build context to evaluate the Jinja expressions for.
    :param expected: Expected build string.
    """
    parser: Final = RecipeVariant(load_file(file), build_context)
    assert parser.get_build_str() == expected
