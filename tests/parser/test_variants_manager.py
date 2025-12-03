"""
:Description: Unit tests for the VariantsManager class
"""

from __future__ import annotations

from typing import Final

import pytest

from conda_recipe_manager.parser.build_context import BuildContext
from conda_recipe_manager.parser.platform_types import Platform
from conda_recipe_manager.parser.variants_manager import VariantsManager
from tests.file_loading import get_test_path, load_file


@pytest.mark.parametrize(
    "platform",
    [
        Platform("linux-64"),
        Platform("linux-aarch64"),
        Platform("osx-arm64"),
        Platform("win-64"),
    ],
)
@pytest.mark.parametrize(
    "feedstock",
    [
        "curl",
        # NOTE: The recipe was modified to avoid a duplicate script key in each output.
        "intel_repack",
        # NOTE: The recipe was modified to avoid:
        #   - Duplicate skip keys.
        #   - Duplicate script keys for numpy-base.
        #   - JINJA if statements in the recipe.
        "numpy",
        # NOTE: The recipe and local CBC were modified:
        #   - To correct the list of lists format for zip keys in the CBC file.
        #   - To avoid duplicate build/string keys in the recipe.
        #   - To avoid duplicate summary keys in the recipe.
        "openblas",
    ],
)
def test_variants_manager(platform: Platform, feedstock: str) -> None:
    """
    Tests the VariantsManager class by computing recipe variants for a given feedstock and platform.
    These variants are compared against the expected variants,
        which were manually verified against conda-build's output for correctness.
    We don't perform automated comparison with conda-build's output directly because the rendering performed
        by CRM is less complete than conda-build's.
    We do not evaluate all JINJA functions such as {{ pin_subpackage() }} for example.

    :param platform: Platform to test the variants manager for.
    :param feedstock: Feedstock to test the variants manager for.
    """
    aggregate_cbc_path = get_test_path() / "recipe_variants" / "conda_build_config.yaml"
    recipe_cbc_path = get_test_path() / "recipe_variants" / feedstock / "recipe" / "conda_build_config.yaml"
    recipe_path = get_test_path() / "recipe_variants" / feedstock / "recipe" / "meta.yaml"

    cbc_strs: Final[list[str]] = [aggregate_cbc_path.read_text()]
    if recipe_cbc_path.exists():
        cbc_strs.append(recipe_cbc_path.read_text())

    manager = VariantsManager(
        recipe_str=recipe_path.read_text(), cbc_strs=cbc_strs, build_context=BuildContext(platform=platform)
    )

    for i, variant in enumerate(manager.get_recipe_variants()):
        assert variant.render() == load_file(f"recipe_variants/{feedstock}/{platform}_{i}.yaml")
