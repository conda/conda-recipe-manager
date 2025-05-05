"""
:Description: Provides a subclass of RecipeReader that adds advanced dependency management tools.
"""

from __future__ import annotations

from typing import Final, Optional, cast

from conda_recipe_manager.parser._types import ROOT_NODE_VALUE
from conda_recipe_manager.parser.dependency import (
    Dependency,
    DependencyMap,
    dependency_data_from_str,
    str_to_dependency_section,
)
from conda_recipe_manager.parser.recipe_reader import RecipeReader
from conda_recipe_manager.parser.selector_parser import SelectorParser
from conda_recipe_manager.parser.types import SchemaVersion


class RecipeReaderDeps(RecipeReader):
    """
    Extension of the base RecipeReader class to enables advanced dependency management abilities. The base RecipeReader
    class is so large, that this has been broken-out for maintenance purposes.
    """

    @staticmethod
    def _add_top_level_dependencies(root_package: str, dep_map: DependencyMap) -> None:
        """
        Helper function that applies "root"/top-level dependencies to packages in multi-output recipes.
        """
        if len(dep_map) <= 1 or root_package not in dep_map:
            return
        root_dependencies: Final[list[Dependency]] = dep_map[root_package]
        for package in dep_map:
            if package == root_package:
                continue
            # Change the "required_by" package name to the current package, not the root package name.
            dep_map[package].extend(
                [Dependency(package, d.path, d.type, d.data, d.selector) for d in root_dependencies]
            )

    @staticmethod
    def _sanitize_dep(dep: Optional[str]) -> Optional[str]:
        """
        Sanitizes dependency strings. Invalid dependencies can be ignored with a `None` check. This function prevents
        consumption of bad recipe file data.

        :param dep: Dependency string to validate. This is the string found in a list in a dependency section.
        :returns: The sanitized string, if valid. `None`, if invalid.
        """
        if dep is None:
            return None

        # TODO V1 support missing here: V1 selectors return an `if/then` dictionary, not a string!
        dep = dep.strip()
        if not dep:
            return None

        return dep

    def _fetch_optional_selector(self, path: str) -> Optional[SelectorParser]:
        """
        Given a recipe path, optionally return a SelectorParser object.

        :param path: Path to the target value
        :returns: A parsed selector, if one is available. Otherwise, None.
        """
        try:
            return SelectorParser(self.get_selector_at_path(path), self._schema_version)
        except KeyError:
            return None

    def get_package_names_to_path(self) -> dict[str, str]:
        """
        Get a map containing all the packages (artifacts) named in a recipe to their paths in the recipe structure.

        :raises KeyError: If a package in the recipe does not have a name
        :raises ValueError: If a recipe contains a package with duplicate names
        :returns: Mapping of package name to path where that package is found
        """
        # TODO Figure out: Skip top-level packages for multi-output recipe files?
        package_tbl: dict[str, str] = {}
        root_name_path: Final[str] = (
            "/recipe/name" if self.is_multi_output() and self._schema_version == SchemaVersion.V1 else "/package/name"
        )
        name_path: Final[str] = (
            "/package/name" if self.is_multi_output() and self._schema_version == SchemaVersion.V1 else "/name"
        )
        for path in self.get_package_paths():
            try:
                if path == ROOT_NODE_VALUE:
                    name = cast(str, self.get_value(root_name_path, sub_vars=True))
                else:
                    name = cast(str, self.get_value(RecipeReader.append_to_path(path, name_path), sub_vars=True))
            except KeyError as e:
                raise KeyError(f"Could not find a package name associated with path: {path}") from e

            if name in package_tbl:
                raise ValueError(f"Duplicate package name found: {name}")

            package_tbl[name] = path
        return package_tbl

    def get_all_dependencies(self) -> DependencyMap:
        """
        Get a parsed representation of all the dependencies found in the recipe.

        :raises KeyError: If a package in the recipe does not have a name
        :raises ValueError: If a recipe contains a package with duplicate names
        :returns: A structured representation of the dependencies.
        """
        # TODO Figure out: Skip top-level packages for multi-output recipe files?
        package_path_tbl: Final[dict[str, str]] = self.get_package_names_to_path()
        root_package = ""
        dep_map: DependencyMap = {}

        for package, path in package_path_tbl.items():
            if path == ROOT_NODE_VALUE:
                root_package = package

            requirements = cast(
                Optional[str | dict[str, list[Optional[str]]]],
                self.get_value(RecipeReader.append_to_path(path, "/requirements"), default={}, sub_vars=True),
            )
            # Skip over empty/malformed requirements sections
            if requirements is None or isinstance(requirements, str):
                continue
            dep_map[package] = []
            for section_str, deps in requirements.items():
                section = str_to_dependency_section(section_str)
                # Unrecognized sections will be skipped as "junk" data
                if section is None or deps is None:
                    continue

                for i, dep in enumerate(deps):
                    dep = RecipeReaderDeps._sanitize_dep(dep)
                    if dep is None:
                        continue

                    # NOTE: `get_dependency_paths()` uses the same approach for calculating dependency paths.
                    dep_path = RecipeReader.append_to_path(path, f"/requirements/{section_str}/{i}")
                    dep_map[package].append(
                        Dependency(
                            required_by=package,
                            path=dep_path,
                            type=section,
                            data=dependency_data_from_str(dep),
                            selector=self._fetch_optional_selector(dep_path),
                        )
                    )

        # Apply top-level dependencies to multi-output recipe packages
        RecipeReaderDeps._add_top_level_dependencies(root_package, dep_map)

        return dep_map
