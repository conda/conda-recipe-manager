"""
:Description: Custom parser for selector recipe selector syntax. This parser does not evaluate Python code directly,
                and should therefore not be affected by the execution vulnerability in the V0 recipe format.
"""

from __future__ import annotations

from typing import Final, Optional, Union

from conda_recipe_manager.parser._is_modifiable import IsModifiable
from conda_recipe_manager.parser._types import Regex
from conda_recipe_manager.parser.enums import ALL_LOGIC_OPS, LogicOp, SchemaVersion
from conda_recipe_manager.parser.exceptions import SelectorSyntaxError
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
from conda_recipe_manager.parser.types import COMPARISON_OPERATOR_PATTERN

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

    def is_operator(self) -> bool:
        """
        Indicates if the node represents an operator

        :returns: True if the node represents an operator
        """
        return self.is_logical_op() and self.l_node is None and self.r_node is None


# Type alias for a nested list of _SelectorNode objects.
SelectorNodeNestedList = list[Union[_SelectorNode, "SelectorNodeNestedList"]]


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
    def _reduce_not_op(tokens: list[_SelectorNode]) -> list[_SelectorNode]:
        """
        Reduces a list of tokens by applying the NOT operator

        :param tokens: List of tokens to reduce
        :raises SelectorSyntaxError: If the selector syntax is invalid
        :returns: List of reduced tokens
        """
        new_tokens = []
        idx = 0
        while idx < len(tokens):
            token = tokens[idx]
            if not (token.is_operator() and token.value == LogicOp.NOT):
                new_tokens.append(token)
                idx += 1
                continue
            if idx + 1 >= len(tokens) or tokens[idx + 1].is_operator():
                raise SelectorSyntaxError(
                    f"Expected NOT operator to be followed by a single operand, got {tokens[idx + 1]}: {tokens}"
                )
            token.l_node = tokens[idx + 1]
            new_tokens.append(token)
            idx += 2
        return new_tokens

    @staticmethod
    def _reduce_op(op: LogicOp, tokens: list[_SelectorNode]) -> list[_SelectorNode]:
        """
        Reduces a list of tokens by applying the given operator

        :param op: Operator to apply
        :param tokens: List of tokens to reduce
        :raises SelectorSyntaxError: If the selector syntax is invalid
        :returns: List of reduced tokens
        """
        new_tokens = []
        idx = 0
        cur_operand = tokens[0]
        while idx < len(tokens):
            if cur_operand.is_operator():
                raise SelectorSyntaxError(f"Expected operand, got {cur_operand}: {tokens}")
            if idx == len(tokens) - 1:
                new_tokens.append(cur_operand)
                break
            operator = tokens[idx + 1]
            if not operator.is_operator():
                raise SelectorSyntaxError(f"Expected operator, got {operator}: {tokens}")
            if operator.value != op:
                new_tokens.append(cur_operand)
                new_tokens.append(operator)
                idx += 2
                cur_operand = tokens[idx]
                continue
            if idx + 2 >= len(tokens) or tokens[idx + 2].is_operator():
                raise SelectorSyntaxError(
                    f"Did not find a second operand after the operator {operator} while reducing {op}: {tokens}"
                )
            operator.l_node = cur_operand
            operator.r_node = tokens[idx + 2]
            idx += 2
            cur_operand = operator
        return new_tokens

    @staticmethod
    def _parse_selector_subtree(tokens: list[_SelectorNode]) -> _SelectorNode:
        """
        Constructs a selector parse subtree

        :param tokens: Selector tokens to process
        :raises SelectorSyntaxError: If the selector syntax is invalid
        :returns: The root of the parse subtree
        """
        if not isinstance(tokens, list) or not tokens:
            raise SelectorSyntaxError(f"Expected a non-empty list of tokens, got {tokens}")

        if len(tokens) == 1:
            return tokens[0]
        # Handle NOT operators first
        tokens = SelectorParser._reduce_not_op(tokens)
        if len(tokens) == 1:
            return tokens[0]
        # Handle AND operators second
        tokens = SelectorParser._reduce_op(LogicOp.AND, tokens)
        if len(tokens) == 1:
            return tokens[0]
        # Handle OR operators third
        tokens = SelectorParser._reduce_op(LogicOp.OR, tokens)
        if len(tokens) == 1:
            return tokens[0]
        raise SelectorSyntaxError(f"Expected 1 token, got {len(tokens)}: {tokens}")

    @staticmethod
    def _parse_selector_tree(tokens: SelectorNodeNestedList) -> _SelectorNode:
        """
        Constructs a selector parse tree

        :param tokens: Selector tokens to process
        :raises SelectorSyntaxError: If the selector syntax is invalid
        :returns: The root of the parse tree
        """
        if not tokens:
            raise SelectorSyntaxError(f"Expected a non-empty list of tokens, got {tokens}")
        list_of_nodes: list[_SelectorNode] = []
        for token in tokens:
            if isinstance(token, list):
                subtree_root = SelectorParser._parse_selector_tree(token)
                list_of_nodes.append(subtree_root)
            else:
                list_of_nodes.append(token)
        tree_root = SelectorParser._parse_selector_subtree(list_of_nodes)
        return tree_root

    @staticmethod
    def _find_space_or_parenthesis(content: str, idx: int) -> int:
        """
        Finds the next space or parenthesis in the content

        :param content: Content to search
        :param idx: Index to start searching from
        :returns: Index of the next space or parenthesis, or length of the content if no space or parenthesis is found
        """
        while idx < len(content):
            if content[idx] == " " or content[idx] == ")":
                return idx
            idx += 1
        return len(content)

    @staticmethod
    def _pre_process_selector_content(content: str, idx: int = 0) -> tuple[SelectorNodeNestedList, int]:
        """
        Pre-processes the selector content

        :param content: Selector content to process to be parsed
        :param idx: Index to start processing from
        :returns: Tuple containing a list of selector nodes and the index of the next character to process
        """
        if not content:
            return [], 0
        tokens: SelectorNodeNestedList = []
        while idx < len(content):
            if content[idx] == ")":
                return tokens, idx + 1
            if content[idx] == "(":
                sub_tree, idx = SelectorParser._pre_process_selector_content(content, idx + 1)
                tokens.append(sub_tree)
            elif content[idx] == " ":
                idx += 1
            else:
                end_idx = SelectorParser._find_space_or_parenthesis(content, idx)
                node = _SelectorNode(content[idx:end_idx])
                tokens.append(node)
                idx = end_idx
        return tokens, idx

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
            initial_content = content
            # TODO Future: validate with Selector regex for consistency, not string indexing.
            if (
                self._schema_version == SchemaVersion.V0
                and initial_content
                and initial_content[0] == "["
                and initial_content[-1] == "]"
            ):
                initial_content = initial_content[1:-1]
            # TODO: Handle comparison operators. For now, we'll just remove whitespace around them.
            # This will cause the parser to treat the whole expression as a single node
            # (e.g. `py >= 3.10` becomes `py>=3.10`).
            initial_content = COMPARISON_OPERATOR_PATTERN.sub(r"\1", initial_content)
            return initial_content

        self._content: Final[str] = _init_content()

        pre_processed_content, _ = SelectorParser._pre_process_selector_content(self._content)
        self._root: Optional[_SelectorNode] = (
            SelectorParser._parse_selector_tree(pre_processed_content) if pre_processed_content else None
        )

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
