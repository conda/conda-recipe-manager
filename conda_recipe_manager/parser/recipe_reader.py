"""
:Description: Provides a class that takes text from a Jinja-formatted recipe file and parses it. This allows for easy
              semantic understanding of the file. This is the primary base-class to all other Recipe Parsing classes.
"""

from __future__ import annotations

import ast
import hashlib
import re
import sys
from collections.abc import Callable
from typing import Final, Optional, cast, no_type_check

import yaml

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
from conda_recipe_manager.parser.selector_parser import SelectorParser
from conda_recipe_manager.parser.types import TAB_AS_SPACES, TAB_SPACE_COUNT, MultilineVariant
from conda_recipe_manager.parser.v0_recipe_formatter import V0RecipeFormatter
from conda_recipe_manager.types import PRIMITIVES_TUPLE, JsonType, Primitives, SentinelType
from conda_recipe_manager.utils.cryptography.hashing import hash_str
from conda_recipe_manager.utils.typing import optional_str

# Import guard: Fallback to `SafeLoader` if `CSafeLoader` isn't available
try:
    from yaml import CSafeLoader as SafeLoader
except ImportError:
    from yaml import SafeLoader  # type: ignore[assignment]

# Type for the internal recipe variables table.
_VarTable = dict[str, NodeVar]


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
    def _parse_yaml(s: str, parser: Optional[RecipeReader] = None) -> JsonType:
        """
        Parse a line (or multiple) of YAML into a Pythonic data structure

        :param s: String to parse
        :param parser: (Optional) If provided, this will substitute Jinja variables with values specified in in the
            recipe file. Since `_parse_yaml()` is critical to constructing recipe files, this function must remain
            static. Also, during construction, we shouldn't be using a variables until the entire recipe is read/parsed.
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
                output = _sub_jinja(cast(JsonType, yaml.load(s, Loader=SafeLoader)))
            except yaml.scanner.ScannerError:
                # We quote-escape here for problematic YAML strings that are non-JINJA, like `**/lib.so`. Parsing
                # invalid YAML containing V0 JINJA statements should cause an exception and fallback to the other
                # recovery logic.
                output = _sub_jinja(cast(JsonType, yaml.load(quote_special_strings(s), Loader=SafeLoader)))
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
                    cast(JsonType, yaml.load(s, Loader=SafeLoader)), lambda d: substitute_markers(d, sub_list)
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
    def _parse_line_node(s: str, only_seen_comments: bool) -> Node:
        """
        Parses a line of conda-formatted YAML into a Node.

        Latest YAML spec can be found here: https://yaml.org/spec/1.2.2/

        :param s: Pre-stripped (no leading/trailing spaces), non-Jinja line of a recipe file.
        :param only_seen_comments: Flag indicating if only comments have been seen at the top of the file thus far.
        :returns: A Node representing a line of the conda-formatted YAML.
        """
        # Use PyYaml to safely/easily/correctly parse single lines of YAML.
        output = RecipeReader._parse_yaml(s)

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
            return Node(value=cast(Primitives, output[0]), comment=comment, list_member_flag=True)
        # Other types are just leaf nodes. This is scenario should likely not be triggered given our recipe files don't
        # have single valid lines of YAML, but we cover this case for the sake of correctness.
        return Node(value=output, comment=comment)

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
            return RecipeReader(  # pylint: disable=protected-access
                # NOTE: `yaml.dump()` defaults to 80 character lines. Longer lines may have newlines unexpectedly
                #       injected into this value, screwing up the parse-tree.
                yaml.dump(value, Dumper=ForceIndentDumper, sort_keys=False, width=sys.maxsize)  # type: ignore[misc]
            )._root.children

        # Primitives can be safely stringified to generate a parse tree.
        return RecipeReader(str(stringify_yaml(value)))._root.children  # pylint: disable=protected-access

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

    @staticmethod
    def _set_key_and_matches(
        key: str,
    ) -> tuple[
        str,
        Optional[re.Match[str]],
        Optional[re.Match[str]],
        Optional[re.Match[str]],
        Optional[re.Match[str]],
        Optional[re.Match[str]],
        Optional[re.Match[str]],
        Optional[re.Match[str]],
    ]:
        """
        Helper function for `_render_jinja_vars()` that takes a JINJA statement (string inside the braces) and attempts
        to match and apply any currently supported "JINJA functions" to the statement.

        :param key: Sanitized key to perform JINJA functions on.
        :returns: The modified key, if any JINJA functions apply. Also returns any applicable match objects.
        """

        # Helper function that strips-out JINJA ops out of the string, `key`.
        def _strip_op(k: str, m: Optional[re.Match[str]]) -> str:
            if not m:
                return k
            return k.replace(m.group(), "").strip()

        # Example: {{ name | lower }}
        lower_match = Regex.JINJA_FUNCTION_LOWER.search(key)
        key = _strip_op(key, lower_match)

        # Example: {{ name | upper }}
        upper_match = Regex.JINJA_FUNCTION_UPPER.search(key)
        key = _strip_op(key, upper_match)

        # Example: {{ name | replace('-', '_') }
        replace_match = Regex.JINJA_FUNCTION_REPLACE.search(key)
        key = _strip_op(key, replace_match)

        # Example: {{ name | split('.') }
        split_match = Regex.JINJA_FUNCTION_SPLIT.search(key)
        # Example: {{ '.'.join(version.split(".")[:2]) }}
        join_match = Regex.JINJA_FUNCTION_JOIN.search(key)

        # Example: {{ name[0] }}
        idx_match = Regex.JINJA_FUNCTION_IDX_ACCESS.search(key)
        if idx_match:
            key = key.replace(f"[{cast(str, idx_match.group(2))}]", "").strip()

        # NOTE: `split` and `join` are special. `split` changes the type from a string to a list and `join` requires
        # a list to work as expected. As a workaround, we only apply `split` if a `join` or `index` operation is
        # present. Additionally, we only apply a `join` if a `split` is present.
        if split_match and join_match:
            key = _strip_op(key, split_match)
            # Re-calculate the join's match now that `split` has been removed.
            join_match = Regex.JINJA_FUNCTION_JOIN.search(key)
            if join_match:
                # If we are in the | form, remove the `join()` portion entirely
                if join_match.groups()[0] is not None:
                    key = _strip_op(key, join_match)
                # If we are in the `.` form, extract the key from the `.join()` call.
                else:
                    key = join_match.group(5)
            # This should not be possible, but we still want to guard against accidental list evaluation if a `join` is
            # no longer possible.
            else:
                join_match = None
                split_match = None
        elif split_match and idx_match:
            key = _strip_op(key, split_match)
        else:
            join_match = None
            split_match = None

        # Addition/concatenation. Note the key(s) will need to be evaluated later.
        # Example: {{ build_number + 100 }}
        # Example: {{ version + ".1" }}
        add_concat_match = Regex.JINJA_FUNCTION_ADD_CONCAT.search(key)

        return key, lower_match, upper_match, replace_match, split_match, join_match, idx_match, add_concat_match

    def _eval_jinja_token(self, s: str) -> JsonType:
        """
        Given a string that matches one of the two groups in the `JINJA_FUNCTION_ADD_CONCAT` regex, evaluate the
        string's intended value. NOTE: This does not invoke `eval()` for security reasons.

        :param s: The string to evaluate.
        :returns: The evaluated value of the string.
        """
        # Variable
        if s in self._vars_tbl:
            return self._vars_tbl[s].get_value()

        # int
        if s.isdigit():
            return int(s)

        # float
        try:
            return float(s)
        except ValueError:
            pass

        # Strip outer quotes, if applicable (unrecognized variables will be treated as strings).
        if s and s[0] == s[-1] and (s[0] == "'" or s[0] == '"'):
            return s[1:-1]
        return s

    def _render_jinja_vars(self, s: str) -> JsonType:
        # pylint: disable=too-complex
        # TODO Refactor and simplify. We should really consider using a proper parser over REGEX soup.
        """
        Helper function that replaces Jinja substitutions with their actual set values.

        :param s: String to be re-rendered
        :returns: The original value, augmented with Jinja substitutions. Types are re-rendered to account for multiline
            strings that may have been "normalized" prior to this call.
        """
        # TODO: Consider tokenizing expressions over using regular expressions. The scope of this function has expanded
        # drastically.

        start_idx, sub_regex = self._set_on_schema_version()

        # Search the string, replacing all substitutions we can recognize
        for match in cast(list[str], sub_regex.findall(s)):
            # The regex guarantees the string starts and ends with double braces
            key = match[start_idx:-2].strip()
            # Check for and interpret common JINJA functions
            key, lower_match, upper_match, replace_match, split_match, join_match, idx_match, add_concat_match = (
                RecipeReader._set_key_and_matches(key)
            )

            if add_concat_match:
                lhs = self._eval_jinja_token(cast(str, add_concat_match.group(1)))
                rhs = self._eval_jinja_token(cast(str, add_concat_match.group(2)))
                # By default concat two strings and quote them. This ensures YAML will interpret the type correctly.
                value = f'"{str(lhs) + str(rhs)}"'
                # Otherwise, perform arithmetic addition, IFF both sides are numeric types.
                if isinstance(lhs, (int, float)) and isinstance(rhs, (int, float)):
                    value = str(lhs + rhs)
                s = s.replace(match, value)
            elif key in self._vars_tbl:
                # Replace value as a string. Re-interpret the entire value before returning.
                value = str(self._vars_tbl[key].get_value())
                if Regex.JINJA_VAR_VALUE_TERNARY.match(value):
                    value = "${{" + value + "}}"
                if lower_match:
                    value = value.lower()
                if upper_match:
                    value = value.upper()
                # NOTE: We previously guarantee in `_set_key_and_matches()` that `split` is accompanied by a operation
                # that will normalize it back to a string. But for this to work, we must perform the `split` before a
                # `join` or an index access.
                if split_match:
                    value = value.split(split_match.group(2))  # type: ignore[assignment]
                if join_match:
                    # The index of the string that we join on changes depending on which form of the function is used.
                    # NOTE: `.groups()` does not return the top-level 0th grouping, so the indices are 1-off.
                    join_str_idx = 3 if join_match.groups()[2] is not None else 2
                    value = join_match.group(join_str_idx).join(value)
                if idx_match:
                    idx = int(cast(str, idx_match.group(2)))
                    # From our research, it looks like string indexing on JINJA variables is almost exclusively used
                    # get the first character in a string. If the index is out of bounds, we will default to the
                    # variable's value as a fall-back. Although rare, negative indexing is supported.
                    if -len(value) <= idx < len(value):
                        value = value[idx]
                if replace_match:
                    value = value.replace(replace_match.group(2), replace_match.group(3))
                s = s.replace(match, value)

        # If there is leading V0 (unescaped) JINJA that was not able to be fully rendered, it will not be able to be
        # parsed by PyYaml. So it is best to just return the value as a string, without evaluating the type (which, to
        # be clear, should be a string).
        if self._schema_version == SchemaVersion.V0 and s[:2] == "{{":
            return s
        return cast(JsonType, yaml.load(s, Loader=SafeLoader))

    def _init_vars_tbl(self) -> None:
        """
        Initializes the variable table, `vars_tbl` based on the document content.
        Requires parse-tree and `_schema_version` to be initialized.
        """
        # Tracks Jinja variables set by the file
        self._vars_tbl: _VarTable = {}

        match self._schema_version:
            case SchemaVersion.V0:
                # Find all the set statements and record the values
                for line in cast(list[str], Regex.JINJA_V0_SET_LINE.findall(self._init_content)):
                    key = line[line.find("set") + len("set") : line.find("=")].strip()
                    value: str | JsonType = line[line.find("=") + len("=") : line.find("%}")].strip()
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
                    self._vars_tbl[key] = NodeVar(value, RecipeReader._parse_trailing_comment(line))
            case SchemaVersion.V1:
                # Abuse the fact that the `/context` section is pure YAML.
                context: Final = cast(dict[str, JsonType], self.get_value("/context", {}))
                comments_tbl: Final = self.get_comments_table()
                for key, value in context.items():
                    # V1 only allows for scalar types as variables. So we should be able to recover all comments without
                    # recursing through `/context`
                    var_path = RecipeReader.append_to_path("/context", key)
                    self._vars_tbl[key] = NodeVar(value, comments_tbl.get(var_path, None))

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

    def __init__(self, content: str):
        # pylint: disable=too-complex
        # TODO Refactor and simplify ^
        """
        Constructs a RecipeReader instance.

        :param content: conda-build formatted recipe file, as a single text string.
        """
        super().__init__()
        # The initial, raw, text is preserved for diffing and debugging purposes
        self._init_content: Final[str] = content

        # Root of the parse tree
        self._root = Node(value=ROOT_NODE_VALUE)

        # Format the text for V0 recipe files in an attempt to improve compatibility with our whitespace-delimited
        # parser.
        fmt: Final[V0RecipeFormatter] = V0RecipeFormatter(self._init_content)
        if fmt.is_v0_recipe():
            fmt.fmt_text()
        # Calculate the string equivalent once.
        fmt_str: Final = str(fmt)

        # For V0 recipe files, count the number of comment-only lines at the start, before the canonical "variables
        # section"
        tof_comment_cntr = 0
        if fmt.is_v0_recipe():
            while fmt_str.splitlines()[tof_comment_cntr].startswith("#"):
                tof_comment_cntr += 1

        # Replace all Jinja lines. Then traverse line-by-line
        sanitized_yaml: Final = Regex.JINJA_V0_LINE.sub("", fmt_str)

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
                new_node = RecipeReader._parse_line_node(clean_line, tof_comment_cntr > 0)
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
                # TODO Figure out tab-depth of the recipe being read. 4 spaces is technically valid in YAML
                depth_to_pop = (cur_indent - new_indent) // TAB_SPACE_COUNT
                for _ in range(depth_to_pop):
                    node_stack.pop()
            cur_indent = new_indent
            # Look at the stack to determine the parent Node and then append the current node to the new parent.
            parent = node_stack[-1]
            parent.children.append(new_node)
            # Update the last node for the next line interpretation
            last_node = new_node

        # Auto-detect and deserialize the version of the recipe schema. This will change how the class behaves.
        self._schema_version = SchemaVersion.V0
        # TODO bootstrap this better. `get_value()` has a circular dependency on `_vars_tbl` if `sub_vars` is used.
        schema_version = cast(SchemaVersion | int, self.get_value("/schema_version", SchemaVersion.V0))
        if isinstance(schema_version, int) and schema_version == 1:
            self._schema_version = SchemaVersion.V1

        # Initialize the variables table. This behavior changes per `schema_version`
        self._init_vars_tbl()

        # Now that the tree is built, construct a selector look-up table that tracks all the nodes that use a particular
        # selector. This will make it easier to.
        #
        # This table will have to be re-built or modified when the tree is modified with `patch()`.
        self._rebuild_selectors()

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
        for key, node_var in self._vars_tbl.items():
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
            elif child.is_leaf():
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

            for key, val in self._vars_tbl.items():
                lines.append(f"{{% set {key} = {val.render_v0_value()} %}}{val.render_comment()}")
            # Add spacing if variables have been set
            if len(self._vars_tbl):
                lines.append("")

        # Render parse-tree, -1 is passed in as the "root-level" is not directly rendered in a YAML file; it is merely
        # implied.
        RecipeReader._render_tree(self._root, -1, lines, self._schema_version)

        if omit_trailing_newline and lines and lines[-1] == "":
            lines = lines[:-1]

        return "\n".join(lines)

    @no_type_check
    def _render_object_tree(self, node: Node, replace_variables: bool, data: JsonType) -> None:
        # pylint: disable=too-complex
        # TODO Refactor and simplify ^
        """
        Recursive helper function that traverses the parse tree to generate a Pythonic data object.

        :param node: Current node in the tree
        :param replace_variables: If set to True, this replaces all variable substitutions with their set values.
        :param data: Accumulated data structure
        """
        # Ignore comment-only lines
        if node.is_comment():
            return

        key = cast(str, node.value)
        for child in node.children:
            # Ignore comment-only lines
            if child.is_comment():
                continue

            # Handle multiline strings and variable replacement
            value = normalize_multiline_strings(child.value, child.multiline_variant)
            if isinstance(value, str):
                if replace_variables:
                    value = self._render_jinja_vars(value)
                elif child.multiline_variant != MultilineVariant.NONE:
                    value = cast(str, yaml.load(value, Loader=SafeLoader))

            # Empty keys are interpreted to point to `None`
            if child.is_empty_key():
                data[key][child.value] = None
                continue

            # Collection nodes are skipped as they are placeholders. However, their children are rendered recursively
            # and added to a list.
            if child.is_collection_element():
                elem_dict = {}
                for element in child.children:
                    self._render_object_tree(element, replace_variables, elem_dict)
                if len(data[key]) == 0:
                    data[key] = []
                data[key].append(elem_dict)
                continue

            # List members accumulate values in a list
            if child.list_member_flag:
                if key not in data:
                    data[key] = []
                data[key].append(value)
                continue

            # Other (non list and non-empty-key) leaf nodes set values directly
            if child.is_leaf():
                data[key] = value
                continue

            # All other keys prep for containing more dictionaries
            data.setdefault(key, {})
            self._render_object_tree(child, replace_variables, data[key])

    def render_to_object(self, replace_variables: bool = False) -> JsonType:
        """
        Takes the underlying state of the parse tree and produces a Pythonic object/dictionary representation. Analogous
        to `json.load()`.

        :param replace_variables: (Optional) If set to True, this replaces all variable substitutions with their set
            values.
        :returns: Pythonic data object representation of the recipe.
        """
        data: JsonType = {}
        # Type narrow after assignment
        assert isinstance(data, dict)

        # Bootstrap/flatten the root-level
        for child in self._root.children:
            if child.is_comment():
                continue
            data.setdefault(cast(str, child.value), {})
            self._render_object_tree(child, replace_variables, data)

        return data

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
        TODO Refactor: This function could leverage `render_to_object()` to simplify/de-dupe the logic.

        :param path: JSON patch (RFC 6902)-style path to a value.
        :param default: (Optional) If the value is not found, return this value instead.
        :param sub_vars: (Optional) If set to True and the value contains a Jinja template variable, the Jinja value
            will be "rendered". Any variables that can't be resolved will be escaped with `${{ }}`.
        :raises KeyError: If the value is not found AND no default is specified
        :returns: If found, the value in the recipe at that path. Otherwise, the caller-specified default value.
        """
        path_stack = str_to_stack_path(path)
        node = traverse(self._root, path_stack)

        # Handle if the path was not found
        if node is None:
            if default == RecipeReader._sentinel or isinstance(default, SentinelType):
                raise KeyError(f"No value/key found at path {path!r}")
            return default

        return_value: JsonType = None
        # Handle unpacking of the last key-value set of nodes.
        if node.is_single_key() and not node.is_root():
            if node.children[0].multiline_variant != MultilineVariant.NONE:
                multiline_str = cast(
                    str,
                    normalize_multiline_strings(
                        cast(list[str], node.children[0].value), node.children[0].multiline_variant
                    ),
                )
                if sub_vars:
                    return self._render_jinja_vars(multiline_str)
                return cast(JsonType, yaml.load(multiline_str, Loader=SafeLoader))
            return_value = cast(Primitives, node.children[0].value)
        # Leaf nodes can return their value directly
        elif node.is_leaf():
            return_value = cast(Primitives, node.value)
        else:
            # NOTE: Traversing the tree and generating our own data structures will be more efficient than rendering and
            # leveraging the YAML parser, BUT this method re-uses code and is easier to maintain.
            lst: list[str] = []
            RecipeReader._render_tree(node, -1, lst, self._schema_version)
            return_value = "\n".join(lst)

        # Collection types are transformed into strings above and will need to be transformed into a proper data type.
        # `_parse_yaml()` will also render JINJA variables for us, if requested.
        if isinstance(return_value, str):
            parser = self if sub_vars else None
            parsed_value = RecipeReader._parse_yaml(return_value, parser)
            # Lists containing 1 value will drop the surrounding list by the YAML parser. To ensure greater consistency
            # and provide better type-safety, we will re-wrap such values.
            if not isinstance(parsed_value, list) and len(node.children) == 1 and node.children[0].list_member_flag:
                return [parsed_value]
            return parsed_value
        return return_value

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
                node.is_leaf()
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
                dependencies = cast(list[str], self.get_value(section_path, []))
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
        return self._vars_tbl[var].get_value()

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
            if node.is_leaf() and re_obj.search(value):
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
