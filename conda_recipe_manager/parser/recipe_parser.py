"""
:Description: Provides a class that takes text from a Jinja-formatted recipe file and parses it. This allows for easy
              semantic understanding and manipulation of the file.

              For historical reasons, this is called the `parser` even though it provides editing capabilities.
              Initially the `RecipeParser` class and `RecipeReader` class were one massive class.

              Patching these files is done using a JSON-patch like syntax. This project closely conforms to the
              RFC 6902 spec, but deviates in some specific ways to handle the Jinja variables and comments found in
              conda recipe files.

              Links:
              - https://jsonpatch.com/
              - https://datatracker.ietf.org/doc/html/rfc6902/

"""

from __future__ import annotations

import difflib
import re
from collections.abc import Callable
from typing import Final, Optional, TypeGuard, cast

from jsonschema import validate as schema_validate

from conda_recipe_manager.parser._node import Node
from conda_recipe_manager.parser._node_var import NodeVar
from conda_recipe_manager.parser._traverse import (
    INVALID_IDX,
    remap_child_indices_virt_to_phys,
    traverse,
    traverse_with_index,
)
from conda_recipe_manager.parser._types import Regex, StrStack
from conda_recipe_manager.parser._utils import str_to_stack_path
from conda_recipe_manager.parser.enums import SelectorConflictMode
from conda_recipe_manager.parser.exceptions import JsonPatchValidationException
from conda_recipe_manager.parser.recipe_reader import RecipeReader
from conda_recipe_manager.parser.selector_parser import SelectorParser
from conda_recipe_manager.parser.types import JSON_PATCH_SCHEMA
from conda_recipe_manager.types import PRIMITIVES_TUPLE, JsonPatchType, JsonType

# Callback that allows the caller to perform custom replacements using `search_and_patch_replace()`.
ReplacePatchFunc = Callable[[JsonType], JsonType]


class RecipeParser(RecipeReader):
    """
    Class that parses a recipe file string and provides editing tools for changing values in the document.
    """

    # Static set of patch operations that require `from`. The others require `value` or nothing.
    _patch_ops_requiring_from = set(["copy", "move"])

    ## Recipe Key Sorting ##

    def _sort_subtree_keys(self, sort_path: str, tbl: dict[str, int], rename: str = "") -> None:
        """
        Convenience function that sorts 1 level of keys, given a path. Optionally allows renaming of the target node.
        No changes are made if the path provided is invalid/does not exist.

        :param sort_path: Top-level path to target sorting of child keys
        :param tbl: Table describing how keys should be sorted. Lower-value key names appear towards the top of the list
        :param rename: (Optional) If specified, renames the top-level key
        """

        def _comparison(n: Node) -> int:
            return RecipeParser._canonical_sort_keys_comparison(n, tbl)

        node = traverse(self._root, str_to_stack_path(sort_path))  # pylint: disable=protected-access
        if node is None:
            return
        if rename:
            node.value = rename
        node.children.sort(key=_comparison)

    ## Pre-processing Recipe Text Functions ##

    @staticmethod
    def pre_process_remove_hash_type(content: str) -> str:
        """
        There is a common-enough-to-be-annoying pattern used in some recipe files where the `/source/sha256` key is
        stored as a variable. For example: `{{ hash_type }}: <hash>`

        This variable-as-a-key mechanism is not supported by the parser and causes issues for other tooling. This
        function, if run before parsing the recipe file, will remove and fix this pattern.

        :param content: Recipe file contents to pre-process
        :returns: Pre-processed recipe file contents, devoid of `hash_type` key/variable usage.
        """
        hash_type_var_variants: Final[set[str]] = {
            '{% set hash_type = "sha256" %}\n',
            '{% set hashtype = "sha256" %}\n',
            '{% set hash = "sha256" %}\n',  # NOTE: `hash` is also commonly used for the actual SHA-256 hash value
        }
        for hash_type_variant in hash_type_var_variants:
            content = content.replace(hash_type_variant, "")
        return Regex.PRE_PROCESS_JINJA_HASH_TYPE_KEY.sub("sha256:", content)

    ## JINJA Variable Editing Functions ##

    def set_variable(self, var: str, value: JsonType) -> None:
        """
        Adds or changes an existing Jinja variable.

        :param var: Variable to modify
        :param value: Value to set
        """
        self._vars_tbl[var] = NodeVar(value)
        self._is_modified = True

    def del_variable(self, var: str) -> None:
        """
        Remove a variable from the project. If one is not found, no changes are made.

        :param var: Variable to delete
        """
        if not var in self._vars_tbl:
            return
        del self._vars_tbl[var]
        self._is_modified = True

    ## Selector Editing Functions ##
    def add_selector(
        self, path: str, selector: str | SelectorParser, mode: SelectorConflictMode = SelectorConflictMode.REPLACE
    ) -> None:
        """
        Given a path, add a selector (include the surrounding brackets) to the line denoted by path.

        :param path: Path to add a selector to
        :param selector: Selector statement to add
        :param mode: (Optional) Indicates how to handle a conflict if a selector already exists at this path.
        :raises KeyError: If the path provided is not found
        :raises ValueError: If the selector provided is malformed
        """
        # TODO add V1 support
        path_stack = str_to_stack_path(path)
        node = traverse(self._root, path_stack)

        # Shim layer that allows us to support the newer SelectorParser object.
        # TODO Future: Swap the string usage in favor of using the SelectorParser.
        if isinstance(selector, SelectorParser):
            selector = selector.render()

        if node is None:
            raise KeyError(f"Path not found: {path!r}")
        if not Regex.SELECTOR.match(selector):
            raise ValueError(f"Invalid selector provided: {selector}")

        # Helper function that extracts the outer set of []'s in a selector
        def _extract_selector(s: str) -> str:
            return s.replace("[", "", 1)[::-1].replace("]", "", 1)[::-1]

        comment = ""
        old_selector_found = Regex.SELECTOR.search(node.comment)
        if node.comment == "" or mode == SelectorConflictMode.REPLACE:
            comment = f"# {selector}"
        # "Append" to existing selectors
        elif old_selector_found:
            logic_op = "and" if mode == SelectorConflictMode.AND else "or"
            old_selector = _extract_selector(old_selector_found.group())
            new_selector = _extract_selector(selector)
            comment = f"# [{old_selector} {logic_op} {new_selector}]"
        # If the comment is not a selector, put the selector first, then append the comment.
        else:
            # Strip the existing comment of it's leading `#` symbol
            comment = f"# {selector} " + node.comment.replace("#", "", 1).strip()

        node.comment = comment
        # Some lines of YAML correspond to multiple nodes. For consistency, we need to ensure that comments are
        # duplicate across all nodes on a line.
        if node.is_single_key():
            node.children[0].comment = comment

        self._rebuild_selectors()
        self._is_modified = True

    def remove_selector(self, path: str) -> Optional[str]:
        """
        Given a path, remove a selector to the line denoted by path.
        - If a selector does not exist, nothing happens.
        - If a comment exists after the selector, keep it, discard the selector.

        :param path: Path to add a selector to
        :raises KeyError: If the path provided is not found
        :returns: If found, the selector removed (includes surrounding brackets). Otherwise, returns None
        """
        path_stack = str_to_stack_path(path)
        node = traverse(self._root, path_stack)

        if node is None:
            raise KeyError(f"Path not found: {path!r}")

        search_results = Regex.SELECTOR.search(node.comment)
        if not search_results:
            return None

        selector = search_results.group(0)
        comment = node.comment.replace(selector, "")
        # Sanitize potential edge-case scenarios after a removal
        comment = comment.replace("#  ", "# ").replace("# # ", "# ")
        # Detect and remove empty comments. Other comments should remain intact.
        if comment.strip() == "#":
            comment = ""

        node.comment = comment
        # Some lines of YAML correspond to multiple nodes. For consistency, we need to ensure that comments are
        # duplicate across all nodes on a line.
        if node.is_single_key():
            node.children[0].comment = comment

        self._rebuild_selectors()
        self._is_modified = True
        return selector

    ## Comment Editing Functions ##

    def add_comment(self, path: str, comment: str) -> None:
        """
        Adds a comment to an existing path. If a comment exists, replaces the existing comment. If a selector exists,
        comment is appended after the selector component of the comment.

        :param path: Target path to add a comment to
        :param comment: Comment to add
        :raises KeyError: If the path provided is not found
        :raises ValueError: If the comment provided is a selector, the empty string, or consists of only whitespace
            characters
        """
        comment = comment.strip()
        if comment == "":
            raise ValueError("Comments cannot consist only of whitespace characters")

        if Regex.SELECTOR.match(comment):
            raise ValueError(f"Selectors can not be submitted as comments: {comment}")

        node = traverse(self._root, str_to_stack_path(path))

        if node is None:
            raise KeyError(f"Path not found: {path}")

        search_results = Regex.SELECTOR.search(node.comment)
        # If a selector is present, append the selector.
        if search_results:
            selector = search_results.group(0)
            if comment[0] == "#":
                comment = comment[1:].strip()
            comment = f"# {selector} {comment}"

        # Prepend a `#` if it is missing
        if comment[0] != "#":
            comment = f"# {comment}"
        node.comment = comment
        # Comments for "single key" nodes apply to both the parent and child. This is because such parent nodes render
        # on the same line as their children.
        if node.is_single_key():
            node.children[0].comment = comment
        self._is_modified = True

    ## YAML Patching Functions ##

    @staticmethod
    def _is_valid_patch_node(node: Optional[Node], node_idx: int) -> TypeGuard[Node]:
        """
        Indicates if the target node to perform a patch operation against is a valid node. This is based on the RFC spec
        for JSON patching paths.

        :param node: Target node to validate
        :param node_idx: If the caller is evaluating that a list member, exists, this is the VIRTUAL index into that
            list. Otherwise this value should be less than 0.
        :returns: True if the node can be patched. False otherwise.
        """
        # Path not found
        if node is None:
            return False

        # Leaf nodes contain values and not path information. Paths should not be made that access leaf nodes, with the
        # exception of members of a list and keys. Making such a path violates the RFC.
        if not node.list_member_flag and not node.key_flag and node.is_leaf():
            return False

        if node_idx >= 0:
            # Check the bounds if the target requires the use of an index, remembering to use the virtual look-up table.
            idx_map = remap_child_indices_virt_to_phys(node.children)
            if node_idx < 0 or node_idx > (len(idx_map) - 1):
                return False
            # You cannot use the list access feature to access non-lists
            if len(node.children) and not node.children[idx_map[node_idx]].list_member_flag:
                return False

        return True

    def _patch_add_find_target(self, path_stack: StrStack) -> tuple[Optional[Node], int, int, str, bool]:
        """
        Finds the target node of an `add()` operation, along with some supporting information.

        This function does not modify the parse tree.

        :param path_stack: Path that describes a location in the tree, as a list, treated like a stack.
        :returns: A tuple containing: - The target node, if found (or the parent node if the target is a list member) -
            The index of a node if the target is a list member - An additional path that needs to be created, if
            applicable - A flag indicating if the new data will be appended to a list
        """
        if len(path_stack) == 0:
            return None, INVALID_IDX, INVALID_IDX, "", False

        # Special case that only applies to `add`. The `-` character indicates the new element can be added to the end
        # of the list.
        append_to_list = False
        if path_stack[0] == "-":
            path_stack.pop(0)
            append_to_list = True

        path_stack_copy = path_stack.copy()
        node, virt_idx, phys_idx = traverse_with_index(self._root, path_stack)
        # Attempt to run a second time, if no node is found. As per the RFC, the containing object/list must exist. That
        # allows us to create only 1 level in the path.
        path_to_create = ""
        # NOTE: Appending to a non-existent list is effectively adding a second level and disallowed by the RFC.
        if node is None and not append_to_list:
            path_to_create = path_stack_copy.pop(0)
            node, virt_idx, phys_idx = traverse_with_index(self._root, path_stack_copy)

        return node, virt_idx, phys_idx, path_to_create, append_to_list

    def _patch_add(self, path_stack: StrStack, value: JsonType) -> bool:
        """
        Performs a JSON patch `add` operation.

        :param path_stack: Path that describes a location in the tree, as a list, treated like a stack.
        :param value: Value to add.
        :returns: True if the operation was successful. False otherwise.
        """
        # NOTE from the RFC:
        #   Because this operation is designed to add to existing objects and arrays, its target location will often
        #   not exist...However, the object itself or an array containing it does need to exist
        # In other words, the patch op will, at most, create 1 new path level. In addition, that also implies that
        # trying to append to an existing list only applies if the append operator is at the end of the list.
        node, virt_idx, phys_idx, path_to_create, append_to_list = self._patch_add_find_target(path_stack)

        if not RecipeParser._is_valid_patch_node(node, virt_idx):
            return False

        # If we couldn't find 1 level in the path, ensure that we re-insert that as the "root" of the sub-tree we are
        # about to create.
        if path_to_create:
            value = {path_to_create: value}

        new_children: list[Node] = RecipeReader._generate_subtree(value)
        # Mark children as list members if they are list members
        if append_to_list or phys_idx > INVALID_IDX:
            # Adding an object to a list requires the children to be wrapped in a collection node
            if not isinstance(value, PRIMITIVES_TUPLE):
                new_children = [Node(list_member_flag=True, children=new_children)]
            else:
                for child in new_children:
                    child.list_member_flag = True

        # Insert members if an index is specified. Otherwise, extend the list of child nodes from the existing list.
        if phys_idx > INVALID_IDX:
            node.children[phys_idx:phys_idx] = new_children
        # Extend the list of children if we're appending or adding a new key.
        elif append_to_list or path_to_create:
            node.children.extend(new_children)
        # NOTE from the RFC: "If the member already exists, it is replaced by the specified value."
        else:
            node.children = new_children

        return True

    def _patch_remove(self, path_stack: StrStack) -> bool:
        """
        Performs a JSON patch `remove` operation.

        :param path_stack: Path that describes a location in the tree, as a list, treated like a stack.
        :returns: True if the operation was successful. False otherwise.
        """
        if len(path_stack) == 0:
            return False

        # Removal in all scenarios requires targeting the parent node.
        node_idx = -1 if not path_stack[0].isdigit() else int(path_stack[0])
        # `traverse()` is destructive to the stack, so make a copy for the second traversal call.
        path_stack_copy = path_stack.copy()
        node_to_rm = traverse(self._root, path_stack)
        if not RecipeParser._is_valid_patch_node(node_to_rm, -1):
            return False

        path_stack_copy.pop(0)
        node = traverse(self._root, path_stack_copy)
        if not RecipeParser._is_valid_patch_node(node, node_idx):
            return False

        if node_idx > INVALID_IDX:
            # Pop the "physical" index, not the "virtual" one to ensure comments have been accounted for.
            node.children.pop(remap_child_indices_virt_to_phys(node.children)[node_idx])
            return True

        # In all other cases, the node to be removed must be found before eviction
        for i in range(len(node.children)):
            if node.children[i] == node_to_rm:
                node.children.pop(i)
                return True
        return False

    def _patch_replace(self, path_stack: StrStack, value: JsonType) -> bool:
        """
        Performs a JSON patch `replace` operation.

        :param path_stack: Path that describes a location in the tree, as a list, treated like a stack.
        :param value: Value to update with.
        :returns: True if the operation was successful. False otherwise.
        """
        node, virt_idx, phys_idx = traverse_with_index(self._root, path_stack)
        if not RecipeParser._is_valid_patch_node(node, virt_idx):
            return False

        new_children: list[Node] = RecipeReader._generate_subtree(value)
        # Lists inject all children at the target position.
        if phys_idx > INVALID_IDX:
            # Adding an object to a list requires the children to be wrapped in a collection node
            if not isinstance(value, PRIMITIVES_TUPLE):
                new_children = [Node(list_member_flag=True, children=new_children)]
            else:
                # Ensure all children are marked as list members
                for child in new_children:
                    child.list_member_flag = True
            node.children[phys_idx:phys_idx] = new_children
            # Evict the old child, which is now behind the new children
            node.children.pop(phys_idx + len(new_children))
            return True

        # Leafs that represent values/paths of values can evict all children, and be replaced with new children, derived
        # from a new tree of values.
        node.children = new_children
        return True

    def _patch_move(self, path_stack: StrStack, value_from: str) -> bool:
        """
        Performs a JSON patch `add` operation.

        :param path_stack: Path that describes a location in the tree, as a list, treated like a stack.
        :param value_from: The "from" value in the JSON payload, i.e. the path the value originates from.
        :returns: True if the operation was successful. False otherwise.
        """
        # NOTE from the RFC:
        #   This operation is functionally identical to a "remove" operation on the "from" location, followed
        #   immediately by an "add" operation at the target location with the value that was just removed.
        # So to save on development and maintenance, that is how this op is written.
        original_value: JsonType
        try:
            original_value = self.get_value(value_from)
        except KeyError:
            return False

        # Validate that `add` will succeed before we `remove` anything
        node, virt_idx, _, _, _ = self._patch_add_find_target(path_stack.copy())
        if not RecipeParser._is_valid_patch_node(node, virt_idx):
            return False

        return self._patch_remove(str_to_stack_path(value_from)) and self._patch_add(path_stack, original_value)

    def _patch_copy(self, path_stack: StrStack, value_from: str) -> bool:
        """
        Performs a JSON patch `add` operation.

        :param path_stack: Path that describes a location in the tree, as a list, treated like a stack.
        :param value_from: The "from" value in the JSON payload, i.e. the path the value originates from.
        :returns: True if the operation was successful. False otherwise.
        """
        # NOTE from the RFC:
        #   This operation is functionally identical to an "add" operation at the target location using the value
        #   specified in the "from" member.
        # So to save on development and maintenance, that is how this op is written.
        original_value: JsonType
        try:
            original_value = self.get_value(value_from)
        except KeyError:
            return False

        return self._patch_add(path_stack, original_value)

    def _patch_test(self, path: str, value: JsonType) -> bool:
        """
        Performs a JSON patch `test` operation.

        :param path: Path as a string. Useful for invoking public class members.
        :param value: Value to evaluate against.
        :returns: True if the target value is equal to the provided value. False otherwise.
        """
        try:
            return self.get_value(path) == value
        except KeyError:
            # Path not found
            return False

    def _call_patch_op(self, op: str, path: str, patch: JsonPatchType) -> bool:
        """
        Switching function that calls the appropriate JSON patch operation.

        :param op: Patch operation, pre-sanitized.
        :param path: Path as a string.
        :param patch: The original JSON patch. This is passed to conditionally provide extra arguments, per op.
        :returns: True if the patch was successful. False otherwise.
        """
        path_stack: Final[StrStack] = str_to_stack_path(path)
        # NOTE: The `remove` op has no `value` or `from` field to pass in, so it is executed first.
        if op == "remove":
            return self._patch_remove(path_stack)

        # The supplemental field name is determined by the operation type.
        value_from: Final[str] = "from" if op in RecipeParser._patch_ops_requiring_from else "value"
        patch_data: Final[JsonType | str] = patch[value_from]

        if op == "add":
            return self._patch_add(path_stack, patch_data)
        if op == "replace":
            return self._patch_replace(path_stack, patch_data)
        if op == "move":
            return self._patch_move(path_stack, cast(str, patch_data))
        if op == "copy":
            return self._patch_copy(path_stack, cast(str, patch_data))
        if op == "test":
            return self._patch_test(path, patch_data)

        # This should be unreachable but is kept for completeness.
        return False

    def patch(self, patch: JsonPatchType) -> bool:
        """
        Given a JSON-patch object, perform a patch operation.

        Modifications from RFC 6902
          - We're using a Jinja-formatted YAML file, not JSON
          - To modify comments, specify the `path` AND `comment`

        :param patch: JSON-patch payload to operate with.
        :raises JsonPatchValidationException: If the JSON-patch payload does not conform to our schema/spec.
        :returns: If the calling code attempts to perform the `test` operation, this indicates the return value of the
            `test` request. In other words, if `value` matches the target variable, return True. False otherwise. For
            all other operations, this indicates if the operation was successful.
        """
        # Validate the patch schema
        try:
            schema_validate(patch, JSON_PATCH_SCHEMA)
        except Exception as e:
            raise JsonPatchValidationException(patch) from e

        path: Final[str] = cast(str, patch["path"])

        # All RFC ops are supported, so the JSON schema validation checks will prevent us from getting this far, if
        # there is an issue.
        op: Final[str] = cast(str, patch["op"])

        # A no-op move is silly, but we might as well make it efficient AND ensure a no-op move doesn't corrupt our
        # modification flag.
        if op == "move" and path == patch["from"]:
            return True

        # Both versions of the path are sent over so that the op can easily use both private and public functions
        # (without incurring even more conversions between path types).
        is_successful = self._call_patch_op(op, path, patch)

        # Update the selector table and modified flag, if the operation succeeded.
        if is_successful and op != "test":
            # TODO this is not the most efficient way to update the selector table, but for now, it works.
            self._rebuild_selectors()
            # TODO technically this doesn't handle a no-op.
            self._is_modified = True

        return is_successful

    def _render_patch_value(self, path: str, patch_with: JsonType | ReplacePatchFunc) -> JsonType:
        """
        Helper function for `RecipeParser::search_and_patch_replace()` that discerns between static and dynamic patches.

        :param path: Path to the value to patch.
        :param patch_with: `JsonType` value to replace the matching value with directly or a callback that provides the
            original value as a `JsonType` so the caller can manipulate what is being patched-in.
        :returns: Value to patch-in.
        """
        if not callable(patch_with):
            return patch_with
        # `RecipeReader::get_value()` should never throw UNLESS there is a bug in `RecipeParser::search()`. We
        # do not want one fault to cause the other patches to fail.
        return patch_with(self.get_value(path, sub_vars=False))

    def _get_comment_selector(self, path: str, preserve_comments_and_selectors: bool) -> Optional[str]:
        """
        Helper function for `RecipeParser::search_and_patch_replace()` that records the pre-patched comment-state of the
        target node in the tree. We go directly to the parse tree so that we don't have to make a distinction between
        comments and selectors or worry about the ordering. If this function returns a string, we must attempt to add
        the comment/selector post-patch.

        :param path: Path to the value to patch.
        :param preserve_comments_and_selectors: Flag indicating if this function should preserve any existing
            comments or selectors that apply to the path provided.
        :returns: A string if there is a comment/selector that needs to be preserved. Otherwise `None`.
        """
        if not preserve_comments_and_selectors:
            return None

        node = traverse(self._root, str_to_stack_path(path))
        # Minor optimization, don't perform an update traversal on a comment/selector that doesn't exist.
        if node is None or node.comment == "":
            return None
        return node.comment

    def search_and_patch_replace(
        self,
        regex: str | re.Pattern[str],
        patch_with: JsonType | ReplacePatchFunc,
        preserve_comments_and_selectors: bool = True,
    ) -> bool:
        """
        Given a regex string and a partial patch, replace values at every location that matches.
        This function effectively replaces the previous `RecipeParser::search_and_patch()`

        :param regex: Regular expression to match with. This only matches values on patch-able paths.
        :param patch_with: `JsonType` value to replace the matching value with directly or a callback that provides the
            original value as a `JsonType` so the caller can manipulate what is being patched-in.
        :param preserve_comments_and_selectors: (Optional) Flag indicating if this function should preserve any existing
            comments or selectors that apply to the path provided.
        :returns: Returns True if all patches were successful. Otherwise, False.
        """

        paths = self.search(regex, include_comment=False)
        summation: bool = True

        for path in paths:
            try:
                comment_selector = self._get_comment_selector(path, preserve_comments_and_selectors)
                summation = summation and self.patch(
                    {"op": "replace", "path": path, "value": self._render_patch_value(path, patch_with)}
                )
                # Skip comment/selector preservation logic if it is not possible/not required.
                if comment_selector is None:
                    continue

                # We must traverse again as the tree state has changed.
                node = traverse(self._root, str_to_stack_path(path))
                if node is None:
                    # TODO Future Log this when CRM parsers have proper logging.
                    summation = False
                    continue

                # The caller is unable to access the node and patch operations ignore comments/selectors.
                node.comment = comment_selector
                # When we add the comment back in, we MUST update the selector table.
                self._rebuild_selectors()
                self._is_modified = True
            except KeyError:
                # TODO Future Log this when CRM parsers have proper logging.
                summation = False
                continue

        return summation

    def diff(self) -> str:
        """
        Returns a git-like-styled diff of the current recipe state with original state of the recipe. Useful for
        debugging and providing users with some feedback.

        :returns: User-friendly displayable string that represents notifications made to the recipe.
        """
        if not self.is_modified():
            return ""
        # Utilize `difflib` to lower maintenance overhead.
        return "\n".join(
            difflib.unified_diff(
                self._init_content.splitlines(), self.render().splitlines(), fromfile="original", tofile="current"
            )
        )
