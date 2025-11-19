"""
:Description: Unit tests for the VariantsManager class
"""

from __future__ import annotations

from pathlib import Path
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
        "intel_repack",
        "numpy",
        "openblas",
    ],
)
def test_variants_manager(platform: Platform, feedstock: str) -> None:
    """
    Tests the VariantsManager class.
    """
    aggregate_cbc_path = get_test_path() / "recipe_variants" / "conda_build_config.yaml"
    recipe_cbc_path = get_test_path() / "recipe_variants" / feedstock / "recipe" / "conda_build_config.yaml"
    recipe_path = get_test_path() / "recipe_variants" / feedstock / "recipe" / "meta.yaml"

    cbc_paths: Final[list[Path]] = [aggregate_cbc_path]
    if recipe_cbc_path.exists():
        cbc_paths.append(recipe_cbc_path)

    manager = VariantsManager(
        recipe_path=recipe_path,
        cbc_paths=cbc_paths,
        build_context=BuildContext(platform=platform),
    )

    for i, variant in enumerate(manager.get_recipe_variants()):
        assert variant.render() == load_file(f"recipe_variants/{feedstock}/{platform}_{i}.yaml")
