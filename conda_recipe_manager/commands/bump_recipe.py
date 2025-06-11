"""
:Description: CLI for bumping build number in recipe files.
"""

from __future__ import annotations

import concurrent.futures as cf
import logging
import re
import sys
import time
from pathlib import Path
from typing import Final, NamedTuple, NoReturn, Optional, cast

import click

from conda_recipe_manager.commands.utils.types import ExitCode
from conda_recipe_manager.fetcher.api import pypi
from conda_recipe_manager.fetcher.artifact_fetcher import from_recipe as af_from_recipe
from conda_recipe_manager.fetcher.base_artifact_fetcher import BaseArtifactFetcher
from conda_recipe_manager.fetcher.exceptions import FetchError
from conda_recipe_manager.fetcher.http_artifact_fetcher import HttpArtifactFetcher
from conda_recipe_manager.parser.enums import SchemaVersion
from conda_recipe_manager.parser.recipe_parser import RecipeParser, ReplacePatchFunc
from conda_recipe_manager.parser.recipe_reader import RecipeReader
from conda_recipe_manager.types import JsonPatchType, JsonType
from conda_recipe_manager.utils.typing import optional_str

# Truncates the `__name__` to the crm command name.
log = logging.getLogger(__name__.rsplit(".", maxsplit=1)[-1])

## Constants ##


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


class _CliArgs(NamedTuple):
    """
    Typed convenience structure that contains all flags and values set by the CLI. This structure is passed once to
    functions that need access to flags and prevents an annoying refactor every time we add a new option.

    NOTE: These members are all immutable by design. They are set once by the CLI and cannot be altered.
    """

    recipe_file_path: str
    # Slightly less confusing name for internal use. If we change the flag, we break users.
    increment_build_num: bool
    override_build_num: int
    dry_run: bool
    target_version: Optional[str]
    retry_interval: float
    save_on_failure: bool
    omit_trailing_newline: bool


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
        r"https?://pypi\.(?:io|org)/packages/source/[a-z]/|https?://files\.pythonhosted\.org/"
    )


# Maximum number of retries to attempt when trying to fetch an external artifact.
_RETRY_LIMIT: Final[int] = 5
# How much longer (in seconds) we should wait per retry.
_DEFAULT_RETRY_INTERVAL: Final[int] = 30


## Functions ##


def _validate_target_version(ctx: click.Context, param: str, value: str) -> str:  # pylint: disable=unused-argument
    """
    Provides additional input validation on the target package version.

    :param ctx: Click's context object
    :param param: Argument parameter name
    :param value: Target value to validate
    :raises click.BadParameter: In the event the input is not valid.
    :returns: The value of the argument, if valid.
    """
    # NOTE: `None` indicates the flag is not provided.
    if value == "":
        raise click.BadParameter("The target version cannot be an empty string.")
    return value


def _validate_retry_interval(ctx: click.Context, param: str, value: float) -> float:  # pylint: disable=unused-argument
    """
    Provides additional input validation on the retry interval

    :param ctx: Click's context object
    :param param: Argument parameter name
    :param value: Target value to validate
    :raises click.BadParameter: In the event the input is not valid.
    :returns: The value of the argument, if valid.
    """
    if value <= 0:
        raise click.BadParameter("The retry interval must be a positive, non-zero floating-point value.")
    return value


def _save_or_print(recipe_parser: RecipeParser, cli_args: _CliArgs) -> None:
    """
    Helper function that saves the current recipe state to a file or prints it to STDOUT.

    :param recipe_parser: Recipe file to print/write-out.
    :param cli_args: Immutable CLI arguments from the user.
    """

    if cli_args.dry_run:
        print(recipe_parser.render(omit_trailing_newline=cli_args.omit_trailing_newline))
        return
    Path(cli_args.recipe_file_path).write_text(
        recipe_parser.render(omit_trailing_newline=cli_args.omit_trailing_newline), encoding="utf-8"
    )


def _exit_on_failed_patch(recipe_parser: RecipeParser, patch_blob: JsonPatchType, cli_args: _CliArgs) -> None:
    """
    Convenience function that exits the program when a patch operation fails. This standardizes how we handle patch
    failures across all patch operations performed in this program.

    :param recipe_parser: Recipe file to update.
    :param patch_blob: Recipe patch to execute.
    :param cli_args: Immutable CLI arguments from the user.
    """
    if recipe_parser.patch(patch_blob):
        log.debug("Executed patch: %s", patch_blob)
        return

    if cli_args.save_on_failure:
        _save_or_print(recipe_parser, cli_args)

    log.error("Couldn't perform the patch: %s", patch_blob)
    sys.exit(ExitCode.PATCH_ERROR)


def _exit_on_failed_search_and_patch_replace(
    recipe_parser: RecipeParser,
    regex: str | re.Pattern[str],
    patch_with: JsonType | ReplacePatchFunc,
    cli_args: _CliArgs,
) -> None:
    """
    Convenience function that exits the program when a search and patch-replace operation fails. This standardizes how
    we handle search and patch-replace failures across all patch operations performed in this program.

    :param recipe_parser: Recipe file to update.
    :param regex: Regular expression to match with. This only matches values on patch-able paths.
    :param patch_with: `JsonType` value to replace the matching value with directly or a callback that provides the
        original value as a `JsonType` so the caller can manipulate what is being patched-in.
    :param cli_args: Immutable CLI arguments from the user.
    """
    patch_type_str: Final[str] = "dynamic" if callable(patch_with) else "static"
    if recipe_parser.search_and_patch_replace(regex, patch_with, preserve_comments_and_selectors=True):
        log.debug("Executed a %s patch using this regular expression: %s", patch_type_str, regex)
        return

    if cli_args.save_on_failure:
        _save_or_print(recipe_parser, cli_args)

    log.error("Couldn't perform a %s patch using this regular expressions: %s", patch_type_str, regex)
    sys.exit(ExitCode.PATCH_ERROR)


def _exit_on_failed_fetch(recipe_parser: RecipeParser, fetcher: BaseArtifactFetcher, cli_args: _CliArgs) -> NoReturn:
    """
    Exits the script upon a failed fetch.

    :param recipe_parser: Recipe file to update.
    :param fetcher: ArtifactFetcher instance used in the fetch attempt.
    :param cli_args: Immutable CLI arguments from the user.
    """
    if cli_args.save_on_failure:
        _save_or_print(recipe_parser, cli_args)
    log.error("Failed to fetch `%s` after attempted retries.", fetcher)
    sys.exit(ExitCode.HTTP_ERROR)


def _pre_process_cleanup(recipe_content: str) -> str:
    """
    Performs some recipe clean-up tasks before parsing the recipe file. This should correct common issues and improve
    parsing compatibility.

    :param recipe_content: Recipe file content to fix.
    :returns: Post-processed recipe file text.
    """
    # TODO delete unused variables? Unsure if that may be too prescriptive.
    return RecipeParser.pre_process_remove_hash_type(recipe_content)


def _post_process_cleanup(recipe_parser: RecipeParser, cli_args: _CliArgs) -> None:
    """
    Performs global, less critical, recipe file clean-up tasks right after the initial parsing stage. We should take
    great care as to what goes in this step. The work done here should have some impact to the other stages of recipe
    editing but not enough to warrant being a separate stage.

    :param recipe_parser: Recipe file to update.
    """
    _exit_on_failed_search_and_patch_replace(
        recipe_parser,
        _Regex.PYPI_DEPRECATED_DOMAINS,
        lambda s: _Regex.PYPI_DEPRECATED_DOMAINS.sub(r"https://pypi.org\3", str(s)),
        cli_args,
    )


def _update_build_num(recipe_parser: RecipeParser, cli_args: _CliArgs) -> None:
    """
    Attempts to update the build number in a recipe file.

    :param recipe_parser: Recipe file to update.
    :param cli_args: Immutable CLI arguments from the user.
    """

    def _exit_on_build_num_failure(msg: str) -> NoReturn:
        if cli_args.save_on_failure:
            _save_or_print(recipe_parser, cli_args)
        log.error(msg)
        sys.exit(ExitCode.ILLEGAL_OPERATION)

    # Try to get "build" key from the recipe, exit if not found
    try:
        recipe_parser.get_value("/build")
    except KeyError:
        _exit_on_build_num_failure("`/build` key could not be found in the recipe.")

    # From the previous check, we know that `/build` exists. If `/build/number` is missing, it'll be added by
    # a patch-add operation and set to a default value of 0. Otherwise, we attempt to increment the build number, if
    # requested.
    if cli_args.increment_build_num and recipe_parser.contains_value(_RecipePaths.BUILD_NUM):
        build_number = recipe_parser.get_value(_RecipePaths.BUILD_NUM)

        if not isinstance(build_number, int):
            _exit_on_build_num_failure("Build number is not an integer.")

        _exit_on_failed_patch(
            recipe_parser,
            cast(JsonPatchType, {"op": "replace", "path": _RecipePaths.BUILD_NUM, "value": build_number + 1}),
            cli_args,
        )
        return
    # `override_build_num`` defaults to 0
    _exit_on_failed_patch(
        recipe_parser,
        cast(JsonPatchType, {"op": "add", "path": _RecipePaths.BUILD_NUM, "value": cli_args.override_build_num}),
        cli_args,
    )


def _update_version(recipe_parser: RecipeParser, cli_args: _CliArgs) -> None:
    """
    Attempts to update the `/package/version` field and/or the commonly used `version` JINJA variable.

    :param recipe_parser: Recipe file to update.
    :param cli_args: Immutable CLI arguments from the user.
    """
    # TODO Add V0 multi-output version support for some recipes (version field is duplicated in cctools-ld64 but not in
    # most multi-output recipes)

    # If the `version` variable is found, patch that. This is an artifact/pattern from Grayskull.
    old_variable = recipe_parser.get_variable(_RecipeVars.VERSION, None)
    if old_variable is not None:
        recipe_parser.set_variable(_RecipeVars.VERSION, cli_args.target_version)
        # Generate a warning if `version` is not being used in the `/package/version` field. NOTE: This is a linear
        # search on a small list.
        if _RecipePaths.VERSION not in recipe_parser.get_variable_references(_RecipeVars.VERSION):
            log.warning("`/package/version` does not use the defined JINJA variable `version`.")
        return

    op: Final[str] = "replace" if recipe_parser.contains_value(_RecipePaths.VERSION) else "add"
    _exit_on_failed_patch(
        recipe_parser, {"op": op, "path": _RecipePaths.VERSION, "value": cli_args.target_version}, cli_args
    )


def _fetch_archive(fetcher: HttpArtifactFetcher, cli_args: _CliArgs, retries: int = _RETRY_LIMIT) -> None:
    """
    Fetches the target source archive (with retries) for future use.

    :param fetcher: Artifact fetching instance to use.
    :param cli_args: Immutable CLI arguments from the user.
    :param retries: (Optional) Number of retries to attempt. Defaults to `_RETRY_LIMIT` constant.
    :raises FetchError: If an issue occurred while downloading or extracting the archive.
    """
    # NOTE: This is the most I/O-bound operation in `bump-recipe` by a country mile. At the time of writing,
    # running this operation in the background will not make any significant improvements to performance. Every other
    # operation is so fast in comparison, any gains would likely be lost with the additional overhead. This op is
    # also inherently reliant on having the version change performed ahead of time. In addition, parallelizing the
    # retries defeats the point of having a back-off timer.

    for retry_id in range(1, retries + 1):
        try:
            log.info("Fetching artifact `%s`, attempt #%d", fetcher, retry_id)
            fetcher.fetch()
            return
        except FetchError:
            time.sleep(retry_id * cli_args.retry_interval)

    raise FetchError(f"Failed to fetch `{fetcher}` after {retries} retries.")


def _correct_pypi_url(recipe_reader: RecipeReader, url_path: str) -> tuple[str, str]:
    """
    Handles correcting PyPi URLs by querying the PyPi API. There are many edge cases here that complicate this process,
    like managing JINJA variables commonly found in our URL values.

    :param recipe_reader: Read-only parser (enforced by our static analyzer). Editing may not be thread-safe. It is up
        to the caller to manage that risk.
    :param url_path: Recipe-path to the URL string being used by the fetcher.
    :raises FetchError: If an issue occurred while downloading or extracting the archive.
    :returns: Corrected PyPi artifact URL for the fetcher and recipe file.
    """
    version_value: Final[Optional[str]] = optional_str(
        recipe_reader.get_value(_RecipePaths.VERSION, default=None, sub_vars=True)
    )
    if version_value is None:
        raise FetchError("Unable to determine recipe version for PyPi API request.")

    # TODO we eventually need to handle the case of mapping conda names to PyPi names.
    # TODO alternatively regex-out the PyPi name from the URL. However, in many cases, this might be wasted
    # compute.
    package_name: Final[Optional[str]] = recipe_reader.get_recipe_name()
    if package_name is None:
        raise FetchError("Unable to determine package name for PyPi API request.")

    # TODO add retry mechanism for PyPi API query?
    try:
        pypi_meta: Final[pypi.PackageMetadata] = pypi.fetch_package_version_metadata(package_name, version_value)
    except pypi.ApiException as e:
        raise FetchError("Failed to access the PyPi API to correct a URL.") from e

    if version_value not in pypi_meta.releases:
        raise FetchError(f"Failed to retrieve target version: {version_value}")

    # We replace the `filename` specifically for a number of reasons:
    #  1) This decreases the "friction" involved with drastically changing what already exists in the recipe file. Less
    #     changes, less disruption/confusion for our package builders (or so the theory goes).
    #  2) The PyPi API generally produces a "post-redirect" URL for package artifacts. Again, as to not change the file
    #     dramatically, we want to keep the commonly used `https://pypi.io` URL.
    filename: Final[str] = pypi_meta.releases[version_value].filename

    # If the commonly used `version` variable exists AND it is being used in the original URL, inject its usage into the
    # file name.
    version_var: Final[Optional[str]] = optional_str(recipe_reader.get_variable(_RecipeVars.VERSION, None))
    is_version_var_used: Final[bool] = url_path in recipe_reader.get_variable_references(_RecipeVars.VERSION)
    base_original_url: Final[str] = str(recipe_reader.get_value(url_path, default="", sub_vars=False)).rsplit(
        "/", maxsplit=1
    )[0]
    base_rendered_url: Final[str] = str(recipe_reader.get_value(url_path, default="", sub_vars=True)).rsplit(
        "/", maxsplit=1
    )[0]
    fetcher_url: Final[str] = f"{base_rendered_url}/{filename}"
    if version_var is not None and is_version_var_used:
        filename_with_var: Final[str] = filename.replace(
            version_value,
            (
                # NOTE: The double-escaping of the outer `{{` and `}}` braces.
                f"{{{{ {_RecipeVars.VERSION} }}}}"
                if recipe_reader.get_schema_version() == SchemaVersion.V0
                else f"${{{{ {_RecipeVars.VERSION} }}}}"
            ),
        )
        return (fetcher_url, f"{base_original_url}/{filename_with_var}")

    return (fetcher_url, f"{base_original_url}/{filename}")


def _get_sha256_and_corrected_url(
    recipe_reader: RecipeReader, url_path: str, fetcher: HttpArtifactFetcher, cli_args: _CliArgs
) -> tuple[str, Optional[str]]:
    """
    Wrapping function that attempts to retrieve an HTTP/HTTPS artifact with a retry mechanism.

    This also determines if a URL correction needs to be made.

    For example, many PyPi archives (as of approximately 2024) now use underscores in the archive file name even though
    the package name still uses hyphens.

    :param recipe_reader: Read-only parser (enforced by our static analyzer). Editing may not be thread-safe. It is up
        to the caller to manage that risk.
    :param url_path: Recipe-path to the URL string being used by the fetcher.
    :param fetcher: Artifact fetching instance to use.
    :param cli_args: Immutable CLI arguments from the user.
    :raises FetchError: If an issue occurred while downloading or extracting the archive.
    :returns: The SHA-256 hash of the artifact, if it was able to be downloaded. Optionally includes a corrected URL to
        be updated in the recipe file.
    """
    pypi_match = _Regex.PYPI_URL.match(fetcher.get_archive_url())
    if pypi_match is None:
        _fetch_archive(fetcher, cli_args)
        return (fetcher.get_archive_sha256(), None)

    # Attempt to handle PyPi URLs that might have changed.
    pypi_retries: Final[int] = _RETRY_LIMIT // 2
    try:
        _fetch_archive(fetcher, cli_args, retries=pypi_retries)
        return (fetcher.get_archive_sha256(), None)
    except FetchError:
        log.info("PyPI URL detected. Attempting to recover URL.")
        # The `corrected_fetcher_url` is the rendered-out URL, without variables.
        corrected_fetcher_url, corrected_recipe_url = _correct_pypi_url(recipe_reader, url_path)
        corrected_fetcher: Final[HttpArtifactFetcher] = HttpArtifactFetcher(str(fetcher), corrected_fetcher_url)

        _fetch_archive(corrected_fetcher, cli_args, retries=pypi_retries)
        log.warning("Archive found at %s. Will attempt to update recipe file.", corrected_fetcher_url)
        return (corrected_fetcher.get_archive_sha256(), corrected_recipe_url)


def _update_sha256_check_hash_var(
    recipe_parser: RecipeParser, fetcher_tbl: dict[str, BaseArtifactFetcher], cli_args: _CliArgs
) -> bool:
    """
    Helper function that checks if the SHA-256 is stored in a variable. If it is, it performs the update.

    :param recipe_parser: Recipe file to update.
    :param fetcher_tbl: Table of artifact source locations to corresponding ArtifactFetcher instances.
    :param cli_args: Immutable CLI arguments from the user.
    :returns: True if `_update_sha256()` should return early. False otherwise.
    """
    # Check to see if the SHA-256 hash might be set in a variable. In extremely rare cases, we log warnings to indicate
    # that the "correct" action is unclear and likely requires human intervention. Otherwise, if we see a hash variable
    # and it is used by a single source, we will edit the variable directly.
    hash_vars_set: Final[set[str]] = _RecipeVars.HASH_NAMES & set(recipe_parser.list_variables())
    if len(hash_vars_set) == 1 and len(fetcher_tbl) == 1:
        hash_var: Final[str] = next(iter(hash_vars_set))
        src_fetcher: Final[Optional[BaseArtifactFetcher]] = fetcher_tbl.get(_RecipePaths.SOURCE, None)
        # By far, this is the most commonly seen case when a hash variable name is used.
        if (
            src_fetcher
            and isinstance(src_fetcher, HttpArtifactFetcher)
            # NOTE: This is a linear search on a small list.
            and _RecipePaths.SINGLE_SHA_256 in recipe_parser.get_variable_references(hash_var)
        ):
            try:
                sha, url = _get_sha256_and_corrected_url(recipe_parser, _RecipePaths.SINGLE_URL, src_fetcher, cli_args)
                recipe_parser.set_variable(hash_var, sha)
                if url is not None:
                    _exit_on_failed_patch(
                        recipe_parser,
                        {
                            # Guard against the "should be impossible" scenario that the `url` field is missing.
                            "op": "replace" if recipe_parser.contains_value(_RecipePaths.SINGLE_URL) else "add",
                            "path": _RecipePaths.SINGLE_URL,
                            "value": url,
                        },
                        cli_args,
                    )
            except FetchError:
                log.exception("Failed to update the SHA-256 variable.")
                _exit_on_failed_fetch(recipe_parser, src_fetcher, cli_args)
            return True

        log.warning(
            (
                "Commonly used hash variable detected: `%s` but is not referenced by `/source/sha256`."
                " The hash value will be changed directly at `/source/sha256`."
            ),
            hash_var,
        )
    elif len(hash_vars_set) > 1:
        log.warning(
            "Multiple commonly used hash variables detected. Hash values will be changed directly in `/source` keys."
        )

    return False


def _update_sha256_fetch_one(
    recipe_reader: RecipeReader, src_path: str, fetcher: HttpArtifactFetcher, cli_args: _CliArgs
) -> tuple[str, str, Optional[tuple[str, str]]]:
    """
    Helper function that retrieves a single HTTP source artifact, so that we can parallelize network requests.

    :param recipe_reader: Read-only parser (enforced by our static analyzer). Editing may not be thread-safe. It is up
        to the caller to manage that risk.
    :param src_path: Recipe key path to the applicable artifact source.
    :param fetcher: Artifact fetching instance to use.
    :param cli_args: Immutable CLI arguments from the user.
    :raises FetchError: In the event that the retry mechanism failed to fetch a source artifact.
    :returns: A tuple containing the path to and the actual SHA-256 value to be updated. Optionally includes a second
        tuple containing the path to the artifact URL and a corrected URL.
    """
    url_path: Final[str] = RecipeParser.append_to_path(src_path, "/url")
    sha, url = _get_sha256_and_corrected_url(recipe_reader, url_path, fetcher, cli_args)
    url_tup: Final[Optional[tuple[str, str]]] = None if url is None else (url_path, url)
    return (RecipeParser.append_to_path(src_path, "/sha256"), sha, url_tup)


def _update_sha256(recipe_parser: RecipeParser, cli_args: _CliArgs) -> None:
    """
    Attempts to update the SHA-256 hash(s) in the `/source` section of a recipe file, if applicable. Note that this is
    only required for build artifacts that are hosted as compressed software archives. If this field must be updated,
    a lengthy network request may be required to calculate the new hash.

    NOTE: For this to make any meaningful changes, the `version` field will need to be updated first.

    :param recipe_parser: Recipe file to update.
    :param cli_args: Immutable CLI arguments from the user.
    """
    fetcher_tbl = af_from_recipe(recipe_parser, True)
    if not fetcher_tbl:
        log.warning("`/source` is missing or does not contain a supported source type.")
        return

    if _update_sha256_check_hash_var(recipe_parser, fetcher_tbl, cli_args):
        return

    # Filter-out artifacts that don't need a SHA-256 hash.
    http_fetcher_tbl: Final[dict[str, HttpArtifactFetcher]] = {
        k: v for k, v in fetcher_tbl.items() if isinstance(v, HttpArtifactFetcher)
    }

    # NOTE: Each source _might_ have a different SHA-256 hash. This is the case for the `cctools-ld64` feedstock. That
    # project has a different implementation per architecture. However, in other circumstances, mirrored sources with
    # different hashes might imply there is a security threat. We will log some statistics so the user can best decide
    # what to do.
    unique_hashes: set[str] = set()
    # Parallelize on acquiring multiple source artifacts on the network. In testing, using a process pool took
    # significantly more time and resources. That aligns with how I/O bound this process is. We use the
    # `ThreadPoolExecutor` class over a `ThreadPool` so the script may exit gracefully if we failed to acquire an
    # artifact.
    sha_cntr = 0
    # Delay writing to the recipe until all threads have joined. This prevents us from performing write operations while
    # other threads may be reading recipe data.
    patches_to_apply: list[JsonPatchType] = []

    with cf.ThreadPoolExecutor() as executor:
        artifact_futures_tbl = {
            executor.submit(
                # Use the static analyzer checks to enforce that only read-only operations are allowed in a threaded
                # context.
                _update_sha256_fetch_one,
                cast(RecipeReader, recipe_parser),
                src_path,
                fetcher,
                cli_args,
            ): fetcher
            for src_path, fetcher in http_fetcher_tbl.items()
        }
        for future in cf.as_completed(artifact_futures_tbl):
            fetcher = artifact_futures_tbl[future]
            try:
                sha_path, sha, url_tup = future.result()
                sha_cntr += 1
                unique_hashes.add(sha)
                patches_to_apply.append(
                    {
                        # Guard against the unlikely scenario that the `sha256` field is missing.
                        "op": "replace" if recipe_parser.contains_value(sha_path) else "add",
                        "path": sha_path,
                        "value": sha,
                    }
                )

                # Patch the URL if a new one has been provided.
                if url_tup is None:
                    continue
                url_path, url = url_tup
                patches_to_apply.append(
                    {
                        # Guard against the "should be impossible" scenario that the `url` field is missing.
                        "op": "replace" if recipe_parser.contains_value(url_path) else "add",
                        "path": url_path,
                        "value": url,
                    }
                )

            except FetchError:
                log.exception("Failed to update SHA-256 from an artifact at %s", fetcher.get_archive_url())
                _exit_on_failed_fetch(recipe_parser, fetcher, cli_args)

    for patch in patches_to_apply:
        _exit_on_failed_patch(recipe_parser, patch, cli_args)

    log.info(
        "Found %d unique SHA-256 hash(es) out of a total of %d hash(es) in %d sources.",
        len(unique_hashes),
        sha_cntr,
        len(fetcher_tbl),
    )


def _validate_interop_flags(build_num: bool, override_build_num: Optional[int], target_version: Optional[str]) -> None:
    """
    Performs additional validation on CLI flags that interact with each other/are invalid in certain combinations.
    This function does call `sys.exit()` in the event of an error.

    :param build_num: Flag indicating if the user wants `bump-recipe` to increment the `/build/number` field
        automatically.
    :param override_build_num: Indicates if the user wants `bump-recipe` to reset the `/build/number` field to a custom
        value.
    :param target_version: Version of software that `bump-recipe` is upgrading too.
    """
    if override_build_num is not None and target_version is None:
        log.error("The `--target-version` option must be provided when using the `--override-build-num` flag.")
        sys.exit(ExitCode.CLICK_USAGE)

    if not build_num and target_version is None:
        log.error("The `--target-version` option must be provided if `--build-num` is not provided.")
        sys.exit(ExitCode.CLICK_USAGE)

    if build_num and override_build_num is not None:
        log.error("The `--build-num` and `--override-build-num` flags cannot be used together.")
        sys.exit(ExitCode.CLICK_USAGE)

    # Incrementing the version number while simultaneously updating the recipe does not make sense. The value should be
    # reset from the starting point (usually 0) that the maintainer specifies.
    if build_num and target_version is not None:
        log.error("The `--build-num` and `--target-version` flags cannot be used together.")
        sys.exit(ExitCode.CLICK_USAGE)


# TODO Improve. In order for `click` to play nice with `pyfakefs`, we set `path_type=str` and delay converting to a
# `Path` instance. This is caused by how `click` uses decorators. See these links for more detail:
# - https://pytest-pyfakefs.readthedocs.io/en/latest/troubleshooting.html#pathlib-path-objects-created-outside-of-tests
# - https://github.com/pytest-dev/pyfakefs/discussions/605
@click.command(short_help="Bumps a recipe file to a new version.")
@click.argument("recipe_file_path", type=click.Path(exists=True, path_type=str))
@click.option(
    "-o",
    "--override-build-num",
    default=None,
    nargs=1,
    type=click.IntRange(0),
    help="Reset the build number to a custom number.",
)
@click.option(
    "-b",
    "--build-num",
    is_flag=True,
    help="Bump the build number by 1.",
)
@click.option(
    "-d",
    "--dry-run",
    is_flag=True,
    help="Performs a dry-run operation that prints the recipe to STDOUT and does not save to the recipe file.",
)
@click.option(
    "-t",
    "--target-version",
    default=None,
    type=str,
    callback=_validate_target_version,
    help="New project version to target. Required if `--build-num` is NOT specified.",
)
@click.option(
    "-i",
    "--retry-interval",
    default=_DEFAULT_RETRY_INTERVAL,
    type=float,
    callback=_validate_retry_interval,
    help=(
        "Retry interval (in seconds) for network requests. Scales with number of failed attempts."
        f" Defaults to {_DEFAULT_RETRY_INTERVAL} seconds"
    ),
)
@click.option(
    "-s",
    "--save-on-failure",
    is_flag=True,
    help=(
        "Saves the current state of the recipe file in the event of a failure."
        " In other words, the file may only contain some automated edits."
    ),
)
@click.option(
    "--omit-trailing-newline",
    is_flag=True,
    help=("Omits trailing newlines from the end of the recipe file."),
)
def bump_recipe(
    recipe_file_path: str,
    build_num: bool,
    override_build_num: Optional[int],
    dry_run: bool,
    target_version: Optional[str],
    retry_interval: float,
    save_on_failure: bool,
    omit_trailing_newline: bool,
) -> None:
    """
    Bumps a recipe to a new version.

    RECIPE_FILE_PATH: Path to the target recipe file
    """
    # Ensure the user does not use flags in an invalid manner.
    _validate_interop_flags(build_num, override_build_num, target_version)

    # Typed, immutable, convenience data structure that contains all CLI arguments for ease of passing new options
    # to existing functions.
    cli_args = _CliArgs(
        recipe_file_path=recipe_file_path,
        increment_build_num=build_num,
        # By this point, we have validated the input. We do not need to discern between if the `--override-build-num`
        # flag was provided or not. To render the optional, we default `None` to `0`.
        override_build_num=0 if override_build_num is None else override_build_num,
        dry_run=dry_run,
        target_version=target_version,
        retry_interval=retry_interval,
        save_on_failure=save_on_failure,
        omit_trailing_newline=omit_trailing_newline,
    )

    try:
        recipe_content = Path(cli_args.recipe_file_path).read_text(encoding="utf-8")
    except IOError:
        log.error("Couldn't read the given recipe file: %s", cli_args.recipe_file_path)
        sys.exit(ExitCode.IO_ERROR)

    # Attempt to remove problematic recipe patterns that cause issues for the parser.
    recipe_content = _pre_process_cleanup(recipe_content)

    try:
        recipe_parser = RecipeParser(recipe_content)
    except Exception:  # pylint: disable=broad-except
        log.error("An error occurred while parsing the recipe file contents.")
        sys.exit(ExitCode.PARSE_EXCEPTION)

    if cli_args.target_version is not None and cli_args.target_version == recipe_parser.get_value(
        _RecipePaths.VERSION, default=None, sub_vars=True
    ):
        log.error("The provided target version is the same value found in the recipe file: %s", cli_args.target_version)
        sys.exit(ExitCode.CLICK_USAGE)

    _post_process_cleanup(recipe_parser, cli_args)

    # Attempt to update fields
    _update_build_num(recipe_parser, cli_args)

    # NOTE: We check if `target_version` is specified to perform a "full bump" for type checking reasons. Also note that
    # the `build_num` flag is invalidated if we are bumping to a new version. The build number must be reset to 0 in
    # this case.
    if cli_args.target_version is not None:
        # Version must be updated before hash to ensure the correct artifact is hashed.
        _update_version(recipe_parser, cli_args)
        _update_sha256(recipe_parser, cli_args)

    _save_or_print(recipe_parser, cli_args)
    sys.exit(ExitCode.SUCCESS)
