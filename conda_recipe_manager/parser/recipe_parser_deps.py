"""
:Description: Provides an editing-capable variant of the RecipeReaderDeps class.
"""

from __future__ import annotations

from typing import Final, Optional, cast

from conda_recipe_manager.parser.dependency import (
    Dependency,
    DependencyConflictMode,
    dependency_data_from_str,
    dependency_data_render_as_str,
    str_to_dependency_section,
)
from conda_recipe_manager.parser.enums import SelectorConflictMode
from conda_recipe_manager.parser.recipe_parser import RecipeParser
from conda_recipe_manager.parser.recipe_reader_deps import RecipeReaderDeps
from conda_recipe_manager.types import JsonType

# Dependency validation constants
_SINGLE_OUTPUT_LEN: Final[int] = 4
_MULTI_OUTPUT_LEN: Final[int] = 6


class RecipeParserDeps(RecipeParser, RecipeReaderDeps):
    """
    Extension of the RecipeParser and RecipeReaderDeps classes to enables advanced dependency management abilities.

    Beware of "The Diamond Problem". This class extends the capabilities of the `RecipeParser` class with the
    dependency tooling found in `RecipeReaderDeps`.
    """

    @staticmethod
    def _is_valid_dependency_path(dep_path: str) -> bool:
        """
        Given a string, validate that the string is a valid path to a dependency in a recipe.

        :param dep_path: Target string.
        :returns: True if the string is a valid path. False otherwise.
        """
        # TODO add V1 support
        path = dep_path.split("/")
        len_path = len(path)
        if len_path not in {_SINGLE_OUTPUT_LEN, _MULTI_OUTPUT_LEN}:
            return False

        # Single-output
        if len_path == _SINGLE_OUTPUT_LEN:
            return (
                not bool(path[0])
                and path[1] in {"requirements", "test"}
                and str_to_dependency_section(path[2]) is not None
                and path[3].isdigit()
            )

        # Multi-output
        return (
            not bool(path[0])
            and path[1] == "outputs"
            and path[2].isdigit()
            and path[3] in {"requirements", "test"}
            and str_to_dependency_section(path[4]) is not None
            and path[5].isdigit()
        )

    @staticmethod
    def _init_patch_path(
        dep: Dependency, dep_mode: DependencyConflictMode, base_path: str, is_new_section: bool
    ) -> str:
        """
        Helper function for `add_dependency` that determines what path should be used for the `patch()` call.

        :param dep: Dependency to add.
        :param dep_mode: Indicates how duplicate dependencies should be handled.
        :param base_path: Base path the dependency is using (i.e. path that does not end in an index)
        :param is_new_section: Indicates that dependency being added is in a new section, changing the patch op.
        :returns: The correct path to use when adding/replacing a dependency.
        """
        if dep_mode == DependencyConflictMode.EXACT_POSITION:
            return dep.path
        if is_new_section:
            return base_path
        return f"{base_path}/-"

    def _calc_is_new_section(self, base_path: str) -> Optional[bool]:
        """
        Determines if a new dependency section (`run`, `host`, etc) need to be added.

        :param base_path: Base path the dependency is using (i.e. path that does not end in an index)
        :returns: True if a new dependency section is needed, False if no new section is needed, and None if the
            path given is missing too many components.
        """
        if not self.contains_value(base_path):
            # We will not handle construction of more than a key that holds a list of dependencies.
            if not self.contains_value(base_path.rsplit("/", 1)[0]):
                return None
            return True

        return False

    def _patch_add_dep(
        self, dep: Dependency, patch_op: str, patch_path: str, sel_mode: SelectorConflictMode, is_new_section: bool
    ) -> bool:
        """
        Helper function that executes a patch operation to add a dependency and apply a selector (if applicable). In
        some cases, the previous selector may have to be preserved.

        :param dep: Dependency to add
        :param patch_op: Patch operation to perform
        :param patch_path: Target path to apply the patch to
        :param sel_mode: Mode of operation for handling Selector conflicts.
        :param is_new_section: Indicates that dependency being added is in a new section, changing the patch op.
        :returns: True if the patch was successful. False otherwise.
        """
        preserve_sel: Optional[str] = None

        if patch_op == "replace" and sel_mode != SelectorConflictMode.REPLACE:
            try:
                preserve_sel = self.get_selector_at_path(patch_path)
            except KeyError:
                pass

        value: JsonType = dependency_data_render_as_str(dep.data)
        # This allows us to create new lists for dependency sections that do not currently exist.
        if is_new_section:
            value = [value]

        patch_success = self.patch({"op": patch_op, "path": patch_path, "value": value})

        if preserve_sel is not None:
            self.add_selector(patch_path, preserve_sel)

        return patch_success

    def add_dependency(
        self,
        dep: Dependency,
        dep_mode: DependencyConflictMode = DependencyConflictMode.REPLACE,
        sel_mode: SelectorConflictMode = SelectorConflictMode.REPLACE,
    ) -> bool:
        """
        Convenience function that adds a dependency to a recipe file. The `path` attribute is used to locate which
        section and output is being used, but the index position is not guaranteed, unless `EXACT_POSITION` mode is
        used.

        This function will add new dependency sections (`run`, `host`, etc) but it will not add any additional missing
        infrastructure (like `requirements` or an `outputs` section).

        :param dep: Dependency to add.
        :param dep_mode: (Optional) Indicates how duplicate dependencies should be handled. Defaults to replacing the
            existing dependency. Duplicates match by name only.
        :param sel_mode: (Optional) Indicates how an existing selector should be handled. Defaults to replacing the
            existing selector.
        :returns: The result of the underlying patch command, indicating that a change occurred.
        """
        # TODO add V1 support
        # Validate the Dependency, in case the user rolled-their-own.
        if not RecipeParserDeps._is_valid_dependency_path(dep.path):
            return False

        base_path: Final[str] = dep.path.rsplit("/", 1)[0]

        is_new_section = self._calc_is_new_section(base_path)
        if is_new_section is None:
            return False

        patch_op = "replace" if dep_mode == DependencyConflictMode.EXACT_POSITION else "add"
        patch_path = RecipeParserDeps._init_patch_path(dep, dep_mode, base_path, is_new_section)

        # TODO: Add a "get dependencies at path" function to `RecipeReaderDeps`
        opt_cur_deps = self.get_value(base_path, sub_vars=True, default=[])
        # Handle empty section case
        opt_cur_deps = [] if opt_cur_deps is None else opt_cur_deps
        cur_deps: Final[list[Optional[str]]] = cast(list[Optional[str]], opt_cur_deps)

        # Check for duplicate dependencies, if applicable.
        if dep_mode not in {DependencyConflictMode.USE_BOTH, DependencyConflictMode.EXACT_POSITION}:
            for i, cur_dep in enumerate(cur_deps):
                cur_dep = RecipeReaderDeps._sanitize_dep(cur_dep)
                if cur_dep is None:
                    continue

                cur_data = dependency_data_from_str(cur_dep)
                if cast(str, cur_data.name) != cast(str, dep.data.name):
                    continue

                # If we have a name match, act according to the conflict mode
                match dep_mode:
                    case DependencyConflictMode.IGNORE:
                        return False
                    case DependencyConflictMode.REPLACE:
                        patch_path = f"{base_path}/{i}"
                        patch_op = "replace"
                        break

        patch_success: Final[bool] = self._patch_add_dep(dep, patch_op, patch_path, sel_mode, is_new_section)

        if patch_success and dep.selector is not None:
            sel_path = patch_path
            # `add_selector()`, by nature of how selectors work, does not support "append" mode. If an append operation
            # occurred, we must calculate the position of the last array element. We only add selectors on a successful
            # patch, so we know we can make assume a dependency list exists.
            if sel_path.endswith("/-"):
                sel_path = sel_path[0:-1] + str(len(cast(list[str], self.get_value(base_path))) - 1)
            self.add_selector(sel_path, dep.selector, mode=sel_mode)
        return patch_success

    def remove_dependency(self, dep: Dependency) -> bool:
        """
        Convenience function that removes a dependency from a recipe file. No exceptions are thrown if the dependency
        does not exist.

        :param dep: Dependency to remove
        :returns: The result of the underlying patch command, indicating that a change occurred.
        """
        return self.patch({"op": "remove", "path": dep.path})
