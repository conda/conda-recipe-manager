"""
:Description: The V0 Recipe Formatter attempts to improve parsing capabilities of V0 recipe files by formatting the file
    prior to parsing. The parser can be easily tripped up on bad indentation and some recipe files have been found to be
    incredibly malformed. Given the V0 format does not contain legal YAML, we cannot use a common YAML formatting tool,
    like `yamlfmt`. This tool is not perfect, but is meant to catch enough common formatting issues to increase CRM's
    parsing capabilities in the ecosystem.
"""

from __future__ import annotations

from typing import Final

from conda_recipe_manager.parser._types import Regex
from conda_recipe_manager.parser._utils import num_tab_spaces
from conda_recipe_manager.parser.types import TAB_SPACE_COUNT


class V0RecipeFormatter:
    """
    Class that attempts to format V0 recipe files in a way to improve parsing compatibility.
    """

    def __init__(self, content: str):
        """
        Constructs a `V0RecipeFormatter` instance.

        :param content: conda-build formatted recipe file, as a single text string.
        """
        self._lines = content.splitlines()

        # In order to be able to be invoked by the parser before parsing begins, we need to determine if the recipe file
        # Is V0 or not independently of the mechanism used by the parser.
        def _calc_is_v0_recipe() -> bool:
            # TODO improve
            return "schema_version:" not in content

        self._is_v0_recipe: Final[bool] = _calc_is_v0_recipe()

    def __str__(self) -> str:
        """
        Returns the text contained by this formatter instance.

        :returns: V0 recipe file contents as a single string.
        """
        # Adding new line to match the default behavior of render. We do not anticipate we need to omit the trailing
        return "\n".join(self._lines) + "\n"

    def is_v0_recipe(self) -> bool:
        """
        Indicates if this file is formatted in the V0 recipe format.

        :returns: True if the recipe content provided is in the V0 format. False otherwise.
        """
        return self._is_v0_recipe

    def fmt_text(self) -> None:
        """
        Executes a number of custom V0 formatting rules in an attempt to improve the chances a V0 recipe can be parsed.
        """
        idx = 0
        num_lines: Final[int] = len(self._lines)
        is_comment_block = False
        bad_lst_block_indent_tracker = -1
        while idx < num_lines:
            line = self._lines[idx]
            clean_line = line.lstrip()

            if not clean_line or not 0 < idx < num_lines - 1:
                idx += 1
                continue

            cur_cntr = num_tab_spaces(line)
            next_cntr = num_tab_spaces(self._lines[idx + 1])
            next_clean_line = self._lines[idx + 1].lstrip()

            # Attempt to correct mis-matched comment indentations by looking at the next line. This does not change
            # indentation when the following line is another comment (as to not mess with multi-line comment blocks).
            # This also does not change the indentation when the next line is blank.
            if clean_line.startswith("#"):
                if next_clean_line.startswith("#"):
                    is_comment_block = True
                if cur_cntr != next_cntr and next_clean_line and not is_comment_block:
                    self._lines[idx] = (" " * next_cntr) + clean_line
            # Reset comment block flag
            else:
                is_comment_block = False

            # This logic attempts to correct list sections that are poorly indented and can handle indenting comments
            # so long as the comment is followed by another list item. It is not a perfect algorithm, but it should be
            # "good enough" for the most common indentation issues without a huge risk to corrupting currently
            # compatible files.
            expected_lst_indent = cur_cntr + TAB_SPACE_COUNT
            if (
                Regex.V0_FMT_SECTION_HEADER.match(clean_line)
                and next_clean_line.startswith("-")
                and next_cntr != expected_lst_indent
            ):
                bad_lst_block_indent_tracker = expected_lst_indent
            elif bad_lst_block_indent_tracker > 0 and (
                clean_line.startswith("-") or (clean_line.startswith("#") and next_clean_line.startswith("-"))
            ):
                self._lines[idx] = (" " * bad_lst_block_indent_tracker) + clean_line
            # Reset block indentation tracker
            else:
                bad_lst_block_indent_tracker = -1

            idx += 1
