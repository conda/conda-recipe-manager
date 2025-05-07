"""
:Description: Base CLI for all `conda-recipe-manager` commands
"""

from __future__ import annotations

import logging

import click

from conda_recipe_manager.commands.bump_recipe import bump_recipe
from conda_recipe_manager.commands.convert import convert
from conda_recipe_manager.commands.graph import graph
from conda_recipe_manager.commands.patch import patch
from conda_recipe_manager.commands.rattler_bulk_build import rattler_bulk_build


@click.group()
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    default=False,
    show_default=True,
    help="Enables verbose logging (for commands that use the logger).",
)
@click.version_option()
def conda_recipe_manager(verbose: bool) -> None:
    """
    Command line interface for conda recipe management commands.
    """
    # Initialize the logger, available to all CRM commands.
    logging.basicConfig(
        format="%(asctime)s[%(levelname)s][%(name)s]: %(message)s",
        level=logging.DEBUG if verbose else logging.INFO,
    )


conda_recipe_manager.add_command(convert)
conda_recipe_manager.add_command(graph)
conda_recipe_manager.add_command(rattler_bulk_build)
conda_recipe_manager.add_command(patch)
conda_recipe_manager.add_command(bump_recipe)


if __name__ == "__main__":
    conda_recipe_manager(False)
