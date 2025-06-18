"""
:Description: Provides private types, type aliases, constants, and small classes used by the parser and related files.
"""

from __future__ import annotations

import re
from typing import Final

import yaml

#### Private Types (Not to be used external to the `parser` module) ####

# Type alias for a list of strings treated as a Pythonic stack
StrStack = list[str]
# Type alias for a `StrStack` that must be immutable. Useful for some recursive operations.
StrStackImmutable = tuple[str, ...]

#### Private Constants (Not to be used external to the `parser` module) ####

# String that represents a root node in our path.
ROOT_NODE_VALUE: Final[str] = "/"
# Marker used to temporarily work around some Jinja-template parsing issues
RECIPE_MANAGER_SUB_MARKER: Final[str] = "__RECIPE_MANAGER_SUBSTITUTION_MARKER__"


class CanonicalSortOrder:
    """
    Namespace that contains all canonical sort-ordering look-up tables.
    """

    # Ideal sort-order of the top-level YAML keys for human readability and traditionally how we organize our files.
    # This should work on both V0 (pre CEP-13) and V1 recipe formats.
    TOP_LEVEL_KEY_SORT_ORDER: Final[dict[str, int]] = {
        "schema_version": 0,
        "context": 10,
        "package": 20,
        "recipe": 30,  # Used in the v1 recipe format
        "source": 40,
        "files": 50,
        "build": 60,
        "requirements": 70,
        "outputs": 80,
        "test": 90,
        "tests": 100,  # Used in the v1 recipe format
        "about": 110,
        "extra": 120,
    }

    # Canonical sort order for the new "v1" recipe format's `build` block
    V1_SOURCE_SECTION_KEY_SORT_ORDER: Final[dict[str, int]] = {
        # URL source fields
        "url": 0,
        "sha256": 10,
        "md5": 20,
        # Local source fields (not including above)
        "path": 30,
        "use_gitignore": 40,
        # Git source fields (not including above)
        "git": 50,
        "branch": 60,
        "tag": 70,
        "rev": 80,
        "depth": 90,
        "lfs": 100,
        # Common fields
        "target_directory": 120,
        "file_name": 130,
        "patches": 140,
    }

    # Canonical sort order for the new "v1" recipe format's `build` block
    V1_BUILD_SECTION_KEY_SORT_ORDER: Final[dict[str, int]] = {
        "number": 0,
        "string": 10,
        "skip": 20,
        "noarch": 30,
        "script": 40,
        "merge_build_and_host_envs": 50,
        "always_include_files": 60,
        "always_copy_files": 70,
        "variant": 80,
        "python": 90,
        "prefix_detection": 100,
        "dynamic_linking": 110,
    }

    # Canonical sort order for the new "v1" recipe format's `tests` block
    V1_TEST_SECTION_KEY_SORT_ORDER: Final[dict[str, int]] = {
        "script": 0,
        "requirements": 10,
        "files": 20,
        "python": 30,
        "downstream": 40,
    }

    # Canonical sort order for the V1 Python test element
    V1_PYTHON_TEST_KEY_SORT_ORDER: Final[dict[str, int]] = {
        "imports": 0,
        "pip_check": 10,
    }


#### Private Classes (Not to be used external to the `parser` module) ####

# NOTE: The classes put in this file should be structures (NamedTuples) and very small support classes that don't make
# sense to dedicate a file for.


class ForceIndentDumper(yaml.Dumper):
    """
    Custom YAML dumper used to include optional indentation for human readability.
    Adapted from: https://stackoverflow.com/questions/25108581/python-yaml-dump-bad-indentation
    """

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:  # pylint: disable=unused-argument
        return super().increase_indent(flow, False)


class Regex:
    """
    Namespace used to organize all regular expressions used by the `parser` module.
    """

    # Jinja syntax that is too complicated to fully convert
    # TODO remove after supporting issue #368
    V0_UNSUPPORTED_JINJA: Final[list[re.Pattern[str]]] = [re.compile(r"\.join\(")]

    # Pattern to detect Jinja variable names and functions
    _JINJA_VAR_FUNCTION_PATTERN: Final[str] = r"[a-zA-Z0-9_\|\'\"\(\)\[\]\,\\\/ =\.\-~\+:]+"
    # Pattern to detect optional comments or trailing whitespace. NOTE: The comment is marked as an optional matching
    # group. Failure to mark this may cause `findall()` to return empty strings if no other group is present in the
    # regex.
    _JINJA_OPTIONAL_EOL_COMMENT: Final[str] = r"[ \t]*(?:#[^\n]*)?$"

    # Pattern that attempts to identify YAML strings that need to be quote-escaped in the parsing process. Including:
    #   - Strings that start with a quote marker, close the same quote marker, and then are trailed by characters.
    # Examples:
    #   'm2w64-' if win else ''
    #   "" foo ""
    #   "%R%" -e "library('RSQLite')"
    #   "foo" bar # baz
    YAML_TO_QUOTE_ESCAPE: Final[re.Pattern[str]] = re.compile(r"^('.*'|\".*\")(?![ \t]#.+).+")

    ## V0 Formatter regular expressions ##
    V0_FMT_SECTION_HEADER: Final[re.Pattern[str]] = re.compile(r"^[\w|-]+:$")

    ## Pre-process conversion tooling regular expressions ##
    # Finds `environ[]` used by a some recipe files. Requires a whitespace character to prevent matches with
    # `os.environ[]`, which is very rare.
    PRE_PROCESS_ENVIRON: Final[re.Pattern[str]] = re.compile(r"\s+environ\[(\"|')(.*)(\"|')\]")

    # Finds `environ.get` which is used in a closed source community of which the author of this comment
    # participates in. See Issue #271.
    PRE_PROCESS_ENVIRON_GET: Final[re.Pattern[str]] = re.compile(
        r"\s+environ \| get\((\"|')(.*)(\"|'), *(\"|')(.*)(\"|')\)"
    )

    # Finds commonly used variants of `{{ hash_type }}:` which is a substitution for the `sha256` field
    PRE_PROCESS_JINJA_HASH_TYPE_KEY: Final[re.Pattern[str]] = re.compile(
        r"'{0,1}\{\{ (hash_type|hash|hashtype) \}\}'{0,1}:"
    )
    # Finds set statements that use dot functions over piped functions (`foo.replace(...)` vs `foo | replace(...)`).
    # Group 1 and Group 2 match the left and right sides of the period mark.
    PRE_PROCESS_JINJA_DOT_FUNCTION_IN_ASSIGNMENT: Final[re.Pattern[str]] = re.compile(
        r"(\{%\s*set.*=.*)\.(.*\(.*\)\s*%\})"
    )
    PRE_PROCESS_JINJA_DOT_FUNCTION_IN_SUBSTITUTION: Final[re.Pattern[str]] = re.compile(
        r"(\{\{\s*[a-zA-Z0-9_]*.*)\.([a-zA-Z0-9_]*\(.*\)\s*\}\})"
    )
    # Strips empty parenthesis artifacts on functions like `| lower`
    PRE_PROCESS_JINJA_DOT_FUNCTION_STRIP_EMPTY_PARENTHESIS: Final[re.Pattern[str]] = re.compile(
        r"(\|\s*(lower|upper))(\(\))"
    )
    # Attempts to normalize multiline strings containing quoted escaped newlines.
    PRE_PROCESS_QUOTED_MULTILINE_STRINGS: Final[re.Pattern[str]] = re.compile(r"(\s*)(.*):\s*['\"](.*)\\n(.*)['\"]")
    # rattler-build@0.18.0 deprecates `min_pin` and `max_pin`
    PRE_PROCESS_MIN_PIN_REPLACEMENT: Final[re.Pattern[str]] = re.compile(r"min_pin=")
    PRE_PROCESS_MAX_PIN_REPLACEMENT: Final[re.Pattern[str]] = re.compile(r"max_pin=")

    ## Ambiguous Dependency Corrections ##
    # Regular expressions used to modify problematic dependencies in the upgrade path. Note this have to account for
    # the dependency name as `VersionSpec`.raw_value does not actually contain the original, unmodified version string.
    AMBIGUOUS_DEP_VERSION_GE_TYPO: Final[re.Pattern[str]] = re.compile(r"([\w+\-]+\s*)=>(\s*[\d|.]+)")
    AMBIGUOUS_DEP_VERSION_LE_TYPO: Final[re.Pattern[str]] = re.compile(r"([\w+\-]+\s*)=<(\s*[\d|.]+)")
    AMBIGUOUS_DEP_MULTI_OPERATOR: Final[re.Pattern[str]] = re.compile(
        r"([\w|\-]+\s*)(~|<|>|<=|>=|==|!=|~=)(\s*[\d|\.]+)(\.\*)"
    )

    ## Selector Replacements ##
    # Replaces Python version expressions with the newer V1 `match()` function
    SELECTOR_PYTHON_VERSION_REPLACEMENT: Final[re.Pattern[str]] = re.compile(
        r"py\s*(<|>|<=|>=|==|!=|~=)\s*(3|2)([0-9]+)"
    )
    SELECTOR_PYTHON_VERSION_EQ_REPLACEMENT: Final[re.Pattern[str]] = re.compile(r"py(3|2)([0-9]+)")
    SELECTOR_PYTHON_VERSION_NE_REPLACEMENT: Final[re.Pattern[str]] = re.compile(r"not py(3|2)([0-9]+)")
    SELECTOR_PYTHON_VERSION_PY2K_REPLACEMENT: Final[re.Pattern[str]] = re.compile(r"py2k")
    SELECTOR_PYTHON_VERSION_PY3K_REPLACEMENT: Final[re.Pattern[str]] = re.compile(r"py3k")

    ## Jinja regular expressions ##
    JINJA_V0_SUB: Final[re.Pattern[str]] = re.compile(r"{{\s*" + _JINJA_VAR_FUNCTION_PATTERN + r"\s*}}")
    JINJA_V0_LINE: Final[re.Pattern[str]] = re.compile(
        r"^[ \t]*({%.+%}|{#.+#})" + _JINJA_OPTIONAL_EOL_COMMENT, flags=re.MULTILINE
    )
    JINJA_V0_SET_LINE: Final[re.Pattern[str]] = re.compile(
        r"^[ \t]*{%[ \t]*set[ \t]*" + _JINJA_VAR_FUNCTION_PATTERN + r"[ \t]*=.+%}" + _JINJA_OPTIONAL_EOL_COMMENT,
        flags=re.MULTILINE,
    )
    # Useful for replacing the older `{{` JINJA substitution with the newer `${{` WITHOUT accidentally doubling-up the
    # newer syntax when multiple replacements are possible.
    JINJA_REPLACE_V0_STARTING_MARKER: Final[re.Pattern[str]] = re.compile(r"(?<!\$)\{\{")

    JINJA_V1_SUB: Final[re.Pattern[str]] = re.compile(r"\${{\s*" + _JINJA_VAR_FUNCTION_PATTERN + r"\s*}}")

    # All recognized JINJA functions are kept in a set for the convenience of trying to match against all of them.
    # Group 1 contains the function or variable name, Group 2 contains the arguments, if any.
    # NOTE: `| replace()` and `.replace()` are both valid in V0 and common. `.upper()` and `.lower()` are VERY uncommon,
    # but are trivial to support. In V1, `| <func>` is the only acceptable form.
    JINJA_FUNCTION_LOWER: Final[re.Pattern[str]] = re.compile(r"\|\s*(lower)|\.(lower)\(\)")
    JINJA_FUNCTION_UPPER: Final[re.Pattern[str]] = re.compile(r"\|\s*(upper)|\.(upper)\(\)")
    JINJA_FUNCTION_REPLACE: Final[re.Pattern[str]] = re.compile(
        r"""[\|\.]\s*(replace)\(['"]([^'"]*)['"]\s*,\s*['"]([^'"]*)['"]\)"""
    )
    JINJA_FUNCTION_SPLIT: Final[re.Pattern[str]] = re.compile(r"""[\|\.]\s*(split)\(['"]([^'"]*)['"]\)""")
    # NOTE: `join` doesn't follow the same pattern as the other JINJA regular expressions. The function name can be in
    # one of two group locations.
    JINJA_FUNCTION_JOIN: Final[re.Pattern[str]] = re.compile(
        r"""\|\s*(join)\(['"]([^'"]*)['"]\)|['"]([^'"]*)['"]\.(join)\((.*)\)"""
    )
    JINJA_FUNCTION_IDX_ACCESS: Final[re.Pattern[str]] = re.compile(r"(.+)\[(-?\d+)\]")
    JINJA_FUNCTION_ADD_CONCAT: Final[re.Pattern[str]] = re.compile(
        r"([\"\']?[\w\.!]+[\"\']?)[ \t]*\+[ \t]*([\"\']?[\w\.!]+[\"\']?)"
    )
    # `match()` is a JINJA function available in the V1 recipe format
    JINJA_FUNCTION_MATCH: Final[re.Pattern[str]] = re.compile(r"match\(.*,.*\)")
    JINJA_FUNCTIONS_SET: Final[set[re.Pattern[str]]] = {
        JINJA_FUNCTION_LOWER,
        JINJA_FUNCTION_UPPER,
        JINJA_FUNCTION_REPLACE,
        JINJA_FUNCTION_SPLIT,
        JINJA_FUNCTION_JOIN,
        JINJA_FUNCTION_IDX_ACCESS,
        JINJA_FUNCTION_ADD_CONCAT,
        JINJA_FUNCTION_MATCH,
    }

    # Matches a JINJA variable's value that contains a ternary operation. Example value: 'm2-' if win else ''
    # Full support for evaluating is tracked in #285, but it is unclear if support for this in V1 is needed.
    JINJA_VAR_VALUE_TERNARY: Final[re.Pattern[str]] = re.compile(r"^.*\s+if\s+(\w|-)+\s+else\s+.*")

    SELECTOR: Final[re.Pattern[str]] = re.compile(r"\[.*\]")
    # Detects the 6 common variants (3 |'s, 3 >'s). See this guide for more info:
    #   https://stackoverflow.com/questions/3790454/how-do-i-break-a-string-in-yaml-over-multiple-lines/21699210
    MULTILINE_VARIANT: Final[re.Pattern[str]] = re.compile(r"^[ \t]*.*:[ \t]+(\||>)(\+|\-)?([ \t]*|[ \t]+#.*)")
    # Group where the "variant" string is identified
    MULTILINE_VARIANT_CAPTURE_GROUP_CHAR: Final[int] = 1
    MULTILINE_VARIANT_CAPTURE_GROUP_SUFFIX: Final[int] = 2
    # Detects the special "-backslash multiline string.
    MULTILINE_BACKSLASH_QUOTE: Final[re.Pattern[str]] = re.compile(r"^[ \t]*(.*):[ \t]+(\".*\\)$")
    MULTILINE_BACKSLASH_QUOTE_CAPTURE_GROUP_KEY: Final[int] = 1
    MULTILINE_BACKSLASH_QUOTE_CAPTURE_GROUP_FIRST_VALUE: Final[int] = 2

    DETECT_TRAILING_COMMENT: Final[re.Pattern[str]] = re.compile(r"([ \t])+(#)")
