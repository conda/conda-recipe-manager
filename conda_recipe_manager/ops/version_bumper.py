"""
:Description: Provides library tooling to perform recipe version updates or recipe "bumps". Most of the work found
    here originates from the `crm bump-recipe` command line interface.
"""

import logging
import re
from enum import Flag, auto
from pathlib import Path
from typing import Final, NamedTuple, NoReturn, Optional, cast

from conda_recipe_manager.fetcher.artifact_fetcher import (
    DEFAULT_RETRY_INTERVAL,
    DEFAULT_RETRY_LIMIT,
    fetch_all_artifacts_with_retry,
)
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
    Set of variables that control how the `VersionBumper` class operates.
    """

    # The amount of time (in seconds) between attempts at fetching a remote resource.
    fetch_retry_interval: float = DEFAULT_RETRY_INTERVAL
    # How many times to attempt to fetch a remote resource, if a failure occurs.
    fetch_retry_limit: int = DEFAULT_RETRY_LIMIT


class VersionBumperOption(Flag):
    """
    Set of flags that dictate how the `VersionBumper` class operates.
    """

    # The "null" flag, only to be used as a default value of "no flags set".
    NONE = 0
    # Automatically saves the current state of the recipe file in the event of a unrecoverable failure.
    COMMIT_ON_FAILURE = auto()
    # Instead of saving to disk, the current state of the recipe file is printed to `STDOUT`.
    DRY_RUN_MODE = auto()
    # When a recipe file is saved, this remove the trailing blank newline at the end of the recipe file. Some Conda
    # packaging communities prefer having an extra empty line at the end of the recipe file, some do not.
    OMIT_TRAILING_NEW_LINE = auto()


class VersionBumper:
    """
    Library class that simplifies the process of upgrading a recipe file to a new version. This class handles file I/O
    and will commit changes directly to a target recipe file. It also handles acquiring and managing remote source
    artifacts specified in the `/source` section of the target recipe file.

    This work was all originally found in the `crm bump-recipe` command and has been refactored into its own library
    module for easier consumption by other automated systems.
    """

    def _commit_on_failure(self) -> None:
        """
        Optionally commits changes if the `VersionBumperOption.COMMIT_ON_FAILURE` flag is enabled. Only call this
        function if a failure case has occurred, to ensure partial progress is saved for the calling program.
        """
        if VersionBumperOption.COMMIT_ON_FAILURE not in self._options:
            return
        self.commit_changes()

    def _throw_on_failed_patch(self, patch_blob: JsonPatchType) -> None:
        """
        Convenience function that exits the program when a patch operation fails. This standardizes how we handle patch
        failures across all patch operations performed in this program.

        :param patch_blob: Recipe patch to execute.
        :raises VersionBumperPatchError: If there was a failure attempting to edit the recipe file.

        """
        if self._recipe_parser.patch(patch_blob):
            log.debug("Executed patch: %s", patch_blob)
            return

        self._commit_on_failure()

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
        :raises VersionBumperPatchError: If there was a failure attempting to edit the recipe file.
        """
        patch_type_str: Final[str] = "dynamic" if callable(patch_with) else "static"
        if self._recipe_parser.search_and_patch_replace(regex, patch_with, preserve_comments_and_selectors=True):
            log.debug("Executed a %s patch using this regular expression: %s", patch_type_str, regex)
            return

        self._commit_on_failure()

        raise VersionBumperPatchError(
            f"Couldn't perform a {patch_type_str} patch using this regular expressions: {regex}"
        )

    @staticmethod
    def _pre_process_cleanup(recipe_content: str) -> str:
        """
        Performs some recipe clean-up tasks before parsing the recipe file. This should correct common issues and
        improve parsing compatibility.

        :param recipe_content: Recipe file content to fix.
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
        :raises VersionBumperInvalidState: TODO
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
            self._recipe_parser,
            retry_interval=self._bumper_args.fetch_retry_interval,
            retries=self._bumper_args.fetch_retry_limit,
        )

    def commit_changes(self) -> None:
        """
        Saves the current recipe state to the target recipe file OR prints the contents of the file to `STDOUT` when the
        `VersionBumperOption.DRY_RUN_MODE` option is enabled.
        """
        omit_trailing_newline: Final = VersionBumperOption.OMIT_TRAILING_NEW_LINE in self._options
        if VersionBumperOption.DRY_RUN_MODE in self._options:
            print(self._recipe_parser.render(omit_trailing_newline=omit_trailing_newline))
            return

        self._recipe_path.write_text(
            self._recipe_parser.render(omit_trailing_newline=omit_trailing_newline), encoding="utf-8"
        )

    def update_build_num(self, build_num: Optional[int]) -> None:
        """
        Attempts to update the build number in a recipe file.

        :param build_num: Build number to set. When set to `None`, this auto-increments the current build
            number. Otherwise, this value must be a >= 0.
        :raises VersionBumperInvalidState: If the build number field could not be set because the recipe file is in or
            would be put into an invalid state.
        :raises VersionBumperPatchError: If there was a failure attempting to edit the `/build/number` field.
        """

        def _throw_on_build_num_failure(msg: str) -> NoReturn:
            self._commit_on_failure()
            raise VersionBumperInvalidState(msg)

        # Guard against negative build numbers
        if build_num is not None and build_num < 0:
            _throw_on_build_num_failure("`/build/number` must be >= 0")

        # Try to get "build" key from the recipe, exit if not found
        try:
            self._recipe_parser.get_value("/build")
        except KeyError:
            _throw_on_build_num_failure("`/build` key could not be found in the recipe.")

        # From the previous check, we know that `/build` exists. If `/build/number` is missing, it'll be added by
        # a patch-add operation and set to a default value of 0. Otherwise, we attempt to increment the build number, if
        # requested.
        if build_num is None and self._recipe_parser.contains_value(_RecipePaths.BUILD_NUM):
            og_build_number: Final = self._recipe_parser.get_value(_RecipePaths.BUILD_NUM)

            if not isinstance(og_build_number, int):
                _throw_on_build_num_failure("Build number is not an integer.")

            self._throw_on_failed_patch(
                cast(JsonPatchType, {"op": "replace", "path": _RecipePaths.BUILD_NUM, "value": og_build_number + 1})
            )
            return

        # The target build number defaults to 0.
        self._throw_on_failed_patch(
            cast(
                JsonPatchType,
                {"op": "add", "path": _RecipePaths.BUILD_NUM, "value": 0 if build_num is None else build_num},
            )
        )

    def update_version(self, target_version: str) -> None:
        """
        Attempts to update the `/package/version` field and/or the commonly used `version` JINJA variable.

        :param target_version: Target version string to set the recipe file to. Must be non-empty and this must be
            different than the current version string.
        :raises VersionBumperInvalidState: If the target version could not be set because the recipe file is in or
            would be put into an invalid state.
        :raises VersionBumperPatchError: If there was a failure attempting to edit the target version.
        """
        # TODO Add V0 multi-output version support for some recipes (version field is duplicated in cctools-ld64 but not
        # in most multi-output recipes)

        # The version string can't be empty
        if target_version == "":
            self._commit_on_failure()
            raise VersionBumperInvalidState("The target software version must be a non-empty string.")

        # Upgrading to the same version is a no-op, so error-out.
        if target_version == self._recipe_parser.get_value(_RecipePaths.VERSION, default=None, sub_vars=True):
            self._commit_on_failure()
            raise VersionBumperInvalidState("Can't bump a recipe to the same software version.")

        # If the `version` variable is found, patch that. This is an artifact/pattern from Grayskull.
        old_variable: Final = self._recipe_parser.get_variable(_RecipeVars.VERSION, None)
        if old_variable is not None:
            self._recipe_parser.set_variable(_RecipeVars.VERSION, target_version)
            # Generate a warning if `version` is not being used in the `/package/version` field. NOTE: This is a linear
            # search on a small list.
            if _RecipePaths.VERSION not in self._recipe_parser.get_variable_references(_RecipeVars.VERSION):
                log.warning("`/package/version` does not use the defined JINJA variable `version`.")
            return

        op: Final[str] = "replace" if self._recipe_parser.contains_value(_RecipePaths.VERSION) else "add"
        self._throw_on_failed_patch({"op": op, "path": _RecipePaths.VERSION, "value": target_version})
