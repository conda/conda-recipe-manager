"""
:Description: Custom parser for selector recipe selector syntax. This parser does not evaluate Python code directly,
                and should therefore not be affected by the execution vulnerability in the V0 recipe format.
"""

from __future__ import annotations

from typing import Final, Optional

from conda_recipe_manager.parser._is_modifiable import IsModifiable
from conda_recipe_manager.parser._types import Regex
from conda_recipe_manager.parser.enums import ALL_LOGIC_OPS, LogicOp, SchemaVersion
from conda_recipe_manager.parser.platform_types import (
    ALL_ARCHITECTURES,
    ALL_OPERATING_SYSTEMS,
    ALL_PLATFORM_ALIASES,
    Arch,
    OperatingSystem,
    PlatformAlias,
    PlatformQualifiers,
    get_platforms_by_alias,
    get_platforms_by_arch,
    get_platforms_by_os,
)
from conda_recipe_manager.parser.selector_query import SelectorQuery

# A selector is comprised of known operators and special types, or (in V0 recipes) arbitrary Python strings
SelectorValue = LogicOp | PlatformQualifiers | str


class _SelectorNode:
    """
    Represents a node in a selector parse tree. This class should not be used outside of this module.
    """

    def __init__(self, value: str):
        """
        Constructs a selector node

        :param value: Selector value stored in the node
        """

        # Enumerate special/known selector types
        def _init_value() -> SelectorValue:
            lower_val: Final[str] = value.lower()
            if lower_val in ALL_PLATFORM_ALIASES:
                return PlatformAlias(lower_val)
            if lower_val in ALL_OPERATING_SYSTEMS:
                return OperatingSystem(lower_val)
            if lower_val in ALL_ARCHITECTURES:
                return Arch(lower_val)
            if lower_val in ALL_LOGIC_OPS:
                return LogicOp(lower_val)
            return value

        self.value: Final[SelectorValue] = _init_value()
        # Left and right nodes
        self.l_node: Optional[_SelectorNode] = None
        self.r_node: Optional[_SelectorNode] = None

    def __str__(self) -> str:
        """
        Returns a debug string representation of a sub-tree rooted at this node.

        :returns: Node's debug string
        """
        l_str: Final[str] = "" if self.l_node is None else f" L {self.l_node}"
        r_str: Final[str] = "" if self.r_node is None else f" R {self.r_node}"
        return f"{self.value}{l_str}{r_str}"

    def __repr__(self) -> str:
        """
        Returns a common string representation of a node

        :returns: Node's value
        """
        return str(self.value)

    def is_logical_op(self) -> bool:
        """
        Indicates if the node represents an operation

        :returns: True if the node represents an operation
        """
        return self.value in ALL_LOGIC_OPS


class SelectorParser(IsModifiable):
    """
    Parses a selector statement
    """

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

    @staticmethod
    def _process_postfix_stack(stack: list[_SelectorNode]) -> Optional[_SelectorNode]:
        """
        Recursively processes the postfix stack of nodes, building a tree

        :returns: Current node in the tree
        """
        if not stack:
            return None
        cur = stack.pop()
        match cur.value:
            case LogicOp.NOT:
                cur.l_node = SelectorParser._process_postfix_stack(stack)
            case LogicOp.AND | LogicOp.OR:
                cur.r_node = SelectorParser._process_postfix_stack(stack)
                cur.l_node = SelectorParser._process_postfix_stack(stack)
        return cur

    @staticmethod
    def _parse_selector_tree(tokens: list[str]) -> Optional[_SelectorNode]:
        """
        Constructs a selector parse tree

        :param tokens: Selector tokens to process
        :returns: The root of the parse tree
        """
        # TODO: Handle parentheses
        # TODO: Handle ==, !=, >=, <=, >, <

        # Shunting yard
        op_stack: list[_SelectorNode] = []
        postfix_stack: list[_SelectorNode] = []
        while tokens:
            node = _SelectorNode(tokens.pop(0))
            if node.is_logical_op():
                # `NOT` has the highest precedence. For example:
                #   - `not osx and win` is interpreted as `(not osx) and win`
                #   - In Python, `not True or True` is interpreted as `(not True) or True`, returning `True`
                if node.value != LogicOp.NOT:
                    while op_stack and op_stack[-1].value == LogicOp.NOT:
                        postfix_stack.append(op_stack.pop())
                op_stack.append(node)
                continue
            postfix_stack.append(node)

        while op_stack:
            postfix_stack.append(op_stack.pop())

        root = SelectorParser._process_postfix_stack(postfix_stack)

        return root

    def __init__(self, content: str, schema_version: SchemaVersion):
        """
        Constructs and parses a selector string

        :param content: Selector string to parse
        :param schema_version: Schema the recipe uses
        """
        super().__init__()
        self._schema_version: Final[SchemaVersion] = schema_version

        # Sanitizes content string
        def _init_content() -> str:
            # TODO Future: validate with Selector regex for consistency, not string indexing.
            if self._schema_version == SchemaVersion.V0 and content and content[0] == "[" and content[-1] == "]":
                return content[1:-1]
            return content

        self._content: Final[str] = _init_content()

        self._root = SelectorParser._parse_selector_tree(self._content.split())

    def __str__(self) -> str:
        """
        Returns a debug string representation of the parser.

        :returns: Parser's debug string
        """
        return f"Schema: V{self._schema_version} | Tree: {self._root}"

    def __eq__(self, other: object) -> bool:
        """
        Checks equivalency between two SelectorParsers.

        :returns: True if both selectors are equivalent. False otherwise.
        """
        if not isinstance(other, SelectorParser):
            return False
        # TODO Improve: This is a short-hand for checking if the two parse trees are the same
        return self._schema_version == other._schema_version and str(self) == str(other)

    def does_selector_apply(self, query: SelectorQuery) -> bool:
        """
        Determines if this selector applies to the current target environment.

        :param query: Target environment constraints.
        :returns: True if the selector applies to the current situation. False otherwise.
        """
        # No selector? No problem!
        if self._root is None:
            return True
        # No platform with a non-empty selector is actually a problem
        # a platform is required to meaningfully evaluate the selector.
        if query.platform is None:
            return False

        # Recursive helper function that performs a post-order traversal
        def _eval_node(node: Optional[_SelectorNode]) -> bool:
            # Typeguard base-case
            if node is None:
                return False

            match node.value:
                case PlatformAlias():
                    return query.platform in get_platforms_by_alias(node.value)
                case Arch():
                    return query.platform in get_platforms_by_arch(node.value)
                case OperatingSystem():
                    return query.platform in get_platforms_by_os(node.value)
                case LogicOp():
                    match node.value:
                        case LogicOp.NOT:
                            return not _eval_node(node.l_node)
                        case LogicOp.AND:
                            return _eval_node(node.l_node) and _eval_node(node.r_node)
                        case LogicOp.OR:
                            return _eval_node(node.l_node) or _eval_node(node.r_node)
                case str():
                    return node.value in query.build_env_vars

        return _eval_node(self._root)

    def render(self) -> str:
        """
        Renders the selector as it would appear in a recipe file.

        :returns: The rendered equivalent selector.
        """
        # TODO Add V1 support
        # TODO will need to render from the tree if we add editing functionality.
        match self._schema_version:
            case SchemaVersion.V0:
                return f"[{self._content.strip()}]"
            case SchemaVersion.V1:
                return self._content
