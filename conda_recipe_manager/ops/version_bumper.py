"""
:Description: Provides library tooling to perform recipe version updates or recipe "bumps". Most of the work found
    here originates from the `crm bump-recipe` command line interface.
"""

import concurrent.futures as cf
import logging
import re
from enum import Flag, auto
from pathlib import Path
from typing import Final, NoReturn, Optional, cast

from conda_recipe_manager.fetcher.artifact_fetcher import FetcherFuturesTable
from conda_recipe_manager.fetcher.exceptions import FetchError
from conda_recipe_manager.fetcher.http_artifact_fetcher import HttpArtifactFetcher
from conda_recipe_manager.ops.exceptions import VersionBumperInvalidState, VersionBumperPatchError
from conda_recipe_manager.parser.recipe_parser import RecipeParser, ReplacePatchFunc
from conda_recipe_manager.parser.recipe_parser_deps import RecipeParserDeps
from conda_recipe_manager.parser.recipe_reader_deps import RecipeReaderDeps
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
        Convenience function that throws when a patch operation fails. This standardizes how we handle patch failures
        across all patch operations performed in this program.

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
        Convenience function that throws when a search and patch-replace operation fails. This standardizes how we
        handle search and patch-replace failures across all patch operations performed in this program.

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

    def _throw_on_failed_fetch(self, src_path: str, e: Exception) -> NoReturn:
        """
        Convenience function that manages internal state and re-throws upon a failed fetch.

        :param src_path: Recipe path to the `/source` section item that failed to be acquired.
        :param e: Original exception to throw from.
        """
        self._commit_on_failure()
        raise FetchError(f"Failed to fetch the artifact found at `{src_path}` in the recipe file.") from e

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
        options: Optional[VersionBumperOption] = None,
    ) -> None:
        """
        Constructs a `VersionBumper` instance. This class aims to streamline the process of updating a recipe file to
        target a new software version.

        :param recipe_path: Path to the underlying recipe file to "version bump".
        :param options: (Optional) A series of flags that change how this class operates. See the `VersionBumperOption`
            docs for more details.
        :raises IOError: If there is an issue accessing the recipe file on disk.
        :raises ParsingException: If there is an issue parsing the recipe file provided.
        :raises VersionBumperPatchError: If there was an issue editing the recipe file in the pre- or post-processing
            recipe text phases. These phases attempt to improve recipe file compatibility with this class.
        """
        self._recipe_path: Final = Path(recipe_path)
        self._options: Final = VersionBumperOption.NONE if options is None else options
        # Track how many times we've actually written to disk.
        self._disk_write_cntr = 0

        recipe_content: Final = self._recipe_path.read_text(encoding="utf-8")
        self._recipe_parser = RecipeParserDeps(
            VersionBumper._pre_process_cleanup(recipe_content), force_remove_jinja=True
        )
        self._post_process_cleanup()

    def get_recipe_reader(self) -> RecipeReaderDeps:
        """
        Exposes the underlying recipe parser instance for read-only access to a recipe file. This can help bootstrap
        the factory functions found the `conda_recipe_manager.fetcher.artifact_fetcher` module

        NOTE: Read-only capabilities are enforced by type-checkers (like `mypy`) only.

        :returns: A read-only recipe parser instance.
        """
        return self._recipe_parser

    # TODO Future: Expose editing capabilities via a callback mechanism that can auto-save on a failure?

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
        self._disk_write_cntr += 1

    def update_build_num(self, build_num: Optional[int]) -> None:
        """
        Attempts to update the build number in a recipe file.

        :param build_num: Build number to set. When set to `None`, this auto-increments the current build
            number. Otherwise, this value must be a >= 0.
        :raises VersionBumperInvalidState: If the build number field could not be set because the recipe file is in or
            would be put into an invalid state.
        :raises VersionBumperPatchError: If there was a failure attempting to edit the `/build/number` field.
        :raises SentinelTypeEvaluationException: If a node value with a sentinel type is evaluated.
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
        :raises SentinelTypeEvaluationException: If a node value with a sentinel type is evaluated.
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
            # If the variable is used in the `/package/version` field, update the variable only.
            # NOTE: This is a linear search on a small list.
            if _RecipePaths.VERSION in self._recipe_parser.get_variable_references(_RecipeVars.VERSION):
                self._recipe_parser.set_variable(_RecipeVars.VERSION, target_version)
                return
            # If the version variable is unused, we want to be careful. We don't know what the intended meaning of the
            # variable is. We will log that the recipe doesn't follow the "standard" naming conventions, and will focus
            # on modifying the `/package/version` field directly.
            else:
                log.info("`/package/version` does not use the defined JINJA variable `version`.")

        op: Final = "replace" if self._recipe_parser.contains_value(_RecipePaths.VERSION) else "add"
        self._throw_on_failed_patch({"op": op, "path": _RecipePaths.VERSION, "value": target_version})

    ## Functions that require fetched source data ##

    def _throw_on_invalid_futures_tbl(self, futures_tbl: FetcherFuturesTable) -> None:
        """
        Convenience function that throws when the provided fetchers future table is invalid.

        :param futures_tbl: Futures table to validate.
        """
        if futures_tbl:
            return

        self._commit_on_failure()
        raise VersionBumperInvalidState(
            "The futures table is empty. The recipe file's `/source` section is likely missing or does not contain"
            " a supported source type."
        )

    def update_http_urls(self, futures_tbl: FetcherFuturesTable) -> None:
        """
        Updates any outdated URLs found in the recipe file. Should be used in conjunction with
        `from_recipe_fetch_corrected()`, which attempts to flag outdated URLs and find their replacement
        URLs.

        NOTE: Most of the URLs updated are tied to changes made by PyPI over the years, including a significant change
              to the package naming conventions made in 2024.
        NOTE: This function will block on network I/O.

        :param futures_tbl: Table of future fetchers, generated by one of the factory functions found in the
            `conda_recipe_manager.fetcher.artifact_fetcher` module.
        :raises FetchError: If there was a failure to acquire the remote source artifacts needed by this call.
        :raises VersionBumperInvalidState: If the futures table provided is invalid.
        :raises VersionBumperPatchError: If there was a failure to update the underlying recipe file.
        """
        self._throw_on_invalid_futures_tbl(futures_tbl)

        url_update_cntr = 0
        for future, src_path in futures_tbl.items():
            try:
                fetcher, updated_url = future.result()

                # Filter-out artifacts that don't need URL updates.
                if not isinstance(fetcher, HttpArtifactFetcher) or updated_url is None:
                    continue

                url_path = RecipeParser.append_to_path(src_path, "/url")
                self._throw_on_failed_patch(
                    {
                        # Guard against the "should be impossible" scenario that the `url` field is missing.
                        "op": "replace" if self._recipe_parser.contains_value(url_path) else "add",
                        "path": url_path,
                        "value": updated_url,
                    }
                )
                url_update_cntr += 1

            except (FetchError, cf.CancelledError) as e:
                self._throw_on_failed_fetch(src_path, e)

        log.info(
            "Updated %d URL(s) in %d source(s).",
            url_update_cntr,
            len(futures_tbl),
        )

    def _update_sha256_check_hash_var(self, futures_tbl: FetcherFuturesTable) -> bool:
        """
        Helper function that checks if the SHA-256 is stored in a variable. If it is, it performs the update.

        :param futures_tbl: Table of future fetchers, generated by one of the factory functions found in the
            `conda_recipe_manager.fetcher.artifact_fetcher` module.
        :returns: True if `_update_sha256()` should return early. False otherwise.
        """
        # Check to see if the SHA-256 hash might be set in a variable. In extremely rare cases, we log warnings to
        # indicate that the "correct" action is unclear and likely requires human intervention. Otherwise, if we see a
        # hash variable and it is used by a single source, we will edit the variable directly.
        hash_vars_set: Final[set[str]] = _RecipeVars.HASH_NAMES & set(self._recipe_parser.list_variables())
        if len(hash_vars_set) == 1 and len(futures_tbl) == 1:
            # Acquire the only entries available
            hash_var: Final[str] = next(iter(hash_vars_set))
            future, src_path = next(iter(futures_tbl.items()))

            try:
                fetcher, _ = future.result()
                # Ignore sources that don't apply to the scenario.
                if not isinstance(fetcher, HttpArtifactFetcher):
                    return False

                # Bail-out if the variable isn't actually used in the `sha256` key. NOTE: This is a linear search on a
                # small list.
                if _RecipePaths.SINGLE_SHA_256 not in self._recipe_parser.get_variable_references(hash_var):
                    log.warning(
                        (
                            "Commonly used hash variable detected: `%s` but is not referenced by `/source/sha256`."
                            " The hash value will be changed directly at `/source/sha256`."
                        ),
                        hash_var,
                    )
                    return False

                self._recipe_parser.set_variable(hash_var, fetcher.get_archive_sha256())
            except (FetchError, cf.CancelledError) as e:
                log.exception("Failed to update the SHA-256 variable.")
                self._throw_on_failed_fetch(src_path, e)
            return True

        elif len(hash_vars_set) > 1:
            log.warning(
                "Multiple commonly used hash variables detected. Hash values will be changed directly in `/source`"
                " section."
            )

        return False

    def update_sha256(self, futures_tbl: FetcherFuturesTable) -> None:
        """
        Attempts to update the SHA-256 hash(s) in the `/source` section of a recipe file, if applicable. Note that this
        is only required for build artifacts that are hosted as compressed software archives.

        NOTE: This function will block on network I/O.
        NOTE: For this to make any meaningful changes, the `version` field will need to be updated first.

        :param futures_tbl: Table of future fetchers, generated by one of the factory functions found in the
            `conda_recipe_manager.fetcher.artifact_fetcher` module.
        :raises FetchError: If there was a failure to acquire the remote source artifacts needed by this call.
        :raises VersionBumperInvalidState: If the futures table provided is invalid.
        :raises VersionBumperPatchError: If there was a failure to update the underlying recipe file.
        """
        self._throw_on_invalid_futures_tbl(futures_tbl)

        # Bail early in the event the SHA-256 hash is used in a variable in a way that we can easily address.
        if self._update_sha256_check_hash_var(futures_tbl):
            return

        # NOTE: Each source _might_ have a different SHA-256 hash. This is the case for the `cctools-ld64` feedstock.
        # That project has a different implementation per architecture. However, in other circumstances, mirrored
        # sources with different hashes might imply there is a security threat. We will log some statistics so the user
        # can best decide what to do.
        unique_hashes: set[str] = set()
        sha_cntr = 0

        for future, src_path in futures_tbl.items():
            try:
                fetcher, _ = future.result()

                # Filter-out artifacts that don't need a SHA-256 hash.
                if not isinstance(fetcher, HttpArtifactFetcher):
                    continue

                sha = fetcher.get_archive_sha256()
                sha_cntr += 1
                unique_hashes.add(sha)
                sha_path = RecipeParser.append_to_path(src_path, "/sha256")
                self._throw_on_failed_patch(
                    {
                        # Guard against the unlikely scenario that the `sha256` field is missing.
                        "op": "replace" if self._recipe_parser.contains_value(sha_path) else "add",
                        "path": sha_path,
                        "value": sha,
                    }
                )

            except (FetchError, cf.CancelledError) as e:
                self._throw_on_failed_fetch(src_path, e)

        log.info(
            "Found %d unique SHA-256 hash(es) out of a total of %d hash(es) in %d sources.",
            len(unique_hashes),
            sha_cntr,
            len(futures_tbl),
        )
