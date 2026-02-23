"""
:Description: Defines a base recipe graph class. Derived classes provide initialization details.
"""

from __future__ import annotations

from typing import Final, Optional

import matplotlib.pyplot as plt
import networkx as nx  # type: ignore[import-untyped]
from networkx.drawing.nx_agraph import graphviz_layout  # type: ignore[import-untyped]

from conda_recipe_manager.grapher.types import GraphDirection, GraphType, PackageStats
from conda_recipe_manager.parser.dependency import DependencySection
from conda_recipe_manager.parser.recipe_reader_deps import RecipeReaderDeps

# TODO: Remove all the typing ignore lines tied to `networkx`
#   See this mypy issue for more details: https://github.com/python/mypy/issues/17699


class RecipeGraph:
    """
    Base class for all Recipe Graph types. This standardizes tooling for multiple recipe storage mechanisms.
    """

    @staticmethod
    def _reverse_flag(direction: GraphDirection) -> bool:
        """
        Determines direction flag by enumeration.

        :param direction: Target direction
        :returns: The equivalent boolean flag of the graph direction
        """
        match direction:
            case GraphDirection.DEPENDS_ON:
                return False
            case GraphDirection.NEEDED_BY:
                return True

    def _get_graph(self, graph_type: GraphType) -> nx.DiGraph:  # type: ignore[no-any-unimported]
        """
        Returns the appropriate graph structure, based on the type.

        :param graph_type: Target graph type
        :returns: Reference to the target graph object
        """
        match graph_type:
            case GraphType.BUILD:
                return self._build_graph  # type: ignore[misc]
            case GraphType.TEST:
                return self._test_graph  # type: ignore[misc]

    def __init__(
        self,
        recipe_cache: dict[str, RecipeReaderDeps],
        recipes_failed_to_parse: set[str],
    ):  # pylint: disable=too-complex
        """
        Constructs common types that all recipe graphs share. Derived classes handle initialization details.

        :param recipe_cache: Maps recipe file SHA-256 hashes to recipe parser instances.
        :param recipes_failed_to_parse: Set of identifiers of recipes that failed to parse.
        """
        self._package_stats = PackageStats(
            recipes_failed_to_parse=recipes_failed_to_parse,
            total_parsed_recipes=len(recipe_cache),
            total_recipes=len(recipe_cache) + len(recipes_failed_to_parse),
        )

        # Cache containing parsed recipes
        self._recipe_cache = recipe_cache
        # Create a secondary look-up table that maps package names to hashes. This will make graph generation easier.
        self._name_to_sha256: dict[str, str] = {}

        # TODO construct graphs
        # Dependency graph representations, built from the initial cache.
        self._build_graph = nx.DiGraph()  # type: ignore[misc]
        self._test_graph = nx.DiGraph()  # type: ignore[misc]

        for sha, parser in self._recipe_cache.items():
            # TODO fix MatchSpec blowing up on failed sub_vars
            try:
                dep_map = parser.get_all_dependencies()
            except Exception:  # pylint: disable=broad-exception-caught
                # Attempt to gather all the package names that failed to parse.
                try:
                    self._package_stats.recipes_failed_to_parse_dependencies[sha] = list(
                        parser.get_package_names_to_path().keys()
                    )
                except Exception:  # pylint: disable=broad-exception-caught
                    self._package_stats.recipes_failed_to_parse_dependencies[sha] = ["Unknown"]
                continue

            for package_name, deps in dep_map.items():
                if package_name in self._name_to_sha256:
                    self._package_stats.package_name_duplicates.add(package_name)
                    continue
                self._name_to_sha256[package_name] = sha
                self._package_stats.total_packages += 1
                for dep in deps:
                    match dep.type:
                        # Build graph
                        case DependencySection.BUILD | DependencySection.HOST:
                            self._build_graph.add_edge(package_name, dep.data.name)  # type: ignore[misc]

                        # Test graph
                        # TODO does this include run constraints?
                        case DependencySection.RUN | DependencySection.TESTS:
                            self._test_graph.add_edge(package_name, dep.data.name)  # type: ignore[misc]

    def __bool__(self) -> bool:
        """
        Indicates if the RecipeGraph contains information.

        :returns: True if the graph is "truthy" and holds information. False otherwise.
        """
        return bool(self._recipe_cache)

    def contains_package_name(self, package: str) -> bool:
        """
        Indicates if a package name is recognized in the graph.

        :param package: Target package
        :returns: True if the package name is found in the graph. False otherwise.
        """
        return package in self._name_to_sha256

    def get_package_stats(self) -> PackageStats:
        """
        Returns a structure filled with package statistics gathered during graph constructed.

        :returns: A structure of package-related statistics
        """
        return self._package_stats

    def plot(
        self,
        graph_type: GraphType,
        direction: GraphDirection = GraphDirection.DEPENDS_ON,
        package: Optional[str] = None,
    ) -> None:
        """
        Draws a dependency graph to the screen.

        :param graph_type: Indicates which kind of graph to render.
        :param direction: (Optional) Indicates the direction of the dependency relationship.
        :param package: (Optional) Name of the target package to draw a sub-graph of. If not provided, renders the
            entire graph.
        """
        # TODO add blocking flag?
        graph_to_render: Final[nx.DiGraph] = self._get_graph(graph_type)  # type: ignore[misc,no-any-unimported]

        plt.figure()
        plt.axis("off")
        if package is None:
            plt.title(f"{graph_type.capitalize()} Graph")
            nx.draw(  # type: ignore[misc]
                graph_to_render,  # type: ignore[misc]
                pos=graphviz_layout(graph_to_render, "dot"),  # type: ignore[misc]
                alpha=0.6,
            )
        else:
            match direction:
                case GraphDirection.DEPENDS_ON:
                    plt.title(f"{graph_type.capitalize()} Graph of Dependencies of {package}")
                case GraphDirection.NEEDED_BY:
                    plt.title(f"{graph_type.capitalize()} Graph of Packages that Need {package}")

            sub_graph = nx.bfs_tree(  # type: ignore[misc]
                graph_to_render, package, reverse=RecipeGraph._reverse_flag(direction)  # type: ignore[misc]
            )
            nx.draw(  # type: ignore[misc]
                sub_graph,  # type: ignore[misc]
                pos=graphviz_layout(sub_graph, "dot"),  # type: ignore[misc]
                node_size=2000,
                with_labels=True,
                alpha=0.6,
            )
        plt.show()
