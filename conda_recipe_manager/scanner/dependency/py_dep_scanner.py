"""
:Description: Provides a Dependency Scanner class capable of finding dependencies in a Python project's source code.
"""

from __future__ import annotations

import ast
import pkgutil
import sys
from pathlib import Path
from typing import Final

from conda_recipe_manager.parser.dependency import DependencySection
from conda_recipe_manager.scanner.dependency.base_dep_scanner import (
    BaseDependencyScanner,
    ProjectDependency,
    new_project_dependency,
)
from conda_recipe_manager.types import MessageCategory

# Table that maps import names that do not match the package name for common packages. See this StackOverflow post for
# more details:
#  https://stackoverflow.com/questions/54886143/why-are-some-python-package-names-different-than-their-import-name
_IMPORT_TO_DEPENDENCY_NAME_TBL: Final[dict[str, str]] = {
    "git": "gitpython",
    "yaml": "pyyaml",
    "PIL": "pillow",
    "sklearn": "scikit-learn",
    "tables": "pytables",
    "cv": "py-opencv",
    "cv2": "py-opencv",
    "OpenGL": "pyopengl",
}


class PythonDependencyScanner(BaseDependencyScanner):
    """
    Dependency Scanner class capable of scanning Python source code.
    """

    @staticmethod
    def _correct_module_to_dependency(module: str) -> str:
        """
        Corrects common dependency names that are not the same as their imported name.

        :param module: Module name to correct
        :returns: The corrected name, if one is found. Otherwise, the original string.
        """
        if module not in _IMPORT_TO_DEPENDENCY_NAME_TBL:
            return module
        return _IMPORT_TO_DEPENDENCY_NAME_TBL[module]

    @staticmethod
    def _is_likely_test_file(file: Path) -> bool:
        """
        Attempts to determine if a Python file is a test file.

        :param file: Path to the file to check
        :returns: True if we determine that this file/path likely points to a test file.
        """
        # NOTE: This is by no means a perfect function. We will have to iterate on this approach over time.

        sanitized_name: Final[str] = file.name.lower()
        if sanitized_name.startswith("test_") or sanitized_name.endswith("_test.py"):
            return True

        # TODO: Check with the `ast` library if pytest, unittest, pyfakefs, etc are imported(?)

        return False

    def __init__(self, src_dir: Path | str):
        """
        Constructs a `PythonDependencyScanner`.

        :param src_dir: Path to the Python source code to scan.
        """
        super().__init__()
        self._src_dir: Final[Path] = Path(src_dir)

    def _get_project_modules(self) -> set[str]:
        """
        Calculates the set of module names found in this project. These will not need to be listed as dependencies in
        the recipe file (as they are a part of the project).

        :returns: A set of unique dependencies defined in this project's source code.
        """
        return {name for _, name, _ in pkgutil.iter_modules([str(self._src_dir)])}

    def _scan_one_file(self, file: Path) -> set[ProjectDependency]:
        """
        Helper function that scans one Python file for dependencies.

        :returns: Set of project dependencies found in the target Python file.
        """
        deps: set[ProjectDependency] = set()
        project_modules: Final[set[str]] = self._get_project_modules()
        # Adapted from:
        #   https://stackoverflow.com/questions/9008451/python-easy-way-to-read-all-import-statements-from-py-module
        root = ast.parse(file.read_text(), file)

        for node in ast.walk(root):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue

            module_names = []
            if isinstance(node, ast.Import):
                # Handle multiple (comma-separated) imports on one line
                for alias in node.names:
                    module_names.append(alias.name.split(".")[0])
            elif node.module is not None:
                module_names.append(node.module.split(".")[0])

            for module_name in module_names:
                # TODO filter relative imports
                # Filter-out the standard library modules and local module names (i.e. modules defined in the target
                # project).
                if not module_name or module_name in sys.stdlib_module_names or module_name in project_modules:
                    continue

                package_name = PythonDependencyScanner._correct_module_to_dependency(module_name)

                # Most Python imports fall under the `run` section in the Conda recipe format. The major exception is
                # any import found in test code.
                dep_type = (
                    DependencySection.TESTS
                    if PythonDependencyScanner._is_likely_test_file(file)
                    else DependencySection.RUN
                )

                deps.add(new_project_dependency(package_name, dep_type))

        return deps

    def scan(self) -> set[ProjectDependency]:
        """
        Actively scans a project for dependencies.

        :returns: A set of unique dependencies found by the scanner.
        """
        # TODO parallelize this? Some preliminary performance tests show conflicting results using `multiprocessing`
        # pools. Very large Python projects can see a 50% reduction in scanning while small projects take a 30%-40% hit
        # in speed with spin-up costs.
        all_imports: set[ProjectDependency] = set()
        for file in self._src_dir.rglob("*.py"):
            try:
                all_imports |= self._scan_one_file(file)
            except Exception as e:  # pylint: disable=broad-exception-caught
                self._msg_tbl.add_message(
                    MessageCategory.EXCEPTION, f"Exception encountered while scanning `{file}`: {e}"
                )

        # `RUN` dependencies are automatically added as `TEST` dependencies, so we need to filter if there are
        # (effectively) duplicates
        def _filter_test_duplicates(dep: ProjectDependency) -> bool:
            if (
                dep.type == DependencySection.TESTS
                and ProjectDependency(dep.data, DependencySection.RUN) in all_imports
            ):
                return False
            return True

        all_imports = set(filter(_filter_test_duplicates, all_imports))

        # TODO determine if users care to attempt to determine if `types-*` packages are to be included for common
        # libraries.

        # TODO filter unused imports

        # Python is inherently a HOST and RUN dependency for all Python projects.
        all_imports.add(new_project_dependency("python", DependencySection.HOST))
        all_imports.add(new_project_dependency("python", DependencySection.RUN))

        return all_imports
