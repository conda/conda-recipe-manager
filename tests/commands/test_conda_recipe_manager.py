"""
:Description: Tests the base `conda-recipe-manager` CLI
"""

from conda_recipe_manager.commands.conda_recipe_manager import conda_recipe_manager
from tests.smoke_testing import assert_cli_usage


def test_usage() -> None:
    """
    Smoke test that ensures rendering of the help menu
    """
    assert_cli_usage(conda_recipe_manager)
