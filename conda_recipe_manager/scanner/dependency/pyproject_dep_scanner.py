"""
:Description: Reads dependencies from a `pyproject.toml` file.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Final, cast

from conda_recipe_manager.parser.dependency import DependencySection
from conda_recipe_manager.scanner.dependency.base_dep_scanner import (
    BaseDependencyScanner,
    ProjectDependency,
    new_project_dependency,
)
from conda_recipe_manager.types import MessageCategory


class PyProjectDependencyScanner(BaseDependencyScanner):
    """
    Dependency Scanner class capable of scanning `pyproject.toml` files.
    """

    def __init__(self, src_dir: Path | str, project_file_name: str = "pyproject.toml"):
        """
        Constructs a `PyProjectDependencyScanner`.

        :param src_dir: Path to the Python source code to scan.
        :param project_file_name: (Optional) Allows for custom pyproject file names. Primarily used for testing,
            defaults to standard `pyproject.toml` name.
        """
        super().__init__()
        self._src_dir: Final[Path] = Path(src_dir)
        self._project_fn: Final[str] = project_file_name

    def scan(self) -> set[ProjectDependency]:
        """
        Actively scans a project for dependencies. Implementation is dependent on the type of scanner used.

        :returns: A set of unique dependencies found by the scanner, if any are found.
        """
        try:
            with open(self._src_dir / self._project_fn, "rb") as f:
                data = cast(dict[str, dict[str, list[str] | dict[str, list[str]]]], tomllib.load(f))
        except (FileNotFoundError, tomllib.TOMLDecodeError) as e:
            if isinstance(e, FileNotFoundError):
                self._msg_tbl.add_message(MessageCategory.EXCEPTION, f"`{self._project_fn}` file not found.")
            if isinstance(e, tomllib.TOMLDecodeError):
                self._msg_tbl.add_message(MessageCategory.EXCEPTION, f"Could not parse `{self._project_fn}` file.")
            return set()

        # NOTE: There is a `validate-pyproject` library hosted on `conda-forge`, but it is marked as "experimental" by
        # its maintainers. Given that and that we only read a small portion of the file, we only validate what we use.
        if "project" not in data:
            self._msg_tbl.add_message(
                MessageCategory.ERROR, f"`{self._project_fn}` file is missing a `project` section."
            )
            return set()

        # NOTE: The dependency constraint system used in `pyproject.toml` appears to be compatible with `conda`'s
        # `MatchSpec` object. For now, dependencies that can't be parsed with `MatchSpec` will store the raw string in
        # a `.name` field.
        # TODO Future, consider handling Environment Markers:
        #   https://packaging.python.org/en/latest/specifications/dependency-specifiers/#environment-markers
        deps: set[ProjectDependency] = set()
        for dep_name in cast(list[str], data["project"].get("dependencies", [])):
            deps.add(new_project_dependency(dep_name, DependencySection.RUN))

        # Optional dependencies are stored in a dictionary, where the key is the "package extra" name and the value is
        # a dependency list. For example: {'dev': ['pytest'], 'conda_build': ['conda-build']}
        for dep_lst in cast(dict[str, list[str]], data["project"].get("optional-dependencies", {})).values():
            for dep_name in dep_lst:
                deps.add(new_project_dependency(dep_name, DependencySection.RUN_CONSTRAINTS))

        return deps
