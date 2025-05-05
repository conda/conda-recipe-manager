"""
:Description: CLI understanding recipe dependency graphs.
"""

from __future__ import annotations

import json
import pickle
import sys
import time
from pathlib import Path
from typing import Final

import click

from conda_recipe_manager.commands.utils.print import print_err
from conda_recipe_manager.commands.utils.types import ExitCode
from conda_recipe_manager.grapher.recipe_graph import PackageStats, RecipeGraph
from conda_recipe_manager.grapher.recipe_graph_from_disk import RecipeGraphFromDisk
from conda_recipe_manager.grapher.types import GraphDirection, GraphType, PackageStatsEncoder


@click.command(short_help="Interactive CLI for examining recipe dependency graphs.")
@click.argument("path", type=click.Path(exists=True, path_type=Path, file_okay=False))
def graph(path: Path) -> None:
    """
    Interactive CLI that provides tools for examining a dependency graph created from conda recipes.

    Arguments:
      PATH - A path containing recipe files to be examined.
    """
    print("Constructing dependency graph...")
    start_time: Final[float] = time.time()

    recipe_graph: Final[RecipeGraph] = RecipeGraphFromDisk(path)
    if not recipe_graph:
        print_err(f"The path provided does not contain any recipe files: {path}")
        sys.exit(ExitCode.CLICK_USAGE)

    total_time: Final[float] = time.time() - start_time
    package_stats: Final[PackageStats] = recipe_graph.get_package_stats()
    failed_recipe_count: Final[int] = len(package_stats.recipes_failed_to_parse)
    failed_dep_count: Final[int] = len(package_stats.recipes_failed_to_parse_dependencies)
    success_recipe_rate: Final[float] = (1 - (failed_recipe_count / package_stats.total_recipes)) * 100
    success_dep_rate: Final[float] = (1 - (failed_dep_count / package_stats.total_parsed_recipes)) * 100
    print(
        f"Failed to parse {failed_recipe_count}"
        f" out of {package_stats.total_recipes} recipe files ({success_recipe_rate:.2f}% success)."
    )
    print(
        f"Failed to parse the dependencies from {failed_dep_count}"
        f" out of {package_stats.total_parsed_recipes} recipe files ({success_dep_rate:.2f}% success)."
    )
    # NOTE: There is no stdlib way to recursively calculate an object's memory usage.
    print(f"Estimated memory usage of the graph: {len(pickle.dumps(recipe_graph)) / (2**20):.2f}MiB")
    print(f"Total graph construction time: {round(total_time, 2)}s")

    print()
    print("== Main menu ==")
    while True:
        command = input("> ").lower()
        match command.split():
            case ["help"] | ["h"]:
                print(
                    "Conda Recipe Manager (CRM) Graph Utility Interactive Shell (GUIS)\n\n"
                    "Use exit, q, or Ctrl-D to quit.\n\n"
                    "Commands:\n"
                    "  - plot (build|test) [depends|needed-by] (<package>|all)\n"
                    "    Generates a visual representation of the requested dependency graph.\n"
                    "    Using `all` prints the entire graph (no direction required).\n"
                    "  - stats\n"
                    "    Prints graph construction statistics.\n"
                    "  - help\n"
                    "    Prints this help message.\n"
                )
            case ["plot", g_type, "all"]:
                if g_type not in GraphType:
                    print(f"Unrecognized graph type: {g_type}")
                    continue
                print("This might take a while...")
                recipe_graph.plot(GraphType(g_type))
            case ["plot", g_type, dir_str, pkg]:
                if g_type not in GraphType:
                    print(f"Unrecognized graph type: {g_type}")
                    continue
                direction: GraphDirection
                match dir_str:
                    case "depends":
                        direction = GraphDirection.DEPENDS_ON
                    case "needed-by":
                        direction = GraphDirection.NEEDED_BY
                    case _:
                        print("Unrecognized graph direction.")
                        continue
                if not recipe_graph.contains_package_name(pkg):
                    print(f"Package not found: {pkg}")
                    continue
                recipe_graph.plot(GraphType(g_type), direction, pkg)
            case ["stats"] | ["statistics"]:
                print(
                    json.dumps(package_stats, indent=2, sort_keys=True, cls=PackageStatsEncoder)  # type: ignore[misc]
                )
            case ["exit"] | ["esc"] | ["quit"] | ["q"]:
                print("Closing interactive menu...")
                break
            case _:
                print("Invalid command.")

    sys.exit(ExitCode.SUCCESS)
