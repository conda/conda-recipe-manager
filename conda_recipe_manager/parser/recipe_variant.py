"""
:Description: Provides a class that represents a variant of a recipe.

This is a subclass of RecipeReaderDeps whose constructor takes a BuildContext object and uses it to construct
a rendered variant of the recipe instead of the recipe in its original form.
It is intended to give full read access to the recipe variant.

This class is intended to be used in the context of the VariantsManager class.
"""

from __future__ import annotations

from typing import Final, cast

from conda_recipe_manager.parser._node import Node
from conda_recipe_manager.parser.build_context import BuildContext
from conda_recipe_manager.parser.recipe_parser import RecipeParser
from conda_recipe_manager.parser.recipe_reader_deps import RecipeReaderDeps
from conda_recipe_manager.parser.selector_parser import SelectorParser
from conda_recipe_manager.parser.types import RecipeReaderFlags
from conda_recipe_manager.types import PRIMITIVES_NO_NONE_TUPLE, JsonType


class RecipeVariant(RecipeReaderDeps):
    """
    Class that represents a recipe variant, filtered by selectors and evaluated for Jinja expressions.
    """

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
        This function is destructive and will modify the recipe in place,
        removing all Jinja variables and expressions.

        :param build_context: Build context to evaluate the Jinja expressions for.
        :raises ValueError: If the JINJA expression evaluation result is not a primitive type.
        """
        recipe_vars_context: Final[dict[str, JsonType]] = {k: self.get_variable(k) for k in self._vars_tbl}
        context: Final = {**build_context.get_context(), **recipe_vars_context}

        def _evaluate_jinja_expression_in_node(node: Node) -> None:
            # Evaluates JINJA expression in the node value if applicable.
            if isinstance(node.value, str):
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
        if build_context is None:
            return
        self._filter_by_selectors(build_context)
        self._evaluate_jinja_expressions(build_context)
