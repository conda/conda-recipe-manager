"""
:Description: Custom parser for selector recipe selector syntax. This parser does not evaluate Python code directly,
                and should therefore not be affected by the execution vulnerability in the V0 recipe format.
"""

from __future__ import annotations

import ast
from functools import cache
from typing import Final, Optional

from evalidate import EvalModel, Expr, base_eval_model  # type: ignore[import-untyped]

from conda_recipe_manager.parser._is_modifiable import IsModifiable
from conda_recipe_manager.parser._types import Regex
from conda_recipe_manager.parser.build_context import BuildContext
from conda_recipe_manager.parser.enums import SchemaVersion
from conda_recipe_manager.parser.exceptions import SelectorSyntaxError
from conda_recipe_manager.parser.types import Primitives


class SelectorParser(IsModifiable):
    """
    Parses a selector statement
    """

    # Evalidate model preparation
    @staticmethod
    @cache  # type: ignore[misc]
    def _get_evalidate_model() -> EvalModel:  # type: ignore[misc, no-any-unimported]
        """
        Prepares the EvalModel for the selector parser.
        The model is setup similarly to conda-build's in order to support the same set of expressions.

        :returns: The prepared EvalModel.
        """
        model: EvalModel = base_eval_model.clone()  # type: ignore[no-any-unimported, misc]
        model.nodes += ["Call", "Attribute", "Tuple", "List", "Dict", "Is", "IsNot"]  # type: ignore[misc]
        model.allowed_functions += ["int", "float", "len", "str", "list", "dict", "tuple"]  # type: ignore[misc]
        model.attributes += [  # type: ignore[misc]
            # String methods
            "endswith",
            "index",
            "lower",
            "rsplit",
            "split",
            "startswith",
            "strip",
            "upper",
            "join",
            "replace",
            # Dict methods
            "get",
            "items",
            "keys",
            "values",
            # For legacy os attributes
            "environ",
            "getenv",
            "pathsep",
            "sep",
        ]
        return model  # type: ignore[misc]

    def __init__(self, content: str, schema_version: SchemaVersion):
        """
        Constructs and parses a selector string

        :param content: Selector string to parse
        :param schema_version: Schema the recipe uses
        """

        super().__init__()
        self._schema_version: Final[SchemaVersion] = schema_version

        # Sanitize content string
        # TODO Future: validate with Selector regex for consistency, not string indexing.
        if self._schema_version == SchemaVersion.V0 and content and content[0] == "[" and content[-1] == "]":
            content = content[1:-1]
        content = content.strip()
        self._content: Final[Optional[str]] = content if content else None

    @staticmethod
    def _v0_extract_selector(comment: Optional[str]) -> Optional[str]:
        """
        Utility that extracts a selector from a V0 comment. Not to be used publicly/outside the `parser` module.

        :param comment: Comment string to attempt to extract a V0 selector from.
        :returns: A selector string, if one was found. Otherwise, `None`.
        """
        if not comment:
            return None
        match = Regex.SELECTOR.search(comment)
        if not match:
            return None
        return match.group(0)

    def __str__(self) -> str:
        """
        Returns a debug string representation of the parser.

        :returns: Parser's debug string
        """
        return f"Schema: V{self._schema_version} | Selector: {self._content}"

    def __eq__(self, other: object) -> bool:
        """
        Checks equivalency between two SelectorParsers.

        :returns: True if both selectors are equivalent. False otherwise.
        """
        if not isinstance(other, SelectorParser):
            return False
        # TODO Improve: This is a short-hand for checking if the two parse trees are the same
        return self._schema_version == other._schema_version and str(self) == str(other)

    @staticmethod
    def _get_names_from_expression(expression: str) -> list[str]:
        """
        Extracts the names from a selector expression.

        :param expression: The selector expression to extract the names from.
        :returns: A list of names.
        """
        tree = ast.parse(expression, mode="eval")
        names = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
        return list(names)

    def does_selector_apply(self, build_context: BuildContext) -> bool:
        """
        Determines if this selector applies to the current target environment.

        :param build_context: Build environment context.
        :raises SelectorSyntaxError: If the selector cannot be evaluated, for example because it is unsafe.
        :returns: True if the selector applies to the current situation. False otherwise.
        """
        # No selector? No problem!
        if not self._content:
            return True

        selector_context: Final[dict[str, Primitives]] = build_context.get_selector_context()

        try:
            # If the selector references a variable that is not in the build context,
            # we add it to the context as None.
            names = SelectorParser._get_names_from_expression(self._content)
            for name in names:
                selector_context.setdefault(name, None)
            expr_code = Expr(self._content, model=SelectorParser._get_evalidate_model()).code  # type: ignore[misc]
            # expr_code is already guaranteed to be safe to evaluate
            # so we can use eval directly for a slight performance boost.
            return bool(eval(expr_code, None, selector_context))  # type: ignore[misc] # pylint: disable=eval-used
        except Exception as e:  # pylint: disable=broad-exception-caught
            raise SelectorSyntaxError(f"Error evaluating selector: {e}") from e

    def render(self) -> str:
        """
        Renders the selector as it would appear in a recipe file.

        :returns: The rendered equivalent selector.
        """
        # TODO Add V1 support
        # TODO will need to render from the tree if we add editing functionality.
        rendered_content: str = self._content if self._content is not None else ""
        if self._schema_version == SchemaVersion.V0:
            rendered_content = f"[{rendered_content}]"
        return rendered_content
