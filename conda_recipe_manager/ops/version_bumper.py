"""
:Description: Provides library tooling to perform recipe version updates or recipe "bumps". Most of the work found
    here originates from the `crm bump-recipe` command line interface.
"""

import logging
import re
from enum import Flag, auto
from pathlib import Path
from typing import Final, NamedTuple, NoReturn, Optional, cast

from conda_recipe_manager.fetcher.artifact_fetcher import DEFAULT_RETRY_INTERVAL, fetch_all_artifacts_with_retry
from conda_recipe_manager.ops.exceptions import VersionBumperInvalidState, VersionBumperPatchError
from conda_recipe_manager.parser.recipe_parser import ReplacePatchFunc
from conda_recipe_manager.parser.recipe_parser_deps import RecipeParserDeps
from conda_recipe_manager.types import JsonPatchType, JsonType

log: Final = logging.getLogger(__name__)

## Cosntants ##

# Default starting point for the `/build/number` field for the vast majority of recipe files.
DEFAULT_BUILD_NUM_START_POINT: Final = 0


## Types ##


class _RecipePaths:
    """
    Namespace to store common recipe path constants.
    """

    BUILD_NUM: Final[str] = "/build/number"
    SOURCE: Final[str] = "/source"
    SINGLE_URL: Final[str] = f"{SOURCE}/url"
    SINGLE_SHA_256: Final[str] = f"{SOURCE}/sha256"
    VERSION: Final[str] = "/package/version"


class _RecipeVars:
    """
    Namespace to store all the commonly used JINJA variable names the bumper should be aware of.
    """

    # Common variable name used to track the software version of a package.
    VERSION: Final[str] = "version"
    # Common variable names used for source artifact hashes.
    HASH_NAMES: Final[set[str]] = {
        "sha256",
        "hash",
        "hash_val",
        "hash_value",
        "checksum",
        "check_sum",
        "hashval",
        "hashvalue",
    }


class _Regex:
    """
    Namespace that contains all pre-compiled regular expressions used in this tool.
    """

    # Matches strings that reference `pypi.io` so that we can transition them to use the preferred `pypi.org` TLD.
    # Group 1 contains the protocol, group 2 is the deprecated domain, group 3 contains the rest of the URL to preserve.
    PYPI_DEPRECATED_DOMAINS: Final[re.Pattern[str]] = re.compile(
        r"(https?://)(pypi\.io|cheeseshop\.python\.org|pypi\.python\.org)(.*)"
    )
    # Attempts to match PyPi source archive URLs by the start of the URL.
    PYPI_URL: Final[re.Pattern[str]] = re.compile(
        r"https?://pypi\.(?:io|org)/packages/source/[a-zA-Z0-9]/|https?://files\.pythonhosted\.org/"
    )


class VersionBumperArguments(NamedTuple):
    """
    TODO document all of these
    """

    target_version: str
    target_build_number: int = DEFAULT_BUILD_NUM_START_POINT
    fetch_retry_interval: int = DEFAULT_RETRY_INTERVAL


class VersionBumperOption(Flag):
    """
    TODO document all of these
    """

    # The "null" flag, only to be used as a default value of "no flags set".
    NONE = 0
    SAVE_ON_FAILURE = auto()
    DRY_RUN_MODE = auto()
    OMIT_TRAILING_NEW_LINE = auto()
    INCREMENT_BUILD_NUM = auto()


class VersionBumper:
    """
    TODO mention I/O
    """

    def _save_or_print(self) -> None:
        """
        Helper function that saves the current recipe state to a file OR prints it to `STDOUT` when in `DRY_RUN_MODE`.
        """
        omit_trailing_newline: Final = VersionBumperOption.OMIT_TRAILING_NEW_LINE in self._options
        if VersionBumperOption.DRY_RUN_MODE in self._options:
            print(self._recipe_parser.render(omit_trailing_newline=omit_trailing_newline))
            return

        self._recipe_path.write_text(
            self._recipe_parser.render(omit_trailing_newline=omit_trailing_newline), encoding="utf-8"
        )

    def _throw_on_failed_patch(self, patch_blob: JsonPatchType) -> None:
        """
        Convenience function that exits the program when a patch operation fails. This standardizes how we handle patch
        failures across all patch operations performed in this program.

        :param patch_blob: Recipe patch to execute.
        :raises VersionBumperPatchError: TODO
        """
        if self._recipe_parser.patch(patch_blob):
            log.debug("Executed patch: %s", patch_blob)
            return

        if VersionBumperOption.SAVE_ON_FAILURE in self._options:
            self._save_or_print()

        raise VersionBumperPatchError(f"Couldn't perform the patch: {patch_blob}")

    def _throw_on_failed_search_and_patch_replace(
        self,
        regex: str | re.Pattern[str],
        patch_with: JsonType | ReplacePatchFunc,
    ) -> None:
        """
        Convenience function that exits the program when a search and patch-replace operation fails. This standardizes
        how we handle search and patch-replace failures across all patch operations performed in this program.

        :param regex: Regular expression to match with. This only matches values on patch-able paths.
        :param patch_with: `JsonType` value to replace the matching value with directly or a callback that provides the
            original value as a `JsonType` so the caller can manipulate what is being patched-in.
        :raises VersionBumperPatchError: TODO
        """
        patch_type_str: Final[str] = "dynamic" if callable(patch_with) else "static"
        if self._recipe_parser.search_and_patch_replace(regex, patch_with, preserve_comments_and_selectors=True):
            log.debug("Executed a %s patch using this regular expression: %s", patch_type_str, regex)
            return

        if VersionBumperOption.SAVE_ON_FAILURE in self._options:
            self._save_or_print()

        raise VersionBumperPatchError(
            f"Couldn't perform a {patch_type_str} patch using this regular expressions: {regex}"
        )

    @staticmethod
    def _pre_process_cleanup(recipe_content: str) -> str:
        """
        Performs some recipe clean-up tasks before parsing the recipe file. This should correct common issues and
        improve parsing compatibility.

        :param recipe_content: Recipe file content to fix.
        :param commit
        :returns: Post-processed recipe file text.
        """
        # TODO delete unused variables? Unsure if that may be too prescriptive.
        return RecipeParserDeps.pre_process_remove_hash_type(recipe_content)

    def _post_process_cleanup(self) -> None:
        """
        Performs global, less critical, recipe file clean-up tasks right after the initial parsing stage. We should take
        great care as to what goes in this step. The work done here should have some impact to the other stages of
        recipe editing but not enough to warrant being a separate stage.

        :param recipe_parser: Recipe file to update.
        """
        self._throw_on_failed_search_and_patch_replace(
            _Regex.PYPI_DEPRECATED_DOMAINS,
            lambda s: _Regex.PYPI_DEPRECATED_DOMAINS.sub(r"https://pypi.org\3", str(s)),
        )

    def __init__(
        self,
        recipe_path: Path | str,
        bumper_args: VersionBumperArguments,
        options: Optional[VersionBumperOption] = None,
    ) -> None:
        """
        TODO

        :param recipe_path: TODO
        :param bumper_args: TODO
        :param options: (Optional) TODO
        :raises IOError: TODO
        :raises ParsingException: TODO check, make note of multiple
        """
        self._recipe_path: Final = Path(recipe_path)
        self._bumper_args: Final = bumper_args
        self._options: Final = VersionBumperOption.NONE if options is None else options

        recipe_content: Final = self._recipe_path.read_text(encoding="utf-8")
        self._recipe_parser = RecipeParserDeps(
            VersionBumper._pre_process_cleanup(recipe_content), force_remove_jinja=True
        )
        self._post_process_cleanup()

        # TODO have a function to delay the resolution?
        self._fetcher_ctx = fetch_all_artifacts_with_retry(
            self._recipe_parser, retry_interval=self._bumper_args.fetch_retry_interval
        )

    def update_build_num(self) -> None:
        """
        Attempts to update the build number in a recipe file.

        :raises VersionBumperInvalidState: TODO
        :raises VersionBumperPatchError: TODO
        """

        def _exit_on_build_num_failure(msg: str) -> NoReturn:
            if VersionBumperOption.SAVE_ON_FAILURE in self._options:
                self._save_or_print()
            log.error(msg)
            raise VersionBumperInvalidState(msg)

        # Try to get "build" key from the recipe, exit if not found
        try:
            self._recipe_parser.get_value("/build")
        except KeyError:
            _exit_on_build_num_failure("`/build` key could not be found in the recipe.")

        # From the previous check, we know that `/build` exists. If `/build/number` is missing, it'll be added by
        # a patch-add operation and set to a default value of 0. Otherwise, we attempt to increment the build number, if
        # requested.
        if VersionBumperOption.INCREMENT_BUILD_NUM in self._options and self._recipe_parser.contains_value(
            _RecipePaths.BUILD_NUM
        ):
            build_number: Final = self._recipe_parser.get_value(_RecipePaths.BUILD_NUM)

            if not isinstance(build_number, int):
                _exit_on_build_num_failure("Build number is not an integer.")

            self._throw_on_failed_patch(
                cast(JsonPatchType, {"op": "replace", "path": _RecipePaths.BUILD_NUM, "value": build_number + 1})
            )
            return

        # The target build number defaults to 0.
        self._throw_on_failed_patch(
            cast(
                JsonPatchType,
                {"op": "add", "path": _RecipePaths.BUILD_NUM, "value": self._bumper_args.target_build_number},
            )
        )

    def update_version(self) -> None:
        """
        Attempts to update the `/package/version` field and/or the commonly used `version` JINJA variable.
        """
        # TODO Add V0 multi-output version support for some recipes (version field is duplicated in cctools-ld64 but not
        # in most multi-output recipes)

        # If the `version` variable is found, patch that. This is an artifact/pattern from Grayskull.
        old_variable: Final = self._recipe_parser.get_variable(_RecipeVars.VERSION, None)
        if old_variable is not None:
            self._recipe_parser.set_variable(_RecipeVars.VERSION, self._bumper_args.target_version)
            # Generate a warning if `version` is not being used in the `/package/version` field. NOTE: This is a linear
            # search on a small list.
            if _RecipePaths.VERSION not in self._recipe_parser.get_variable_references(_RecipeVars.VERSION):
                log.warning("`/package/version` does not use the defined JINJA variable `version`.")
            return

        op: Final[str] = "replace" if self._recipe_parser.contains_value(_RecipePaths.VERSION) else "add"
        self._throw_on_failed_patch({"op": op, "path": _RecipePaths.VERSION, "value": self._bumper_args.target_version})
