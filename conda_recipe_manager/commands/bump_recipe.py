"""
:Description: CLI for bumping build number in recipe files.
"""

from __future__ import annotations

import concurrent.futures as cf
import logging
import sys
import time
from pathlib import Path
from typing import Final, NamedTuple, NoReturn, Optional, cast

import click

from conda_recipe_manager.commands.utils.types import ExitCode
from conda_recipe_manager.fetcher.artifact_fetcher import from_recipe as af_from_recipe
from conda_recipe_manager.fetcher.base_artifact_fetcher import BaseArtifactFetcher
from conda_recipe_manager.fetcher.exceptions import FetchError
from conda_recipe_manager.fetcher.http_artifact_fetcher import HttpArtifactFetcher
from conda_recipe_manager.parser.recipe_parser import RecipeParser
from conda_recipe_manager.parser.recipe_reader import RecipeReader
from conda_recipe_manager.types import JsonPatchType

# Truncates the `__name__` to the crm command name.
log = logging.getLogger(__name__.rsplit(".", maxsplit=1)[-1])

## Constants ##


class _RecipePaths:
    """
    Namespace to store common recipe path constants.
    """

    BUILD_NUM: Final[str] = "/build/number"
    SOURCE: Final[str] = "/source"
    SINGLE_SHA_256: Final[str] = f"{SOURCE}/sha256"
    VERSION: Final[str] = "/package/version"


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


# Common variable names used for source artifact hashes.
_COMMON_HASH_VAR_NAMES: Final[set[str]] = {
    "sha256",
    "hash",
    "hash_val",
    "hash_value",
    "checksum",
    "check_sum",
    "hashval",
    "hashvalue",
}

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
        print(recipe_parser.render())
        return
    Path(cli_args.recipe_file_path).write_text(recipe_parser.render(), encoding="utf-8")


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


def _exit_on_failed_fetch(recipe_parser: RecipeParser, fetcher: BaseArtifactFetcher, cli_args: _CliArgs) -> NoReturn:
    """
    Exits the script upon a failed fetch.

    :param recipe_parser: Recipe file to update.
    :param fetcher: ArtifactFetcher instance used in the fetch attempt.
    :param cli_args: Immutable CLI arguments from the user.
    """
    if cli_args.save_on_failure:
        _save_or_print(recipe_parser, cli_args)
    log.error("Failed to fetch `%s` after %s retries.", fetcher, _RETRY_LIMIT)
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


def _exit_on_build_num_failure(msg: str, cli_args: _CliArgs, recipe_parser: RecipeParser) -> NoReturn:
    if cli_args.save_on_failure:
        _save_or_print(recipe_parser, cli_args)
    log.error(msg)
    sys.exit(ExitCode.ILLEGAL_OPERATION)


def _update_build_num_field_directly(recipe_parser: RecipeParser, cli_args: _CliArgs) -> None:
    """
    Update the `build/number` field
    """

    try:
        recipe_parser.get_value("/build")
    except KeyError:
        _exit_on_build_num_failure("`/build` key could not be found in the recipe.", cli_args, recipe_parser)

    # From the previous check, we know that `/build` exists. If `/build/number` is missing, it'll be added by
    # a patch-add operation and set to a default value of 0. Otherwise, we attempt to increment the build number, if
    # requested.
    if cli_args.increment_build_num and recipe_parser.contains_value(_RecipePaths.BUILD_NUM):
        build_number = recipe_parser.get_value(_RecipePaths.BUILD_NUM)

        if not isinstance(build_number, int):
            _exit_on_build_num_failure("Build number is not an integer.", cli_args, recipe_parser)

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


def _update_build_num(recipe_parser: RecipeParser, recipe_reader: RecipeReader, cli_args: _CliArgs) -> None:
    """
    Attempts to update the build number in a recipe file.

    :param recipe_parser: Recipe file to update.
    :param recipe_reader: Recipe reader object
    :param cli_args: Immutable CLI arguments from the user.
    """

    # List of possible names for the build number variable as seen in some recipes
    build_num_possible_variants = ["build_number", "buildnumber", "build"]

    build_num_variable = ""
    build_num_variable_value = ""

    # Check if any of the possible names for the build number variable are found in the recipe
    for bn in build_num_possible_variants:
        try:
            recipe_reader.get_variable(bn)
            build_num_variable = bn
            build_num_variable_value = recipe_reader.get_variable(bn)
            break  # break out of the loop once a match is found
        except KeyError:
            continue

    if build_num_variable_value:
        if isinstance(build_num_variable_value, str):
            try:
                build_num_variable_value = int(build_num_variable_value)
            except ValueError:
                _exit_on_build_num_failure("Build number is not an integer.", cli_args, recipe_parser)
        if not isinstance(build_num_variable_value, int):
            _exit_on_build_num_failure("Build number is not an integer.", cli_args, recipe_parser)
        if references := recipe_reader.get_variable_references(build_num_variable):
            if "/build/number" in references:
                if cli_args.increment_build_num:
                    # converting to string before patching because Jinja variables are usually set to str values
                    recipe_parser.set_variable(build_num_variable, str(build_num_variable_value + 1))
                else:
                    recipe_parser.set_variable(build_num_variable, str(cli_args.override_build_num))
            else:
                log.error(f"{build_num_variable} set but unused.")
                if recipe_parser.contains_value(_RecipePaths.BUILD_NUM):
                    _update_build_num_field_directly(recipe_parser, cli_args)
    else:
        _update_build_num_field_directly(recipe_parser, cli_args)


def _update_version(recipe_parser: RecipeParser, cli_args: _CliArgs) -> None:
    """
    Attempts to update the `/package/version` field and/or the commonly used `version` JINJA variable.

    :param recipe_parser: Recipe file to update.
    :param cli_args: Immutable CLI arguments from the user.
    """
    # TODO Add V0 multi-output version support for some recipes (version field is duplicated in cctools-ld64 but not in
    # most multi-output recipes)

    # If the `version` variable is found, patch that. This is an artifact/pattern from Grayskull.
    old_variable = recipe_parser.get_variable("version", None)
    if old_variable is not None:
        recipe_parser.set_variable("version", cli_args.target_version)
        # Generate a warning if `version` is not being used in the `/package/version` field. NOTE: This is a linear
        # search on a small list.
        if _RecipePaths.VERSION not in recipe_parser.get_variable_references("version"):
            log.warning("`/package/version` does not use the defined JINJA variable `version`.")
        return

    op: Final[str] = "replace" if recipe_parser.contains_value(_RecipePaths.VERSION) else "add"
    _exit_on_failed_patch(
        recipe_parser, {"op": op, "path": _RecipePaths.VERSION, "value": cli_args.target_version}, cli_args
    )


def _get_sha256(fetcher: HttpArtifactFetcher, cli_args: _CliArgs) -> str:
    """
    Wrapping function that attempts to retrieve an HTTP/HTTPS artifact with a retry mechanism.

    :param fetcher: Artifact fetching instance to use.
    :param cli_args: Immutable CLI arguments from the user.
    :raises FetchError: If an issue occurred while downloading or extracting the archive.
    :returns: The SHA-256 hash of the artifact, if it was able to be downloaded.
    """
    # NOTE: This is the most I/O-bound operation in `bump-recipe` by a country mile. At the time of writing,
    # running this operation in the background will not make any significant improvements to performance. Every other
    # operation is so fast in comparison, any gains would likely be lost with the additional overhead. This op is
    # also inherently reliant on having the version change performed ahead of time. In addition, parallelizing the
    # retries defeats the point of having a back-off timer.
    for retry_id in range(1, _RETRY_LIMIT + 1):
        try:
            log.info("Fetching artifact `%s`, attempt #%d", fetcher, retry_id)
            fetcher.fetch()
            return fetcher.get_archive_sha256()
        except FetchError:
            time.sleep(retry_id * cli_args.retry_interval)
    raise FetchError(f"Failed to fetch `{fetcher}` after {_RETRY_LIMIT} retries.")


def _update_sha256_check_hash_var(
    recipe_parser: RecipeParser, fetcher_tbl: dict[str, BaseArtifactFetcher], cli_args: _CliArgs
) -> bool:
    """
    Helper function that checks if the SHA-256 is stored in a variable. If it does, it performs the update.

    :param recipe_parser: Recipe file to update.
    :param fetcher_tbl: Table of artifact source locations to corresponding ArtifactFetcher instances.
    :param cli_args: Immutable CLI arguments from the user.
    :returns: True if `_update_sha256()` should return early. False otherwise.
    """
    # Check to see if the SHA-256 hash might be set in a variable. In extremely rare cases, we log warnings to indicate
    # that the "correct" action is unclear and likely requires human intervention. Otherwise, if we see a hash variable
    # and it is used by a single source, we will edit the variable directly.
    hash_vars_set: Final[set[str]] = _COMMON_HASH_VAR_NAMES & set(recipe_parser.list_variables())
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
                recipe_parser.set_variable(hash_var, _get_sha256(src_fetcher, cli_args))
            except FetchError:
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


def _update_sha256_fetch_one(src_path: str, fetcher: HttpArtifactFetcher, cli_args: _CliArgs) -> tuple[str, str]:
    """
    Helper function that retrieves a single HTTP source artifact, so that we can parallelize network requests.

    :param src_path: Recipe key path to the applicable artifact source.
    :param fetcher: Artifact fetching instance to use.
    :param cli_args: Immutable CLI arguments from the user.
    :raises FetchError: In the event that the retry mechanism failed to fetch a source artifact.
    :returns: A tuple containing the path to and the actual SHA-256 value to be updated.
    """
    sha = _get_sha256(fetcher, cli_args)
    return (RecipeParser.append_to_path(src_path, "/sha256"), sha)


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

    # NOTE: Each source _might_ have a different SHA-256 hash. This is the case for the `cctools-ld64` feedstock. That
    # project has a different implementation per architecture. However, in other circumstances, mirrored sources with
    # different hashes might imply there is a security threat. We will log some statistics so the user can best decide
    # what to do.
    unique_hashes: set[str] = set()

    # Filter-out artifacts that don't need a SHA-256 hash.
    http_fetcher_tbl: Final[dict[str, HttpArtifactFetcher]] = {
        k: v for k, v in fetcher_tbl.items() if isinstance(v, HttpArtifactFetcher)
    }
    # Parallelize on acquiring multiple source artifacts on the network. In testing, using a process pool took
    # significantly more time and resources. That aligns with how I/O bound this process is. We use the
    # `ThreadPoolExecutor` class over a `ThreadPool` so the script may exit gracefully if we failed to acquire an
    # artifact.
    sha_path_to_sha_tbl: dict[str, str] = {}
    with cf.ThreadPoolExecutor() as executor:
        artifact_futures_tbl = {
            executor.submit(_update_sha256_fetch_one, src_path, fetcher, cli_args): fetcher
            for src_path, fetcher in http_fetcher_tbl.items()
        }
        for future in cf.as_completed(artifact_futures_tbl):
            fetcher = artifact_futures_tbl[future]
            try:
                resolved_tuple = future.result()
                sha_path_to_sha_tbl[resolved_tuple[0]] = resolved_tuple[1]
            except FetchError:
                _exit_on_failed_fetch(recipe_parser, fetcher, cli_args)

    for sha_path, sha in sha_path_to_sha_tbl.items():
        unique_hashes.add(sha)
        # Guard against the unlikely scenario that the `sha256` field is missing.
        patch_op = "replace" if recipe_parser.contains_value(sha_path) else "add"
        _exit_on_failed_patch(recipe_parser, {"op": patch_op, "path": sha_path, "value": sha}, cli_args)

    log.info(
        "Found %d unique SHA-256 hash(es) out of a total of %d hash(es) in %d sources.",
        len(unique_hashes),
        len(sha_path_to_sha_tbl),
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
def bump_recipe(
    recipe_file_path: str,
    build_num: bool,
    override_build_num: Optional[int],
    dry_run: bool,
    target_version: Optional[str],
    retry_interval: float,
    save_on_failure: bool,
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

    try:
        recipe_reader = RecipeReader(recipe_content)
    except Exception:
        log.error("An error occurred while parsing the recipe file contents.")
        sys.exit(ExitCode.READ_EXCEPTION)

    # Attempt to update fields
    _update_build_num(recipe_parser, recipe_reader, cli_args)

    # NOTE: We check if `target_version` is specified to perform a "full bump" for type checking reasons. Also note that
    # the `build_num` flag is invalidated if we are bumping to a new version. The build number must be reset to 0 in
    # this case.
    if cli_args.target_version is not None:
        if cli_args.target_version == recipe_parser.get_value(_RecipePaths.VERSION, default=None, sub_vars=True):
            log.warning(
                "The provided target version is the same value found in the recipe file: %s", cli_args.target_version
            )

        # Version must be updated before hash to ensure the correct artifact is hashed.
        _update_version(recipe_parser, cli_args)
        _update_sha256(recipe_parser, cli_args)

    _save_or_print(recipe_parser, cli_args)
    sys.exit(ExitCode.SUCCESS)
