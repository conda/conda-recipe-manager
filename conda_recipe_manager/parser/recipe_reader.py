"""
:Description: Provides a class that takes text from a Jinja-formatted recipe file and parses it. This allows for easy
              semantic understanding of the file. This is the primary base-class to all other Recipe Parsing classes.
"""

from __future__ import annotations

import ast
import hashlib
import logging
import re
import sys
from collections.abc import Callable
from typing import Final, Optional, cast, no_type_check

import yaml
from jinja2 import Environment, StrictUndefined

from conda_recipe_manager.parser._is_modifiable import IsModifiable
from conda_recipe_manager.parser._node import CommentPosition, Node
from conda_recipe_manager.parser._node_var import NodeVar
from conda_recipe_manager.parser._selector_info import SelectorInfo
from conda_recipe_manager.parser._traverse import traverse, traverse_all
from conda_recipe_manager.parser._types import (
    RECIPE_MANAGER_SUB_MARKER,
    ROOT_NODE_VALUE,
    ForceIndentDumper,
    Regex,
    SafeLoader,
    StringLoader,
    StrStack,
)
from conda_recipe_manager.parser._utils import (
    dedupe_and_preserve_order,
    normalize_multiline_strings,
    num_tab_spaces,
    quote_special_strings,
    stack_path_to_str,
    str_to_stack_path,
    stringify_yaml,
    substitute_markers,
)
from conda_recipe_manager.parser.dependency import (
    DependencySection,
    dependency_data_from_str,
    dependency_section_to_str,
)
from conda_recipe_manager.parser.enums import SchemaVersion
from conda_recipe_manager.parser.exceptions import (
    DuplicateKeyException,
    ParsingException,
    ParsingJinjaException,
    SentinelTypeEvaluationException,
)
from conda_recipe_manager.parser.selector_parser import SelectorParser
from conda_recipe_manager.parser.types import TAB_AS_SPACES, TAB_SPACE_COUNT, MultilineVariant, RecipeReaderFlags
from conda_recipe_manager.parser.v0_recipe_formatter import V0RecipeFormatter
from conda_recipe_manager.types import PRIMITIVES_NO_NONE_TUPLE, PRIMITIVES_TUPLE, JsonType, Primitives, SentinelType
from conda_recipe_manager.utils.cryptography.hashing import hash_str
from conda_recipe_manager.utils.typing import optional_str

log: Final = logging.getLogger(__name__)

# Type for the internal recipe variables table. Although relatively uncommon, variables may be defined multiple times
# (in V0), usually in the context of string concatenation. Hence why the table contains a list of `NodeVar`s.
# NOTE:
#   - Support for editing multiple variable definitions will be limited at best.
#   - If a key exists, the list will always have at least one entry.
#   - V1 does not support multiple variable definitions as YAML does not support duplicate keys in an object.
_VarTable = dict[str, list[NodeVar]]


class RecipeReader(IsModifiable):
    """
    Class that parses a recipe file string for read-only operations.
    NOTE: This base class inherits `IsModifiable` even though it provides read-only operations. This is done to
    simplify some problems using Python's multi-inheritance mechanisms.
    """

    # Sentinel object used for detecting defaulting behavior.
    # See here for a good explanation: https://peps.python.org/pep-0661/
    _sentinel = SentinelType()

    @staticmethod
    def _parse_yaml_recursive_sub(data: JsonType, modifier: Callable[[str], JsonType]) -> JsonType:
        """
        Recursive helper function used when we need to perform variable substitutions.

        :param data: Data to substitute values in
        :param modifier: Modifier function that performs some kind of substitution.
        :returns: Pythonic data corresponding to the line of YAML
        """
        # Add the substitutions back in
        if isinstance(data, str):
            data = modifier(quote_special_strings(data))
        if isinstance(data, dict):
            for key in data.keys():
                data[key] = RecipeReader._parse_yaml_recursive_sub(cast(str, data[key]), modifier)
        elif isinstance(data, list):
            for i in range(len(data)):
                data[i] = RecipeReader._parse_yaml_recursive_sub(cast(str, data[i]), modifier)
        return data

    @staticmethod
    def _parse_yaml(
        s: str, parser: Optional[RecipeReader] = None, yaml_loader: type[SafeLoader] = SafeLoader
    ) -> JsonType:
        """
        Parse a line (or multiple) of YAML into a Pythonic data structure

        :param s: String to parse
        :param parser: (Optional) If provided, this will substitute Jinja variables with values specified in in the
            recipe file. Since `_parse_yaml()` is critical to constructing recipe files, this function must remain
            static. Also, during construction, we shouldn't be using a variables until the entire recipe is read/parsed.
        :param yaml_loader: The YAML loader to use.
        :returns: Pythonic data corresponding to the line of YAML
        """
        output: JsonType = None

        # Convenience function to substitute variables. Given the re-try mechanism on YAML parsing, we have to attempt
        # to perform substitutions a few times. Substitutions may occur as the entire strings or parts in a string.
        def _sub_jinja(out: JsonType) -> JsonType:
            if parser is None:
                return out
            return RecipeReader._parse_yaml_recursive_sub(
                out, parser._render_jinja_vars  # pylint: disable=protected-access
            )

        # Our first attempt handles special string cases that require quotes that the YAML parser drops. If that fails,
        # then we fall back to performing JINJA substitutions.
        try:
            try:
                output = _sub_jinja(cast(JsonType, yaml.load(s, Loader=yaml_loader)))
            except yaml.scanner.ScannerError:
                # We quote-escape here for problematic YAML strings that are non-JINJA, like `**/lib.so`. Parsing
                # invalid YAML containing V0 JINJA statements should cause an exception and fallback to the other
                # recovery logic.
                output = _sub_jinja(cast(JsonType, yaml.load(quote_special_strings(s), Loader=yaml_loader)))
        except Exception:  # pylint: disable=broad-exception-caught
            # If a construction exception is thrown, attempt to re-parse by replacing Jinja macros (substrings in
            # `{{}}`) with friendly string substitution markers, then re-inject the substitutions back in. We classify
            # all Jinja substitutions as string values, so we don't have to worry about the type of the actual
            # substitution.
            sub_list: list[str] = Regex.JINJA_V0_SUB.findall(s)
            s = Regex.JINJA_V0_SUB.sub(RECIPE_MANAGER_SUB_MARKER, s)
            # Because we leverage PyYaml to parse the data structures, we need to perform a second pass to perform
            # variable substitutions.
            output = _sub_jinja(
                RecipeReader._parse_yaml_recursive_sub(
                    cast(JsonType, yaml.load(s, Loader=yaml_loader)), lambda d: substitute_markers(d, sub_list)
                )
            )
        return output

    @staticmethod
    def _parse_trailing_comment(s: str) -> Optional[str]:
        """
        Helper function that parses a trailing comment on a line for `Node*`s classes.

        :param s: Pre-stripped (no leading/trailing spaces), non-Jinja line of a recipe file
        :returns: A comment string, including the `#` symbol, if a comment exists. `None` otherwise.
        """
        # There is a comment at the end of the line if a `#` symbol is found with leading whitespace before it. If it is
        # "touching" a character on the left-side, it is just part of a string.
        comment_re_result: Final = Regex.DETECT_TRAILING_COMMENT.search(s)
        if comment_re_result is None:
            return None

        # Group 0 is the whole match, Group 1 is the leading whitespace, Group 2 locates the `#`
        return s[comment_re_result.start(2) :].rstrip()

    @staticmethod
    def _parse_multiline_node(
        line: str, lines: list[str], line_idx: int, new_indent: int, new_node: Optional[Node]
    ) -> tuple[int, Optional[Node]]:
        """
        Parses a multiline string. This handles both quote-backslash and general variations.

        :param line: Current line to scan/parse.
        :param lines: Array of all lines in the file.
        :param line_idx: Current index into the `lines` array, representing the current parser position. This may be
            incremented by this function.
        :param new_indent: Current indentation level to track.
        :param new_node: Current parse-tree node to operate on. If this is not set, this function may initialize and
            return this value if a quote-backslash multiline string is found.
        :returns: A tuple containing the new `line_idx` value and reference to `new_node`. `new_node` may be initialized
            if it is initially set to `None`.
        """
        # The backslash-quote syntax is special and requires us to bypass the usually Node initialization process. We
        # store the initial state as a bool so that we can modify `new_node` later.
        check_backslash_variant: Final[bool] = new_node is None

        # Pick the applicable regular expression to match the starting line with.
        multiline_re_match: Final = (
            Regex.MULTILINE_BACKSLASH_QUOTE.match(line)
            if check_backslash_variant
            else Regex.MULTILINE_VARIANT.match(line)
        )

        if not multiline_re_match:
            return line_idx, new_node

        # Initialization of the child "multiline-node" differs between the two major multiline string forms.
        # NOTE: We perform a redundant `new_node is None` check to help-out the type-checker.
        multiline_node: Node
        if new_node is None or check_backslash_variant:
            new_node = Node(
                value=multiline_re_match.group(Regex.MULTILINE_BACKSLASH_QUOTE_CAPTURE_GROUP_KEY), key_flag=True
            )
            multiline_node = Node(
                # We do not need to increment `line_idx`. It is modified after the current line is read.
                value=[multiline_re_match.group(Regex.MULTILINE_BACKSLASH_QUOTE_CAPTURE_GROUP_FIRST_VALUE)],
                multiline_variant=MultilineVariant.BACKSLASH_QUOTE,
            )
        else:
            # Calculate which multiline symbol is used. The first character must be matched, the second is optional.
            variant_capture = cast(str, multiline_re_match.group(Regex.MULTILINE_VARIANT_CAPTURE_GROUP_CHAR))
            variant_sign = cast(str | None, multiline_re_match.group(Regex.MULTILINE_VARIANT_CAPTURE_GROUP_SUFFIX))
            if variant_sign is not None:
                variant_capture += variant_sign
            # Per YAML spec, multiline statements can't be commented. In other words, the `#` symbol is seen as a
            # string character in multiline values.
            multiline_node = Node(
                value=[],
                multiline_variant=MultilineVariant(variant_capture),
            )

        multiline = lines[line_idx]
        multiline_indent = num_tab_spaces(multiline)
        lines_len: Final[int] = len(lines)
        # Add the line to the list once it is verified to be the next line to capture in this node. This means that
        # `line_idx` will point to the line of the next node, post-processing. Note that blank lines are valid in
        # multi-line strings, occasionally found in `/about/summary` sections.
        while (
            multiline_indent > new_indent
            or multiline == ""
            or (check_backslash_variant and multiline and multiline[-1] == "\\")
        ):
            cast(list[str], multiline_node.value).append(multiline.strip())
            line_idx += 1
            # Ensure we stop looking if we have reached the end of the file.
            if line_idx >= lines_len:
                break
            multiline = lines[line_idx]
            multiline_indent = num_tab_spaces(multiline)
        # The previous level is the key to this multiline value, so we can safely reset it.
        new_node.children = [multiline_node]

        return line_idx, new_node

    @staticmethod
    def _parse_line_node(s: str, only_seen_comments: bool, yaml_loader: type[SafeLoader] = SafeLoader) -> Node:
        """
        Parses a line of conda-formatted YAML into a Node.

        Latest YAML spec can be found here: https://yaml.org/spec/1.2.2/

        :param s: Pre-stripped (no leading/trailing spaces), non-Jinja line of a recipe file.
        :param only_seen_comments: Flag indicating if only comments have been seen at the top of the file thus far.
        :param yaml_loader: The YAML loader to use.
        :returns: A Node representing a line of the conda-formatted YAML.
        """
        # Use PyYaml to safely/easily/correctly parse single lines of YAML.
        output = RecipeReader._parse_yaml(s, yaml_loader=yaml_loader)

        # The full line is a comment
        if s.startswith("#"):
            return Node(
                comment=s, comment_pos=CommentPosition.TOP_OF_FILE if only_seen_comments else CommentPosition.DEFAULT
            )

        # Attempt to parse-out comments. Fully commented lines are not ignored to preserve context when the text is
        # rendered. Their order in the list of child nodes will preserve their location. Fully commented lines just have
        # a value of "None".
        #
        # There is an open issue to PyYaml to support comment parsing:
        #   - https://github.com/yaml/pyyaml/issues/90
        # TODO Future: Node comments should be Optional. That would simplify this logic and prevent empty string
        # allocations.
        opt_comment: Final = RecipeReader._parse_trailing_comment(s)
        comment: Final = "" if opt_comment is None else opt_comment

        # If a dictionary is returned, we have a line containing a key and potentially a value. There should only be 1
        # key/value pairing in 1 line. Nodes representing keys should be flagged for handling edge cases.
        if isinstance(output, dict):
            children: list[Node] = []
            key = list(output.keys())[0]
            # If the value returned is None, there is no leaf node to set
            if output[key] is not None:
                # As the line is shared by both parent and child, the comment gets tagged to both.
                children.append(Node(value=cast(Primitives, output[key]), comment=comment))
            return Node(value=key, comment=comment, children=children, key_flag=True)
        # If a list is returned, then this line is a listed member of the parent Node
        if isinstance(output, list):
            # The full line is a comment
            if s.startswith("#"):
                # Comments are list members to ensure indentation
                return Node(comment=comment, list_member_flag=True)
            # Special scenarios that can occur on 1 line:
            #   1. Lists can contain lists: - - foo -> [["foo"]]
            #   2. Lists can contain keys:  - foo: bar -> [{"foo": "bar"}]
            # And, of course, there can be n values in each of these collections on 1 line as well. Scenario 2 occurs in
            # multi-output recipe files so we need to support the scenario here.
            #
            # `PKG-3006` tracks an investigation effort into what we need to support for our purposes.
            if isinstance(output[0], dict):
                # Build up the key-and-potentially-value pair nodes first
                key_children: list[Node] = []
                key = list(output[0].keys())[0]
                if output[0][key] is not None:
                    key_children.append(Node(cast(Primitives, output[0][key]), comment))
                key_node = Node(value=key, comment=comment, children=key_children, key_flag=True)

                elem_node = Node(comment=comment, list_member_flag=True)
                elem_node.children.append(key_node)
                return elem_node
            # Handle lists of lists
            if output[0] is None:
                return Node(comment=comment, list_member_flag=True)
            return Node(value=cast(Primitives, output[0]), comment=comment, list_member_flag=True)
        # Other types are just leaf nodes. This is scenario should likely not be triggered given our recipe files don't
        # have single valid lines of YAML, but we cover this case for the sake of correctness.
        return Node(value=output, comment=comment)

    @staticmethod
    def _create_private_recipe_reader(content: str) -> RecipeReader:
        """
        Creates a new RecipeReader instance. Exclusively for internal RecipeReader use.

        :param content: The content of the recipe file.
        :returns: A new RecipeReader instance.
        """
        recipe_reader = RecipeReader.__new__(RecipeReader)
        recipe_reader._private_init(content=content, internal_call=True)  # pylint: disable=protected-access
        return recipe_reader

    @staticmethod
    def _generate_subtree(value: JsonType) -> list[Node]:
        """
        Given a value supported by JSON, use the RecipeReader to generate a list of child nodes. This effectively
        creates a new subtree that can be used to patch other parse trees.
        """
        # Multiline values can replace the list of children with a single multiline leaf node.
        if isinstance(value, str) and "\n" in value:
            return [
                Node(
                    value=value.splitlines(),
                    # The conversion from JSON-to-YAML is lossy here. Default to the closest equivalent, which preserves
                    # newlines.
                    multiline_variant=MultilineVariant.PIPE,
                )
            ]

        # For complex types, generate the YAML equivalent and build a new tree.
        if not isinstance(value, PRIMITIVES_TUPLE):
            # Although not technically required by YAML, we add the optional spacing for human readability.
            return RecipeReader._create_private_recipe_reader(  # pylint: disable=protected-access
                # NOTE: `yaml.dump()` defaults to 80 character lines. Longer lines may have newlines unexpectedly
                #       injected into this value, screwing up the parse-tree.
                yaml.dump(value, Dumper=ForceIndentDumper, sort_keys=False, width=sys.maxsize),  # type: ignore[misc]
            )._root.children

        # Primitives can be safely stringified to generate a parse tree.
        return RecipeReader._create_private_recipe_reader(  # pylint: disable=protected-access
            str(stringify_yaml(value))
        )._root.children

    def _set_on_schema_version(self) -> tuple[int, re.Pattern[str]]:
        """
        Helper function for `_render_jinja_vars()` that initializes `schema_version`-specific substitution details.

        :returns: The starting index and the regex pattern used to substitute V0 or V1 JINJA variables.
        """
        match self._schema_version:
            case SchemaVersion.V0:
                return 2, Regex.JINJA_V0_SUB
            case SchemaVersion.V1:
                return 3, Regex.JINJA_V1_SUB

    @no_type_check
    @staticmethod
    def _render_jinja_expression(expression: str, context: dict[str, JsonType]) -> tuple[bool, JsonType]:
        """
        Helper function that renders a Jinja expression.

        :param expression: The Jinja expression to render.
        :param context: The context to evaluate the Jinja expression with.
        :returns: A tuple containing a boolean indicating if the expression was rendered successfully and
            the rendered value, or the original expression if it cannot be rendered.
        """
        try:
            env = Environment(undefined=StrictUndefined)
            compiled_expression = env.compile_expression(expression, undefined_to_none=False)
            result = compiled_expression(**context)
            if isinstance(result, StrictUndefined):
                return False, expression
            return True, result
        except Exception:  # pylint: disable=broad-exception-caught
            return False, expression

    def _eval_var(self, key: str) -> JsonType:
        """
        Evaluates a known variable by name to a V0 JINJA variable or a V1 context variable.

        :param key: Target key that MUST exist in the variables table.
        :returns: Variable's evaluated value
        """
        match self._schema_version:
            case SchemaVersion.V0:
                if len(self._vars_tbl[key]) == 1:
                    return self._vars_tbl[key][0].get_value()
                # Support recursive concatenation here.
                context: dict[str, JsonType] = {}
                for node_var in self._vars_tbl[key]:
                    success, result = cast(
                        tuple[bool, JsonType], self._render_jinja_expression(node_var.get_value(), context)
                    )
                    if not success:
                        log.debug(
                            "The recipe parser was unable to evaluate the " "JINJA expression: %s with context: %s",
                            node_var.get_value(),
                            context,
                        )
                    context = {key: result}
                return result
            case SchemaVersion.V1:
                return self._vars_tbl[key][0].get_value()

    def _render_jinja_vars(self, s: str, context: dict[str, JsonType] | None = None) -> JsonType:
        """
        Helper function that replaces Jinja substitutions with their actual set values.

        :param s: String to be re-rendered
        :param context: (Optional) Context to evaluate the Jinja expressions for.
            If not provided, the Jinja expression context will be constructed ONLY from the recipe variables.
        :returns: The original value, augmented with Jinja substitutions. Types are re-rendered to account for multiline
            strings that may have been "normalized" prior to this call.
        """
        if not s:
            return s

        start_idx, sub_regex = self._set_on_schema_version()

        if context is None:
            context = {k: self.get_variable(k) for k in self._vars_tbl}

        # Search the string, replacing all substitutions we can recognize
        for match in cast(list[str], sub_regex.findall(s)):
            # The regex guarantees the string starts and ends with double braces
            expression = match[start_idx:-2].strip()
            # If the expression can't be evaluated, skip it.
            success, result = cast(tuple[bool, JsonType], self._render_jinja_expression(expression, context))
            if not success:
                log.warning("The recipe parser was unable to evaluate the JINJA expression: %s", expression)
                continue
            # Do not replace the match if the result is not a primitive type. None signals an undefined expression.
            if not isinstance(result, PRIMITIVES_NO_NONE_TUPLE):
                log.warning("The recipe parser was unable to evaluate the JINJA expression: %s", expression)
                continue
            result = str(result)
            if Regex.JINJA_VAR_VALUE_TERNARY.match(result):
                result = "${{" + result + "}}"
            s = s.replace(match, result)

        # If there is leading V0 (unescaped) JINJA that was not able to be fully rendered, it will not be able to be
        # parsed by PyYaml. So it is best to just return the value as a string, without evaluating the type (which, to
        # be clear, should be a string).
        if self._schema_version == SchemaVersion.V0 and s[:2] == "{{":
            return s
        return cast(JsonType, yaml.load(s, Loader=self._yaml_loader))

    def _init_vars_tbl(self) -> None:
        """
        Initializes the variable table, `vars_tbl` based on the document content.
        Requires parse-tree and `_schema_version` to be initialized.

        :raises SentinelTypeEvaluationException: If a node value with a sentinel type is evaluated.
        """
        # Tracks Jinja variables set by the file
        self._vars_tbl: _VarTable = {}

        match self._schema_version:
            case SchemaVersion.V0:
                # Find all the set statements and record the values
                for set_match in cast(list[re.Match[str]], Regex.JINJA_V0_SET_MULTI_LINE.finditer(self._init_content)):
                    jinja_match: str = set_match.group("jinja")
                    key = jinja_match[jinja_match.find("set") + len("set") : jinja_match.find("=")].strip()
                    value: str | JsonType = jinja_match[
                        jinja_match.find("=") + len("=") : jinja_match.find("%}")
                    ].strip()
                    # Fall-back to string interpretation.
                    # TODO: Ideally we use `_parse_yaml()` in the future. However, as discovered in the work to solve
                    # issue #366, that is easier said than done. `_parse_yaml()` was never expected to run on V0 JINJA
                    # variable initialization lines. This causes a lot of conversion problems if the value being set is
                    # a string that is invalid YAML.
                    # Example: {% set soversion = ".".join(version.split(".")[:3]) %}
                    try:
                        value = cast(JsonType, ast.literal_eval(cast(str, value)))
                    except Exception:  # pylint: disable=broad-exception-caught
                        value = str(value)
                    raw_comment: Optional[str] = set_match.group("comment")
                    comment: Optional[str] = raw_comment.rstrip() if isinstance(raw_comment, str) else None
                    node_var = NodeVar(value, comment)
                    # Tracks multiple definitions. In the wild, this is rare, but does occur in the context of
                    # concatenating strings together.
                    if key not in self._vars_tbl:
                        self._vars_tbl[key] = [node_var]
                        continue
                    self._vars_tbl[key].append(node_var)

            case SchemaVersion.V1:
                # Abuse the fact that the `/context` section is pure YAML.
                context: Final = cast(dict[str, JsonType], self.get_value("/context", {}))
                comments_tbl: Final = self.get_comments_table()
                for key, value in context.items():
                    # V1 only allows for scalar types as variables. So we should be able to recover all comments without
                    # recursing through `/context`
                    var_path = RecipeReader.append_to_path("/context", key)
                    # V1 does not support multiple definitions in `/context` because YAML keys must be unique.
                    self._vars_tbl[key] = [NodeVar(value, comments_tbl.get(var_path, None))]

    def _rebuild_selectors(self) -> None:
        """
        Re-builds the selector look-up table. This table allows quick access to tree nodes that have a selector
        specified. This needs to be called when the tree or selectors are modified.
        """
        self._selector_tbl: dict[str, list[SelectorInfo]] = {}

        def _collect_selectors(node: Node, path: StrStack) -> None:
            selector: Final = SelectorParser._v0_extract_selector(node.comment)  # pylint: disable=protected-access
            if selector is None:
                return
            selector_info = SelectorInfo(node, list(path))
            self._selector_tbl.setdefault(selector, [])
            self._selector_tbl[selector].append(selector_info)

        traverse_all(self._root, _collect_selectors)

    def _init_schema_version_and_sanitize_v0_yaml(
        self, internal_call: bool, force_remove_jinja: bool
    ) -> tuple[str, int]:
        """
        Determines the schema version used by the recipe file and then runs a series of corrective actions to improve
        compatibility with V0 recipe files. Most of these actions involve handling common indentation issues, seen in
        the field, that break the recipe parser.

        The vast, vast majority of recipe files follow a standard 2-space-tab convention. Although technically not
        required by YAML/conda-build, it is an assumption this parser makes to simplify an already complex file format.
        `V0RecipeFormatter::fix_excessive_indentation()` should correct n > 2 tab lengths. This is invoked in this
        function.

        :param internal_call: Whether this is an internal call. If true, we cannot determine if the recipe is V0 or V1.
        :param force_remove_jinja: Whether to force remove unsupported JINJA statements from the recipe file.
            If this is set to True,
                then unsupported JINJA statements will silently be removed from the recipe file.
            If this is set to False,
                then unsupported JINJA statements will trigger a ParsingJinjaException.
        :raises ParsingJinjaException: If unsupported JINJA statements are present
            and force_remove_jinja is set to False.
        :returns: A sanitized version of the original recipe file text and a counter indicating how many comments exist
            at the top of the recipe file, before the "canonical" variables section.
        """
        # Format the text for V0 recipe files in an attempt to improve compatibility with our whitespace-delimited
        # parser.
        fmt: Final[V0RecipeFormatter] = V0RecipeFormatter(self._init_content)

        # Auto-detect and deserialize the version of the recipe schema. This will change how the class behaves.
        # NOTE: This will need to be improved when multiple schema versions exist.
        self._schema_version = SchemaVersion.V0 if fmt.is_v0_recipe() else SchemaVersion.V1

        # Early-escape for V1 and recursive calls. Remember that at this point, we have not parsed/set the version enum
        # in the parser.
        if not fmt.is_v0_recipe() or internal_call:
            return self._init_content, 0

        fmt.fmt_text()
        # Calculate the string equivalent once.
        fmt_str: Final = str(fmt)

        # For V0 recipe files, count the number of comment-only lines at the start, before the canonical "variables
        # section"
        tof_comment_cntr = 0
        while fmt_str.splitlines()[tof_comment_cntr].startswith("#"):
            tof_comment_cntr += 1

        # Before removing JINJA statements, we need to ensure that they are all set statements.
        # Unless we are forcefully removing JINJA statements.
        if not force_remove_jinja:
            set_statements: set[str] = {match.group() for match in Regex.JINJA_V0_SET_MULTI_LINE.finditer(fmt_str)}
            for match in Regex.JINJA_V0_MULTI_LINE.finditer(fmt_str):
                if match.group() not in set_statements:
                    raise ParsingJinjaException(match.group())

        # Replace all JINJA lines and fix excessive indentation. Then traverse line-by-line.
        sanitized_yaml_unfixed: Final = Regex.JINJA_V0_MULTI_LINE.sub("", fmt_str)
        # We then must call for a second kind of text formatting, now that the JINJA has been removed.
        sanitized_fmt = V0RecipeFormatter(sanitized_yaml_unfixed)
        if not sanitized_fmt.fix_excessive_indentation():
            log.error("The recipe parser was unable to correct indentation level in a V0 recipe file.")

        return str(sanitized_fmt), tof_comment_cntr

    def _construct_parse_tree(self, sanitized_yaml: str, tof_comment_cntr: int) -> None:
        """
        Constructs the parse tree from the sanitized YAML.

        :param sanitized_yaml: The sanitized YAML to construct the parse tree from.
        :param tof_comment_cntr: The number of comment-only lines at the start of the recipe file.
        """
        # pylint: disable=too-complex
        # Read the YAML line-by-line, maintaining a stack to manage the last owning node in the tree.
        node_stack: list[Node] = [self._root]
        # Relative depth is determined by the increase/decrease of indentation marks (spaces)
        cur_indent = 0
        last_node = node_stack[-1]

        # Iterate with an index variable, so we can handle multiline values
        line_idx = 0
        lines: Final = sanitized_yaml.splitlines()
        num_lines: Final = len(lines)
        while line_idx < num_lines:
            line = lines[line_idx]
            # Increment here, so that the inner multiline processing loop doesn't cause a skip of the line following the
            # multiline value.
            line_idx += 1
            # Ignore empty lines
            clean_line = line.strip()
            if clean_line == "":
                continue

            new_indent = num_tab_spaces(line)
            # Special multiline case. This will initialize `new_node` if the special "-backslash multiline pattern is
            # found.
            line_idx, new_node = RecipeReader._parse_multiline_node(clean_line, lines, line_idx, new_indent, None)
            if new_node is None:
                new_node = RecipeReader._parse_line_node(
                    clean_line, tof_comment_cntr > 0, yaml_loader=self._yaml_loader
                )
                tof_comment_cntr -= 1
                # In the general case (which does not create a new-node), we ignore the returned `new_node` value and
                # rely on the object being modified by the reference we pass-in. As a small optimization, we only run
                # checks on the other multiline variants if the special case fails.
                line_idx, _ = RecipeReader._parse_multiline_node(clean_line, lines, line_idx, new_indent, new_node)
            # Insurance policy: If we miscounted, force-drop the ToF-comment state.
            if tof_comment_cntr > 0 and not new_node.is_comment():
                tof_comment_cntr = -1

            if new_indent > cur_indent:
                node_stack.append(last_node)
                # Edge case: The first element of a list of objects that is NOT a 1-line key-value pair needs
                # to be added to the stack to maintain composition
                if last_node.is_collection_element() and not last_node.children[0].is_single_key():
                    node_stack.append(last_node.children[0])
            elif new_indent < cur_indent:
                # Multiple levels of depth can change from line to line, so multiple stack nodes must be pop'd. Example:
                # foo:
                #   bar:
                #     fizz: buzz
                # baz: blah
                # Tab-depth is guaranteed because of fix_excessive_indentation() above.
                depth_to_pop = (cur_indent - new_indent) // TAB_SPACE_COUNT
                for _ in range(depth_to_pop):
                    node_stack.pop()
            cur_indent = new_indent
            # Look at the stack to determine the parent Node and then append the current node to the new parent.
            parent = node_stack[-1]
            # Check for duplicate keys and bail if found.
            if new_node.is_key() and not new_node.list_member_flag:
                if new_node.value in [child.value for child in parent.children]:
                    raise DuplicateKeyException(line_idx, str(new_node.value))
            parent.children.append(new_node)
            # Update the last node for the next line interpretation
            last_node = new_node

    def _private_init(
        self, content: str, internal_call: bool, flags: RecipeReaderFlags = RecipeReaderFlags.NONE
    ) -> None:
        """
        Private constructor for internal RecipeReader use. This constructor is called by `__init__()` and
        `_create_private_recipe_reader()`, with internal_call set to False and True, respectively.

        :param content: conda-build formatted recipe file, as a single text string.
        :param internal_call: Whether this is an internal call. If true, we cannot determine if the recipe is V0 or V1.
        :param flags: Flags to control the behavior of the recipe reader.
        :raises ParsingJinjaException: If unsupported JINJA statements are present
            and RecipeReaderFlags.FORCE_REMOVE_JINJA is not set.
        """
        super().__init__()
        # The initial, raw, text is preserved for diffing and debugging purposes
        # Note: _init_content should be Final, but mypy requires Final attributes to be declared in __init__
        # See https://mypy.readthedocs.io/en/stable/final_attrs.html#syntax-variants
        self._init_content: str = content
        force_remove_jinja: Final[bool] = RecipeReaderFlags.FORCE_REMOVE_JINJA in flags
        floats_as_strings: Final[bool] = RecipeReaderFlags.FLOATS_AS_STRINGS in flags
        self._yaml_loader: type[SafeLoader] = StringLoader if floats_as_strings else SafeLoader

        sanitized_yaml, tof_comment_cntr = self._init_schema_version_and_sanitize_v0_yaml(
            internal_call, force_remove_jinja
        )

        # Construct the parse tree from the sanitized YAML.
        self._root = Node(value=ROOT_NODE_VALUE)
        self._construct_parse_tree(sanitized_yaml, tof_comment_cntr)
        # Initialize the variables table. This behavior changes per `schema_version`
        self._init_vars_tbl()

        # Now that the tree is built, construct a selector look-up table that tracks all the nodes that use a particular
        # selector. This will make it easier to.
        #
        # This table will have to be re-built or modified when the tree is modified with `patch()`.
        self._rebuild_selectors()

    def __init__(
        self, content: str, flags: RecipeReaderFlags = RecipeReaderFlags.NONE
    ):  # pylint: disable=super-init-not-called
        """
        Constructs a RecipeReader instance.

        :param content: conda-build formatted recipe file, as a single text string.
        :param flags: Flags to control the behavior of the recipe reader.
        :raises ParsingJinjaException: If unsupported JINJA statements are present
            and RecipeReaderFlags.FORCE_REMOVE_JINJA is not set.
        :raises ParsingException: If the recipe file cannot be parsed for an unknown reason.
        """
        try:
            self._private_init(
                content=content,
                internal_call=False,
                flags=flags,
            )
        # If the expected exception is thrown, log then raise it.
        except ParsingException as e:
            log.exception(e)
            raise
        # If an unexpected exception is thrown, raise the expected exception from it.
        # Then log and raise.
        except Exception as e0:  # pylint: disable=broad-exception-caught
            try:
                raise ParsingException() from e0
            except ParsingException as e1:
                log.exception(e1)
                raise

    @staticmethod
    def _canonical_sort_keys_comparison(n: Node, priority_tbl: dict[str, int]) -> int:
        """
        Given a look-up table defining "canonical" sort order, this function provides a way to compare Nodes.

        :param n: Node to evaluate
        :param priority_tbl: Table that provides a "canonical ordering" of keys
        :returns: An integer indicating sort-order priority
        """
        # For now, put all comments at the top of the section. Arguably this is better than having them "randomly tag"
        # to another top-level key.
        if n.is_comment():
            return -sys.maxsize
        # Unidentified keys go to the bottom of the section.
        if not isinstance(n.value, str) or n.value not in priority_tbl:
            return sys.maxsize
        return priority_tbl[n.value]

    @staticmethod
    def _str_tree_recurse(node: Node, depth: int, lines: list[str]) -> None:
        """
        Helper function that renders a parse tree as a text-based dependency tree. Useful for debugging.

        :param node: Node of interest
        :param depth: Current depth of the node
        :param lines: Accumulated list of lines to text to render
        """
        spaces = TAB_AS_SPACES * depth
        branch = "" if depth == 0 else "|- "
        lines.append(f"{spaces}{branch}{node.short_str()}")
        for child in node.children:
            RecipeReader._str_tree_recurse(child, depth + 1, lines)

    def __str__(self) -> str:
        """
        Casts the parser into a string. Useful for debugging.

        :returns: String representation of the recipe file
        """
        s = "--------------------\n"
        tree_lines: list[str] = []
        RecipeReader._str_tree_recurse(self._root, 0, tree_lines)
        s += f"{self.__class__.__name__} Instance\n"
        s += f"- Schema Version: {self._schema_version}\n"
        s += "- Variables Table:\n"
        for key, node_vars in self._vars_tbl.items():
            for node_var in node_vars:
                s += f"{TAB_AS_SPACES}- {key}: {node_var.render_v0_value()}{node_var.render_comment()}\n"
        s += "- Selectors Table:\n"
        for key, val in self._selector_tbl.items():
            s += f"{TAB_AS_SPACES}{key}\n"
            for info in val:
                s += f"{TAB_AS_SPACES}{TAB_AS_SPACES}- {info}\n"
        s += f"- is_modified?: {self._is_modified}\n"
        s += "- Tree:\n" + "\n".join(tree_lines) + "\n"
        s += "--------------------\n"

        return s

    def __eq__(self, other: object) -> bool:
        """
        Checks if two recipe representations match entirely

        :param other: Other recipe parser instance to check against.
        :returns: True if both recipes contain the same current state. False otherwise.
        """
        if not isinstance(other, RecipeReader):
            raise TypeError
        if self._schema_version != other._schema_version:
            return False
        return self.render() == other.render()

    def get_schema_version(self) -> SchemaVersion:
        """
        Returns which version of the schema this recipe uses. Useful for preventing illegal operations.
        :returns: Schema Version of the recipe file.
        """
        return self._schema_version

    def has_unsupported_statements(self) -> bool:
        """
        Runs a series of checks against the original recipe file.

        :returns: True if the recipe has statements we do not currently support. False otherwise.
        """
        # TODO complete
        raise NotImplementedError

    @staticmethod
    def _render_tree(
        node: Node, depth: int, lines: list[str], schema_version: SchemaVersion, parent: Optional[Node] = None
    ) -> None:
        # pylint: disable=too-complex
        # TODO Refactor and simplify ^
        """
        Recursive helper function that traverses the parse tree to generate a file.

        :param node: Current node in the tree
        :param depth: Current depth of the recursion
        :param lines: Accumulated list of lines in the recipe file
        :param schema_version: Target recipe schema version
        :param parent: (Optional) Parent node to the current node. Set by recursive calls only.
        """
        spaces = TAB_AS_SPACES * depth

        # Edge case: The first element of dictionary in a list has a list `- ` prefix. Subsequent keys in the dictionary
        # just have a tab.
        is_first_collection_child: Final[bool] = (
            parent is not None and parent.is_collection_element() and node == parent.children[0]
        )

        # Handle same-line printing
        if node.is_single_key():
            # Edge case: Handle a list containing 1 member
            if node.children[0].list_member_flag:
                if is_first_collection_child:
                    lines.append(f"{TAB_AS_SPACES * (depth-1)}- {node.value}:  {node.comment}".rstrip())
                else:
                    lines.append(f"{spaces}{node.value}:  {node.comment}".rstrip())
                lines.append(
                    f"{spaces}{TAB_AS_SPACES}- "
                    f"{stringify_yaml(node.children[0].value, multiline_variant=node.children[0].multiline_variant)}  "
                    f"{node.children[0].comment}".rstrip()
                )
                return

            if is_first_collection_child:
                lines.append(
                    f"{TAB_AS_SPACES * (depth-1)}- {node.value}: "
                    f"{stringify_yaml(node.children[0].value)}  "
                    f"{node.children[0].comment}".rstrip()
                )
                return

            # Handle multi-line statements. In theory this will probably only ever be strings, but we'll try to account
            # for other types.
            #
            # By the language spec, # symbols do not indicate comments on multiline strings.
            if node.children[0].multiline_variant != MultilineVariant.NONE:
                # TODO should we even render comments in multi-line strings? I don't believe they are valid.
                multi_variant: Final[MultilineVariant] = node.children[0].multiline_variant
                start_idx = 0
                # Quoted multiline strings with backslashes are special. They start by rendering on the same line as
                # their key.
                if multi_variant == MultilineVariant.BACKSLASH_QUOTE:
                    start_idx = 1
                    lines.append(
                        f"{spaces}{node.value}: {cast(list[str], node.children[0].value)[0]} {node.comment}".rstrip()
                    )
                else:
                    lines.append(f"{spaces}{node.value}: {multi_variant}  {node.comment}".rstrip())
                for val_line in cast(list[str], node.children[0].value)[start_idx:]:
                    lines.append(
                        f"{spaces}{TAB_AS_SPACES}"
                        f"{stringify_yaml(val_line, multiline_variant=multi_variant)}".rstrip()
                    )
                return
            lines.append(
                f"{spaces}{node.value}: "
                f"{stringify_yaml(node.children[0].value)}  "
                f"{node.children[0].comment}".rstrip()
            )
            return

        depth_delta = 1
        # Don't render a `:` for the non-visible root node. Also don't render invisible collection nodes.
        if depth > -1 and not node.is_collection_element():
            list_prefix = ""
            # Creating a copy of `spaces` scoped to this check prevents a scenario in which child nodes of this
            # collection element are missing one indent-level. The indent now only applies to the collection element.
            # Example:
            #   - script:
            #     - foo  # Incorrect
            #       - foo  # Correct
            tmp_spaces = spaces
            # Handle special cases for the "parent" key
            if node.list_member_flag:
                list_prefix = "- "
                depth_delta += 1
            if is_first_collection_child:
                list_prefix = "- "
                tmp_spaces = tmp_spaces[TAB_SPACE_COUNT:]
            # Nodes representing collections in a list have nothing to render
            lines.append(f"{tmp_spaces}{list_prefix}{node.value}:  {node.comment}".rstrip())

        for child in node.children:
            # Top-level empty-key edge case: Top level keys should have no additional indentation.
            extra_tab = "" if depth < 0 else TAB_AS_SPACES
            # Comments in a list are indented to list-level, but do not include a list `-` mark
            if child.is_comment():
                # Top-of-file comments are rendered at the top-level `render()` call in V0. We skip them here to prevent
                # duplicating comments and accidentally rendering values on a comment block.
                if schema_version == SchemaVersion.V0 and child.is_tof_comment():
                    continue
                lines.append(f"{spaces}{extra_tab}" f"{child.comment}".rstrip())
            # Empty keys can be easily confused for leaf nodes. The difference is these nodes render with a "dangling"
            # `:` mark
            elif child.is_empty_key():
                lines.append(f"{spaces}{extra_tab}" f"{stringify_yaml(child.value)}:  " f"{child.comment}".rstrip())
            # Leaf nodes are rendered as members in a list
            elif child.is_strong_leaf():
                lines.append(f"{spaces}{extra_tab}- " f"{stringify_yaml(child.value)}  " f"{child.comment}".rstrip())
            else:
                RecipeReader._render_tree(child, depth + depth_delta, lines, schema_version, node)
            # By tradition, recipes have a blank line after every top-level section, unless they are a comment. Comments
            # should be left where they are.
            if depth < 0 and not child.is_comment():
                lines.append("")

    def render(self, omit_trailing_newline: bool = False) -> str:
        """
        Takes the current state of the parse tree and returns the recipe file as a string.

        :returns: String representation of the recipe file
        """
        lines: list[str] = []

        # Render variable set section for V0 recipes. V1 recipes have variables stored in the parse tree under
        # `/context`.
        if self._schema_version == SchemaVersion.V0:
            # Rendering comments before the variable table is not an issue in V1 as variables are inherently part of the
            # tree structure.
            for root_child in self._root.children:
                if not root_child.is_tof_comment():
                    break
                # NOTE: Top of file comments must be owned by the root level and, therefore, do not need indentation.
                lines.append(root_child.comment.rstrip())

            for key, node_vars in self._vars_tbl.items():
                for node_var in node_vars:
                    lines.append(f"{{% set {key} = {node_var.render_v0_value()} %}}{node_var.render_comment()}")
            # Add spacing if variables have been set
            if len(self._vars_tbl):
                lines.append("")

        # Render parse-tree, -1 is passed in as the "root-level" is not directly rendered in a YAML file; it is merely
        # implied.
        RecipeReader._render_tree(self._root, -1, lines, self._schema_version)

        if omit_trailing_newline and lines and lines[-1] == "":
            lines = lines[:-1]

        return "\n".join(lines)

    def _preprocess_node_value(self, node: Node, replace_variables: bool) -> JsonType:
        """
        Handle multi-line strings and variable replacement.

        :param node: Node from which to extract the value to preprocess
        :param replace_variables: If set to True, this replaces all variable substitutions with their set values.
        :raises SentinelTypeEvaluationException: If the node value is a sentinel type
        :returns: Preprocessed value
        """
        if isinstance(node.value, SentinelType):
            raise SentinelTypeEvaluationException(node)
        value: Final = normalize_multiline_strings(node.value, node.multiline_variant)
        if isinstance(value, str):
            if replace_variables:
                return self._render_jinja_vars(value)
            if node.multiline_variant != MultilineVariant.NONE:
                return cast(str, yaml.load(value, Loader=self._yaml_loader))
        return cast(JsonType, value)

    @no_type_check
    def _render_object_tree(self, node: Node, replace_variables: bool, data: JsonType) -> None:
        # pylint: disable=too-complex
        # TODO Refactor and simplify ^
        """
        Recursive helper function that traverses the parse tree to generate a Pythonic data object.

        :param node: Current node in the tree
        :param replace_variables: If set to True, this replaces all variable substitutions with their set values.
        :param data: Accumulated data structure
        :raises SentinelTypeEvaluationException: If a node value with a sentinel type is evaluated.
        """

        # Ignore comment-only nodes
        if node.is_comment():
            return

        # Handle terminal nodes
        if node.is_empty_key():
            if isinstance(data, list):
                data.append({node.value: None})
            elif isinstance(data, dict):
                data[node.value] = None
            return

        if node.is_single_key():
            child_value = self._preprocess_node_value(node.children[0], replace_variables)
            if node.children[0].list_member_flag:
                child_value = [child_value]
            if isinstance(data, list):
                data.append({node.value: child_value})
            elif isinstance(data, dict):
                data[node.value] = child_value
            return

        if node.is_strong_leaf():
            # At this point, we know the data is a list
            data.append(self._preprocess_node_value(node, replace_variables))
            return

        # Process collection nodes (lists or dicts that are list members)
        if node.is_collection_element():
            if node.contains_list():
                elem_json = []
            else:
                elem_json = {}
            for element in node.children:
                self._render_object_tree(element, replace_variables, elem_json)
            data.append(elem_json)
            return

        # List nodes (lists that are not list members)
        if node.contains_list():
            key = node.value
            data.setdefault(key, [])
            for element in node.children:
                self._render_object_tree(element, replace_variables, data[key])
            return

        # What should remain is dicts that are not list members
        key = node.value
        data.setdefault(key, {})
        for element in node.children:
            self._render_object_tree(element, replace_variables, data[key])
        return

    def _render_to_object(self, replace_variables: bool = False, root_node: Optional[Node] = None) -> JsonType:
        """
        Takes the underlying state of the parse tree and produces a Pythonic object/dictionary representation. Analogous
        to `json.load()`.
        NOTE: This private function is used to hide the Node class (which is private) from the public interface.

        :param replace_variables: (Optional) If set to True, this replaces all variable substitutions with their set
            values.
        :param root_node: (Optional) If provided, this will use the provided node as the root node instead of the
            default root node.
        :raises SentinelTypeEvaluationException: If a node value with a sentinel type is evaluated.
        :returns: Pythonic data object representation of the recipe.
        """
        if root_node is None:
            root_node = self._root

        # Handle terminal nodes immediately
        if root_node.is_empty_key():
            return None
        if root_node.is_single_key():
            child_value = self._preprocess_node_value(root_node.children[0], replace_variables)
            if root_node.children[0].list_member_flag:
                child_value = [child_value]
            return child_value
        if root_node.is_strong_leaf():
            return self._preprocess_node_value(root_node, replace_variables)

        # Bootstrap/flatten the root-level
        data: JsonType = [] if root_node.contains_list() else {}
        for child in root_node.children:
            self._render_object_tree(child, replace_variables, data)

        return data

    def render_to_object(self, replace_variables: bool = False) -> JsonType:
        """
        Takes the underlying state of the parse tree and produces a Pythonic object/dictionary representation. Analogous
        to `json.load()`.

        :param replace_variables: (Optional) If set to True, this replaces all variable substitutions with their set
            values.
        :raises SentinelTypeEvaluationException: If a node value with a sentinel type is evaluated.
        :returns: Pythonic data object representation of the recipe.
        """
        return self._render_to_object(replace_variables)

    ## YAML Access Functions ##

    def list_value_paths(self) -> list[str]:
        """
        Provides a list of all known terminal paths. This can be used by the caller to perform search operations.

        :returns: List of all terminal paths in the parse tree.
        """
        lst: list[str] = []

        def _find_paths(node: Node, path_stack: StrStack) -> None:
            if node.is_leaf():
                lst.append(stack_path_to_str(path_stack))

        traverse_all(self._root, _find_paths)
        return lst

    def contains_value(self, path: str) -> bool:
        """
        Determines if a value (via a path) is contained in this recipe. This also allows the caller to determine if a
        path exists.

        :param path: JSON patch (RFC 6902)-style path to a value.
        :returns: True if the path exists. False otherwise.
        """
        path_stack = str_to_stack_path(path)
        return traverse(self._root, path_stack) is not None

    def get_value(self, path: str, default: JsonType | SentinelType = _sentinel, sub_vars: bool = False) -> JsonType:
        """
        Retrieves a value at a given path. If the value is not found, return a specified default value or throw.

        :param path: JSON patch (RFC 6902)-style path to a value.
        :param default: (Optional) If the value is not found, return this value instead.
        :param sub_vars: (Optional) If set to True and the value contains a Jinja template variable, the Jinja value
            will be "rendered". Any variables that can't be resolved will be escaped with `${{ }}`.
        :raises KeyError: If the value is not found AND no default is specified
        :raises SentinelTypeEvaluationException: If a node value with a sentinel type is evaluated.
        :returns: If found, the value in the recipe at that path. Otherwise, the caller-specified default value.
        """
        path_stack = str_to_stack_path(path)
        node = traverse(self._root, path_stack)

        # Handle if the path was not found or is an empty key
        if node is None:
            if default == RecipeReader._sentinel or isinstance(default, SentinelType):
                raise KeyError(f"No value/key found at path {path!r}")
            return default

        return self._render_to_object(sub_vars, node)

    def find_value(self, value: Primitives) -> list[str]:
        """
        Given a value, find all the paths that contain that value.

        NOTE: This only supports searching for "primitive" values, i.e. you cannot search for collections.

        :param value: Value to find in the recipe.
        :raises ValueError: If the value provided is not a primitive type.
        :returns: List of paths where the value can be found.
        """
        if not isinstance(value, PRIMITIVES_TUPLE):
            raise ValueError(f"A non-primitive value was provided: {value}")

        paths: list[str] = []

        def _find_value_paths(node: Node, path_stack: StrStack) -> None:
            # Special cases:
            #   - Empty keys imply a null value, although they don't contain a null child.
            #   - Types are checked so bools aren't simplified to "truthiness" evaluations.
            if (value is None and node.is_empty_key()) or (
                node.is_strong_leaf()
                and type(node.value) == type(value)  # pylint: disable=unidiomatic-typecheck
                and node.value == value
            ):
                paths.append(stack_path_to_str(path_stack))

        traverse_all(self._root, _find_value_paths)

        return paths

    def get_recipe_name(self) -> Optional[str]:
        """
        Convenience function that retrieves the "name" of a recipe file. This can be used as an identifier, but it
        is not guaranteed to be unique. In V0 recipes and single-output V1 recipes, this is known as the "package name".

        In V1 recipe files, the name must be included to pass the schema check that should be enforced by any build
        system.

        :raises SentinelTypeEvaluationException: If a node value with a sentinel type is evaluated.
        :returns: The name associated with the recipe file. In the unlikely event that no name is found, `None` is
            returned instead.
        """

        if self._schema_version == SchemaVersion.V1 and self.is_multi_output():
            return optional_str(self.get_value("/recipe/name", sub_vars=True, default=None))
        return optional_str(self.get_value("/package/name", sub_vars=True, default=None))

    ## General Convenience Functions ##

    def is_multi_output(self) -> bool:
        """
        Indicates if a recipe is a "multiple output" recipe.

        :returns: True if the recipe produces multiple outputs. False otherwise.
        """
        return self.contains_value("/outputs")

    def is_python_recipe(self) -> bool:
        """
        Indicates if a recipe is a "pure Python" recipe.

        :raises SentinelTypeEvaluationException: If a node value with a sentinel type is evaluated.
        :return: True if the recipe is a "pure Python recipe". False otherwise.
        """
        # TODO cache this or otherwise find a way to reduce the computation complexity.
        # TODO consider making a single query interface similar to `RecipeReaderDeps::get_all_dependencies()`
        # TODO improve definition/validation of "pure Python"
        for base_path in self.get_package_paths():
            # A "pure python" package shouldn't need a `build` dependencies.
            build_deps = cast(
                Optional[list[str | dict[str, str]]],
                self.get_value(RecipeReader.append_to_path(base_path, "/requirements/build"), default=[]),
            )
            if build_deps:
                return False

            host_path = RecipeReader.append_to_path(base_path, "/requirements/host")
            host_deps = cast(Optional[list[str | dict[str, str]]], self.get_value(host_path, default=[]))
            # Skip the rare edge case where the list may be null (usually caused by commented-out code)
            if host_deps is None:
                continue
            for i, dep in enumerate(host_deps):
                # If we find a selector on a line, ignore it. Conditionalized `python` inclusion does not indicate
                # something that is "pure Python". We check for V1 selectors first as it is cheaper and prevents a
                # a type issue. We do not check which schema the current recipe for the sake of the recipe converter,
                # which uses this function in the upgrade process.
                # TODO Improve V1 selector check (when more utilities are built). Checking for
                if not isinstance(dep, str):
                    continue
                if "python" == cast(str, dependency_data_from_str(dep).name).lower():
                    # The V0 selector check is more costly and it can be delayed until we've determined we have found
                    # a python host dependency.
                    if self.contains_selector_at_path(RecipeReader.append_to_path(host_path, f"/{i}")):
                        continue
                    return True
        return False

    def get_package_paths(self) -> list[str]:
        """
        Convenience function that returns the locations of all "outputs" in the `/outputs` directory AND the root/
        top-level of the recipe file. Combined with a call to `get_value()` with a default value and a for loop, this
        should easily allow the calling code to handle editing/examining configurations found in:

          - "Simple" (non-multi-output) recipe files
          - Multi-output recipe files
          - Recipes that have both top-level and multi-output sections. An example can be found here:
              https://github.com/AnacondaRecipes/curl-feedstock/blob/master/recipe/meta.yaml

        :raises SentinelTypeEvaluationException: If a node value with a sentinel type is evaluated.
        """
        paths: list[str] = ["/"]

        outputs: Final[list[str]] = cast(list[str], self.get_value("/outputs", []))
        for i in range(len(outputs)):
            paths.append(f"/outputs/{i}")

        return paths

    @staticmethod
    def append_to_path(base_path: str, ext_path: str) -> str:
        """
        Convenience function meant to be paired with `get_package_paths()` to generate extended paths. This handles
        issues that arise when concatenating paths that do or do not include a trailing/leading `/` character. Most
        notably, the root path `/` inherently contains a trailing `/`.

        :param base_path: Base path, provided by `get_package_paths()`
        :param ext_path: Path to append to the end of the `base_path`
        :returns: A normalized path constructed by the two provided paths.
        """
        # Ensure the base path always ends in a `/`
        if not base_path:
            base_path = "/"
        if base_path[-1] != "/":
            base_path += "/"
        # Ensure the extended path never starts with a `/`
        if ext_path and ext_path[0] == "/":
            ext_path = ext_path[1:]
        return f"{base_path}{ext_path}"

    def get_dependency_paths(self) -> list[str]:
        """
        Convenience function that returns a list of all dependency lines in a recipe.

        :raises SentinelTypeEvaluationException: If a node value with a sentinel type is evaluated.
        :returns: A list of all paths in a recipe file that point to dependencies.
        """
        paths: list[str] = []
        req_sections: Final[list[str]] = [
            dependency_section_to_str(DependencySection.BUILD, self._schema_version),
            dependency_section_to_str(DependencySection.HOST, self._schema_version),
            dependency_section_to_str(DependencySection.RUN, self._schema_version),
            dependency_section_to_str(DependencySection.RUN_CONSTRAINTS, self._schema_version),
        ]

        # Convenience function that reduces repeated logic between regular and multi-output recipes
        def _scan_requirements(path_prefix: str = "") -> None:
            for section in req_sections:
                section_path = f"{path_prefix}/requirements/{section}"
                # Relying on `get_value()` ensures that we will only examine literal values and ignore comments
                # in-between dependencies.
                value = self.get_value(section_path, [])
                # Handle empty keys
                if value is None:
                    continue
                dependencies = cast(list[str], value)
                for i in range(len(dependencies)):
                    paths.append(f"{section_path}/{i}")

        # Scan for both multi-output and non-multi-output recipes. Here is an example of a recipe that has both:
        #   https://github.com/AnacondaRecipes/curl-feedstock/blob/master/recipe/meta.yaml
        _scan_requirements()

        outputs = cast(list[JsonType], self.get_value("/outputs", []))
        for i in range(len(outputs)):
            _scan_requirements(f"/outputs/{i}")

        return paths

    ## Jinja Variable Functions ##

    def list_variables(self) -> list[str]:
        """
        Returns variables found in the recipe, sorted by first appearance.

        :returns: List of variables found in the recipe.
        """
        return list(self._vars_tbl.keys())

    def contains_variable(self, var: str) -> bool:
        """
        Determines if a variable is set in this recipe.

        :param var: Variable to check for.
        :returns: True if a variable name is found in this recipe. False otherwise.
        """
        return var in self._vars_tbl

    def get_variable(self, var: str, default: JsonType | SentinelType = _sentinel) -> JsonType:
        """
        Returns the value of a variable set in the recipe. If specified, a default value will be returned if the
        variable name is not found.

        :param var: Variable of interest check for.
        :param default: (Optional) If the value is not found, return this value instead.
        :raises KeyError: If the value is not found AND no default is specified
        :returns: The value (or specified default value if not found) of the variable name provided.
        """
        if var not in self._vars_tbl:
            if default == RecipeReader._sentinel or isinstance(default, SentinelType):
                raise KeyError
            return default
        return self._eval_var(var)

    def get_variable_references(self, var: str) -> list[str]:
        """
        Returns a list of paths that use particular variables.

        :param var: Variable of interest
        :returns: List of paths that use a variable, sorted by first appearance.
        """
        if var not in self._vars_tbl:
            return []

        path_list: list[str] = []

        # The regular expression between the braces is very forgiving to match JINJA expressions like
        # `{{ name | lower }}`
        def _init_re() -> re.Pattern[str]:
            match self._schema_version:
                case SchemaVersion.V0:
                    return re.compile(r"{{.*" + var + r".*}}")
                case SchemaVersion.V1:
                    return re.compile(r"\${{.*" + var + r".*}}")

        var_re: Final[re.Pattern[str]] = _init_re()

        def _collect_var_refs(node: Node, path: StrStack) -> None:
            # Variables can only be found inside string values.
            if isinstance(node.value, str) and var_re.search(node.value):
                path_list.append(stack_path_to_str(path))

        traverse_all(self._root, _collect_var_refs)
        return dedupe_and_preserve_order(path_list)

    ## Selector Functions ##

    def list_selectors(self) -> list[str]:
        """
        Returns selectors found in the recipe, sorted by first appearance.

        :returns: List of selectors found in the recipe.
        """
        return list(self._selector_tbl.keys())

    def contains_selector(self, selector: str) -> bool:
        """
        Determines if a selector expression is present in this recipe.

        :param selector: Selector to check for.
        :returns: True if a selector is found in this recipe. False otherwise.
        """
        return selector in self._selector_tbl

    def get_selector_paths(self, selector: str) -> list[str]:
        """
        Given a selector (including the surrounding brackets), provide a list of paths in the parse tree that use that
        selector.

        Selector paths will be ordered by the line they appear on in the file.

        :param selector: Selector of interest.
        :returns: A list of all known paths that use a particular selector
        """
        # We return a tuple so that caller doesn't accidentally modify a private member variable.
        if not self.contains_selector(selector):
            return []
        path_list: list[str] = []
        for path_stack in self._selector_tbl[selector]:
            path_list.append(stack_path_to_str(path_stack.path))
        # The list should be de-duped and maintain order. Duplications occur when key-value pairings mean a selector
        # occurs on two nodes with the same path.
        #
        # For example:
        #   skip: True  # [unix]
        # The nodes for both `skip` and `True` contain the comment `[unix]`
        return dedupe_and_preserve_order(path_list)

    def contains_selector_at_path(self, path: str) -> bool:
        """
        Given a path, determine if a selector exists on that line.

        :param path: Target path
        :returns: True if the selector exists at that path. False otherwise.
        """
        path_stack = str_to_stack_path(path)
        node = traverse(self._root, path_stack)
        if node is None:
            return False
        return bool(Regex.SELECTOR.search(node.comment))

    def get_selector_at_path(self, path: str, default: str | SentinelType = _sentinel) -> str:
        """
        Given a path, return the selector that exists on that line.

        :param path: Target path
        :param default: (Optional) Default value to use if no selector is found.
        :raises KeyError: If a selector is not found on the provided path AND no default has been specified.
        :raises ValueError: If the default selector provided is malformed
        :returns: Selector on the path provided
        """
        path_stack = str_to_stack_path(path)
        node = traverse(self._root, path_stack)
        if node is None:
            raise KeyError(f"Path not found: {path}")

        search_results = Regex.SELECTOR.search(node.comment)
        if not search_results:
            # Use `default` case
            if default != RecipeReader._sentinel and not isinstance(default, SentinelType):
                if not Regex.SELECTOR.match(default):
                    raise ValueError(f"Invalid selector provided: {default}")
                return default
            raise KeyError(f"Selector not found at path: {path}")
        return search_results.group(0)

    ## Comment Functions ##

    def get_comments_table(self) -> dict[str, str]:
        """
        Returns a dictionary containing the location of every comment mapped to the value of the comment.
        NOTE:
            - Selectors are not considered to be comments.
            - Lines containing only comments are currently not addressable by our pathing scheme, so they are omitted.
              For our current purposes (of upgrading the recipe format) this should be fine. Non-addressable values
              should be less likely to be removed from patch operations.

        :returns: Dictionary of paths where comments can be found mapped to the comment found.
        """
        comments_tbl: dict[str, str] = {}

        def _track_comments(node: Node, path_stack: StrStack) -> None:
            if node.is_comment() or node.comment == "":
                return
            comment = node.comment
            # Handle comments found alongside a selector
            if Regex.SELECTOR.search(comment):
                comment = Regex.SELECTOR.sub("", comment).strip()
                # Sanitize common artifacts left from removing the selector
                comment = comment.replace("#  # ", "# ", 1).replace("#  ", "# ", 1)

                # Reject selector-only comments
                if comment in {"", "#"}:
                    return
                if comment[0] != "#":
                    comment = f"# {comment}"

            path = stack_path_to_str(path_stack)
            comments_tbl[path] = comment

        traverse_all(self._root, _track_comments)
        return comments_tbl

    def search(self, regex: str | re.Pattern[str], include_comment: bool = False) -> list[str]:
        """
        Given a regex string, return the list of paths that match the regex.
        NOTE: This function only searches against primitive values. All variables and selectors can be fully provided by
        using their respective `list_*()` functions.

        :param regex: Regular expression to match with
        :param include_comment: (Optional) If set to `True`, this function will execute the regular expression on values
            WITH their comments provided. For example: `42  # This is a comment`
        :returns: Returns a list of paths where the matched value was found.
        """
        re_obj = re.compile(regex)
        paths: list[str] = []

        def _search_paths(node: Node, path_stack: StrStack) -> None:
            value = str(stringify_yaml(node.value))
            if include_comment and node.comment:
                value = f"{value}{TAB_AS_SPACES}{node.comment}"
            if node.is_strong_leaf() and re_obj.search(value):
                paths.append(stack_path_to_str(path_stack))

        traverse_all(self._root, _search_paths)

        return paths

    def calc_sha256(self) -> str:
        """
        Generates a SHA-256 hash of recipe's contents. This hash is the same as if the current recipe state was written
        to a file. NOTE: This may not be the same as the original recipe file as the parser will auto-format text.

        :returns: SHA-256 hash of the current recipe state.
        """
        return hash_str(self.render(), hashlib.sha256)
