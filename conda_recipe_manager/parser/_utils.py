"""
:Description: Provides private utility functions only used by the parser.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Final, cast

from conda_recipe_manager.parser._types import (
    RECIPE_MANAGER_SUB_MARKER,
    ROOT_NODE_VALUE,
    Regex,
    StrStack,
    StrStackImmutable,
)
from conda_recipe_manager.parser.types import TAB_AS_SPACES, MultilineVariant, NodeValue
from conda_recipe_manager.types import H, JsonType, SentinelType

# Commonly used special characters that we need to ensure get quoted when rendered as a YAML string.
# NOTE: `#`, `|`, `{`, `}`, `>`, and `<` are left out of this list as in our use case, they have specifics meaning that
#       are already handled in the parser.
_TO_QUOTE_SPECIAL_STARTING_CHARS: Final[set[str]] = {
    "[",
    "]",
    ",",
    "&",
    ":",
    "*",
    "?",
    "-",
    "=",
    "!",
    "%",
    "@",
    "\\",
}
# If a string contains this substring, then it MUST be quoted. This is reserved for characters used in the YAML grammar.
_TO_QUOTE_SPECIAL_CONTAINS_SUBSTR: Final[set[str]] = {
    # NOTE:
    #   - We don't match `:` directly as `:<non_whitespace_char>` is acceptable. Example: `https://pypi.org`.
    #   - From some very brief testing, there is not an equivalent risk with `- `
    ": ",
    ":\t",
}


def str_to_stack_path(path: str) -> StrStack:
    """
    Takes a JSON-patch path as a string and return a path as a stack of strings. String paths are used by callers,
    stacks are used internally.

    For example:
        "/foo/bar/baz" -> ["baz", "bar", "foo", "/"]

    :param path: Path to deconstruct into a stack
    :returns: Path, described as a stack of strings.
    """
    # TODO: validate the path starts with `/` (root)

    # `PurePath` could be used here, but isn't for performance gains.
    # TODO reduce 3 (O)n operations to 1 O(n) operation

    # Wipe the trailing `/`, if provided. It doesn't have meaning here; only the `root` path is tracked.
    if path[-1] == ROOT_NODE_VALUE:
        path = path[:-1]
    parts = path.split("/")
    # Replace empty strings with `/` for compatibility in other functions.
    for i in range(0, len(parts)):
        if parts[i] == "":
            parts[i] = "/"
    return parts[::-1]


def stack_path_to_str(path_stack: StrStack | StrStackImmutable) -> str:
    """
    Takes a stack that represents a path and converts it into a string. String paths are used by callers, stacks are
    used internally.

    :param path_stack: Stack to construct back into a string.
    :returns: Path, described as a string.
    """
    # Normalize type if a tuple is given.
    if isinstance(path_stack, tuple):
        path_stack = list(path_stack)
    path = ""
    while len(path_stack) > 0:
        value = path_stack.pop()
        # Special case to bootstrap root; the first element will automatically add the first slash.
        if value == ROOT_NODE_VALUE:
            continue
        path += f"/{value}"
    return path


def num_tab_spaces(s: str) -> int:
    """
    Counts the number of spaces at the start of the string. Used to indicate depth of a field in a YAML file (the YAML
    specification dictates only spaces can be used for indenting).

    :param s: Target string
    :returns: Number of preceding spaces in a string
    """
    cntr: int = 0
    for c in s:
        if c == " ":
            cntr += 1
        else:
            break
    return cntr


def substitute_markers(s: str, subs: list[str]) -> str:
    """
    Given a string, replace substitution markers with the original Jinja template from a list of options.

    :param s: String to replace substitution markers with
    :param subs: List of substitutions to make, in order of appearance
    :returns: New string, with substitutions removed
    """
    while s.find(RECIPE_MANAGER_SUB_MARKER) >= 0 and len(subs):
        s = s.replace(RECIPE_MANAGER_SUB_MARKER, subs[0], 1)
        subs.pop(0)
    return s


def _quote_special_str_startswith_check_all(s: str) -> bool:
    """
    Checks if a string contains a starting character that will require the string to be quoted.

    :param s: String to check
    :returns: True if the string will need to be quoted. Otherwise, False.
    """
    for char in _TO_QUOTE_SPECIAL_STARTING_CHARS:
        if s.startswith(char):
            return True
    return False


def _quote_special_str_contains_check_all(s: str) -> bool:
    """
    Checks if a string contains a substring that will require the string to be quoted.

    :param s: String to check
    :returns: True if the string will need to be quoted. Otherwise, False.
    """
    for substr in _TO_QUOTE_SPECIAL_CONTAINS_SUBSTR:
        if substr in s:
            return True
    return False


def quote_special_strings(s: str, multiline_variant: MultilineVariant = MultilineVariant.NONE) -> str:
    """
    Ensures string quote-escaping if quote marks are present at the start of the string and handles other problematic
    starting characters for YAML parsing. This is not to be confused with other V0 JINJA handling processes.

    In addition, there are a handful of special cases that need to be quoted in order to produce valid YAML. PyYaml
    and Ruamel (in safe mode) will drop quotes found in the YAML. This means that round-tripping the YAML can break in
    some cases. For example, `"**/lib"` -> `**/lib` and `*` is an illegal character to start a bare YAML string with.
    So if we parse that value again, the YAML parser will throw.

    :param s: String to modify
    :param multiline_variant: (Optional) If the value being processed is a multiline string, indicate which YAML
        descriptor is in use.
    :returns: YAML version of a value, as a string.
    """

    # Do not mess with quotes in multiline strings or strings containing JINJA substitutions or JINJA functions used
    # without substitution markers (like `match()`)
    if (
        multiline_variant != MultilineVariant.NONE
        # We check the entire string for JINJA statements to avoid quoting valid YAML strings like:
        # `- ${{ compiler('rust') }} >=1.65.0` and `foo > {{ '4' + "2" }}`.
        or cast(list[str], Regex.JINJA_V0_SUB.findall(s))
        or Regex.JINJA_FUNCTION_MATCH.search(s)
    ):
        return s

    # `*` is common enough that we query the set of special characters before checking every "startswith" option as a
    # small short-circuit optimization. See the definition of `Regex.YAML_TO_QUOTE_ESCAPE` for details on some YAML
    # quoting edge cases and issue #366 for other context.
    if (
        s in _TO_QUOTE_SPECIAL_STARTING_CHARS
        or Regex.YAML_TO_QUOTE_ESCAPE.match(s)
        or _quote_special_str_contains_check_all(s)
        or _quote_special_str_startswith_check_all(s)
    ):
        # Prefer simpler usage of surrounding with "/' quotes if possible. Use JSON encoding as a fallback.
        if '"' not in s:
            return f'"{s}"'
        if "'" not in s:
            return f"'{s}'"
        # The PyYaml equivalent function injects newlines, hence why we abuse the JSON library to write our YAML
        return json.dumps(s)
    return s


def stringify_yaml(
    val: NodeValue | SentinelType, multiline_variant: MultilineVariant = MultilineVariant.NONE
) -> NodeValue:
    """
    Special function for handling edge cases when converting values back to YAML.

    :param val: Value to check
    :param multiline_variant: (Optional) If the value being processed is a multiline string, indicate which YAML
        descriptor is in use.
    :returns: YAML version of a value, as a string.
    """
    # Handled for type-completeness of `Node.value`. A `Node` with a sentinel as its value indicates a special Node
    # type that is not directly render-able.
    if isinstance(val, SentinelType):
        return ""
    # None -> null
    if val is None:
        return "null"
    # True -> true
    if isinstance(val, bool):
        if val:
            return "true"
        return "false"
    # Handle special string quote cases
    if isinstance(val, str):
        return quote_special_strings(val, multiline_variant)
    return val


def normalize_multiline_strings(val: NodeValue, variant: MultilineVariant) -> NodeValue:
    """
    Utility function that takes in a Node's value and "normalizes" multiline strings so that they can be accurately
    interpreted by PyYaml. We use PyYaml to handle the various ways in which a multiline string can be interpreted.

    :param val: Value to normalize
    :param variant: Multiline variant rules to follow
    :returns: If the value is a multiline string, this returns the "normalized" string to be re-evaluated by PyYaml.
        Otherwise, returns the original value.
    """
    if variant == MultilineVariant.NONE:
        return val

    # Prepend the multiline marker to the string to have PyYaml interpret how the whitespace should be handled. JINJA
    # substitutions in multi-line strings do not break the PyYaml parser.
    multiline_str = f"\n{TAB_AS_SPACES}".join(cast(list[str], val))
    if variant == MultilineVariant.BACKSLASH_QUOTE:
        return multiline_str
    return f"{variant}\n{TAB_AS_SPACES}{multiline_str}"


def dedupe_and_preserve_order(l: list[H]) -> list[H]:
    """
    Takes a list of strings
    See this StackOverflow post:
      - https://stackoverflow.com/questions/480214/how-do-i-remove-duplicates-from-a-list-while-preserving-order

    """
    return list(cast(dict[H, None], dict.fromkeys(l)))


def set_key_conditionally(dictionary: dict[str, JsonType], key: str, value: JsonType) -> None:
    """
    Convenience function that conditionally includes a key-value pair in a dictionary if the value is truthy.
    Great for cheating McCabe ratings in complex JSON/YAML operations!

    :param dictionary: Dictionary to conditionally add a value to
    :param key: Key to use
    :param value: Value to conditionally add to the dictionary
    """
    if value:
        dictionary[key] = value


def search_any_regex(re_set: Iterable[re.Pattern[str]], s: str) -> bool:
    """
    Convenience function that checks a string against many regular expressions

    :param re_set: Set of regular expressions to check
    :param s: Target string
    :returns: True if any regex in the set matches. False otherwise.
    """
    for r in re_set:
        if r.search(s):
            return True

    return False
