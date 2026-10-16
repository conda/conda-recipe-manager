"""
:Description: Provides a class that represents a variant of a recipe.

This is a subclass of RecipeReaderDeps whose constructor takes a BuildContext object and uses it to construct
a rendered variant of the recipe instead of the recipe in its original form.
It is intended to give full read access to the recipe variant.

This class is intended to be used in the context of the VariantsManager class.
"""

from __future__ import annotations

import hashlib
import json
from typing import Final, cast

from conda.models.match_spec import MatchSpec

from conda_recipe_manager.parser._node import Node
from conda_recipe_manager.parser.build_context import BuildContext
from conda_recipe_manager.parser.recipe_parser import RecipeParser
from conda_recipe_manager.parser.recipe_reader_deps import RecipeReaderDeps
from conda_recipe_manager.parser.selector_parser import SelectorParser
from conda_recipe_manager.parser.types import NoArchType, RecipeReaderFlags
from conda_recipe_manager.types import PRIMITIVES_NO_NONE_TUPLE, JsonType
from conda_recipe_manager.utils.cryptography.hashing import hash_str
from conda_recipe_manager.utils.typing import optional_str


class RecipeVariant(RecipeReaderDeps):
    """
    Class that represents a recipe variant, filtered by selectors and evaluated for Jinja expressions.
    """

    def _hash_pkg(self) -> str:
        """
        Helper function that calculates a recipe variant's "package hash" component of a "build string". This is a
        mechanism in conda-build to fingerprint dependencies in builds.

        :returns: The "package hash" component of the recipe variant's build string.
        """
        # Hashing contents are determined by:
        #   https://github.com/conda/conda-build/blob/main/conda_build/metadata.py#L1702
        to_hash = {}
        # TODO: match filtering mechanisms found in conda-build
        for _, deps in self.get_all_dependencies(include_test_dependencies=False).items():
            for dep in deps:
                to_hash[dep.data.name] = "" if not isinstance(dep.data, MatchSpec) else dep.data.version

        recipe_dep_hash: Final = hash_str(json.dumps(to_hash, sort_keys=True), hashlib.sha1)
        # Default hash-length used by conda-build is 7:
        #   https://github.com/conda/conda-build/blob/main/conda_build/config.py#L229
        # `h` usually marks that this is a hex-representation, but that is not included in the `PKG_HASH` variable (or
        # at least recipes that reference `PKG_HASH` tend to include the `h` manually).
        return recipe_dep_hash[:7]

    def _get_build_num(self) -> int:
        """
        Convenience function for retrieving the `/build/number` field and ensuring it is a numeric type.

        :returns: An integer representation of the `/build/number` field.
        """
        build_num: Final = self.get_value("/build/number", default=0, sub_vars=True)
        if not isinstance(build_num, int):
            return 0
        return build_num

    def _filter_by_selectors(self, build_context: BuildContext) -> None:
        """
        Filters the recipe by the selectors in the build context.
        This operation is destructive and will remove paths that are no longer applicable to the build context.
        It will also remove all selectors.

        :param build_context: Build context to filter the recipe by.
        """
        # Remove all jinja variables that do not apply to the build context
        for variable, values in self._vars_tbl.items():
            new_values = []
            for val in values:
                if not val.contains_selector() or cast(SelectorParser, val.get_selector()).does_selector_apply(
                    build_context
                ):
                    new_values.append(val)
            self._vars_tbl[variable] = new_values
        self._vars_tbl = {k: v for k, v in self._vars_tbl.items() if len(v) > 0}

        def _filter_selectors_and_paths(node: Node) -> None:
            # Filters selectors and paths in the node's children.
            new_children = []
            for child in node.children:
                if child.is_comment():
                    new_children.append(child)
                    continue
                child_selector = SelectorParser._v0_extract_selector(child.comment)  # pylint: disable=protected-access
                if not child_selector:
                    new_children.append(child)
                elif SelectorParser(child_selector, self.get_schema_version()).does_selector_apply(build_context):
                    child.comment, _ = RecipeParser._remove_selector_from_comment(  # pylint: disable=protected-access
                        child.comment
                    )
                    new_children.append(child)
                else:
                    continue
                _filter_selectors_and_paths(child)
            node.children = new_children

        _filter_selectors_and_paths(self._root)

        self._rebuild_selectors()
        self._is_modified = True

    def _evaluate_jinja_expressions(self, build_context: BuildContext) -> None:
        """
        Evaluates Jinja expressions in the recipe given the provided query and the recipe variables.
        This function is destructive and will modify the recipe in place, removing all Jinja variables and expressions.

        :param build_context: Build context to evaluate the Jinja expressions for.
        :raises ValueError: If the JINJA expression evaluation result is not a primitive type.
        """
        recipe_vars_context: Final[dict[str, JsonType]] = {k: self.get_variable(k) for k in self._vars_tbl}

        # We inject special build-time variables here so they can be rendered appropriately throughout the variant.
        # TODO Future: Ideally this replacement work should live in the variable rendering logic in `RecipeReader`
        #              so that `PKG_*` variables may be used when `sub_vars=True`. Unfortunately, calculating `PKG_HASH`
        #              uses tooling made available in `RecipeReaderDeps`.
        # TODO Future: Figure out what other conda-build variables fall into this category.
        recipe_vars_context["PKG_HASH"] = self._hash_pkg()
        recipe_vars_context["PKG_BUILDNUM"] = self._get_build_num()

        context: Final = {**build_context.get_context(), **recipe_vars_context}
        _, sub_regex = self._set_on_schema_version()

        def _evaluate_jinja_expression_in_node(node: Node) -> None:
            # Evaluates JINJA expression in the node value if applicable.
            if isinstance(node.value, str) and sub_regex.search(node.value):
                rendered_value = self._render_jinja_vars(node.value, context)
                if not isinstance(rendered_value, PRIMITIVES_NO_NONE_TUPLE):
                    raise ValueError(
                        f"JINJA expression evaluation result is not a primitive type: {type(rendered_value)}"
                    )
                node.value = rendered_value
            for child in node.children:
                _evaluate_jinja_expression_in_node(child)

        _evaluate_jinja_expression_in_node(self._root)
        self._vars_tbl.clear()
        self._is_modified = True

    def __init__(
        self, content: str, build_context: BuildContext | None = None, flags: RecipeReaderFlags = RecipeReaderFlags.NONE
    ):
        """
        Constructs a RecipeVariant instance.

        :param content: conda-build formatted recipe file, as a single text string.
        :param build_context: (Optional) Build context to use to construct the variant.
            If not provided, the recipe will not be filtered by selectors or evaluated for Jinja expressions.
        :param flags: (Optional) Flags to control the behavior of the recipe reader.
        """
        super().__init__(content, flags)
        self._build_ctx = build_context
        if self._build_ctx is None:
            return
        self._filter_by_selectors(self._build_ctx)
        self._evaluate_jinja_expressions(self._build_ctx)

    def get_build_str(self) -> str:
        """
        Attempts to mimic the build-string generation behavior of `conda-build`.
        NOTE: As of writing, this behavior is not guaranteed to match!

        :returns: Build string for this recipe variant.
        """
        # Look at conda-build's `Metadata::hash_dependencies()` function for the conda-build's build-string logic.
        build_str: Final = optional_str(self.get_value("/build/string", default=None, sub_vars=True))
        if build_str is not None:
            return build_str

        build_num: Final = self._get_build_num()
        pkg_hash: Final = self._hash_pkg()

        # Helper function for calculating the `py*` prefix in the build string name.
        def _py_prefix() -> str:
            if not self.is_python_recipe():
                return ""

            match self.get_noarch_type():
                case NoArchType.PYTHON:
                    return "py"
                case NoArchType.GENERIC:
                    return ""
                case NoArchType.NONE:
                    if self._build_ctx is not None:
                        py_ver: Final = self._build_ctx.get_python_version_as_int()
                        if py_ver is not None:
                            return f"py{py_ver}"
                    return "py"

        return f"{_py_prefix()}h{pkg_hash}_{build_num}"
