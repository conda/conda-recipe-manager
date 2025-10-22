"""
:Description: CLI for bumping build number in recipe files.
"""

from __future__ import annotations

import logging
import sys
from typing import Final, Optional

import click

from conda_recipe_manager.commands.utils.types import CONTEXT_SETTINGS, ExitCode
from conda_recipe_manager.fetcher.artifact_fetcher import DEFAULT_RETRY_INTERVAL, from_recipe_fetch_corrected
from conda_recipe_manager.fetcher.exceptions import FetchError
from conda_recipe_manager.ops.exceptions import VersionBumperInvalidState, VersionBumperPatchError
from conda_recipe_manager.ops.version_bumper import VersionBumper, VersionBumperOption
from conda_recipe_manager.parser.exceptions import ParsingException

# Truncates the `__name__` to the crm command name.
log: Final = logging.getLogger(__name__)


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


def _full_version_bump(version_bumper: VersionBumper, target_version: str, retry_interval: float) -> None:
    """
    Perform the steps necessary to complete a full version bump (as opposed to a build-number-only bump).

    :param version_bumper: Version bumper instance to perform the desired bump.
    :param target_version: The version being bumped to.
    :param retry_interval: Base quantity of time (in seconds) to wait between fetch attempts.
    """
    # Version must be updated before hash to ensure the correct artifact is hashed.
    try:
        version_bumper.update_version(target_version)
    except VersionBumperInvalidState:
        log.exception(
            "The provided target version is the same value found in the recipe file or empty: %s",
            target_version,
        )
        sys.exit(ExitCode.CLICK_USAGE)
    except VersionBumperPatchError:
        log.exception("Failed to edit the target version.")
        sys.exit(ExitCode.PATCH_ERROR)

    # Although we would like to kick this off sooner (to get more overlapping execution), we need the version to be
    # updated _before_ we attempt to fetch artifacts. Otherwise, we may attempt to fetch the previous verion's artifacts
    # from the recipe.
    with from_recipe_fetch_corrected(
        version_bumper.get_recipe_reader(), ignore_unsupported=True, retry_interval=retry_interval
    ) as fetcher_tbl:
        # Update recipe file components that require source artifacts. NOTE: These calls block on I/O.
        try:
            version_bumper.update_http_urls(fetcher_tbl)
            version_bumper.update_sha256(fetcher_tbl)
        except FetchError:
            log.exception("Failed to fetch the source artifacts found in the recipe file.")
            sys.exit(ExitCode.HTTP_ERROR)
        except VersionBumperPatchError:
            log.exception("Failed to update the recipe file components that require source artifacts.")
            sys.exit(ExitCode.PATCH_ERROR)


# TODO Improve. In order for `click` to play nice with `pyfakefs`, we set `path_type=str` and delay converting to a
# `Path` instance. This is caused by how `click` uses decorators. See these links for more detail:
# - https://pytest-pyfakefs.readthedocs.io/en/latest/troubleshooting.html#pathlib-path-objects-created-outside-of-tests
# - https://github.com/pytest-dev/pyfakefs/discussions/605
@click.command(short_help="Bumps a recipe file to a new version.", context_settings=CONTEXT_SETTINGS)
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
    default=DEFAULT_RETRY_INTERVAL,
    type=float,
    callback=_validate_retry_interval,
    help=(
        "Retry interval (in seconds) for network requests. Scales with number of failed attempts."
        f" Defaults to {DEFAULT_RETRY_INTERVAL} seconds"
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

    # By this point, we have validated the input. We do not need to discern between if the `--override-build-num` flag
    # was provided or not. To render the optional, we default `None` to `0`.
    build_num_int: Final = 0 if override_build_num is None else override_build_num

    # Accumulate flags into a bitwise set of options.
    options = VersionBumperOption.NONE
    options |= VersionBumperOption.DRY_RUN_MODE if dry_run else VersionBumperOption.NONE
    options |= VersionBumperOption.COMMIT_ON_FAILURE if save_on_failure else VersionBumperOption.NONE
    options |= VersionBumperOption.OMIT_TRAILING_NEW_LINE if omit_trailing_newline else VersionBumperOption.NONE

    try:
        version_bumper: Final = VersionBumper(
            recipe_file_path,
            options=options,
        )
    except IOError:
        log.exception("Couldn't read the given recipe file: %s", recipe_file_path)
        sys.exit(ExitCode.IO_ERROR)
    except ParsingException:
        log.exception("An error occurred while parsing the recipe file contents.")
        sys.exit(ExitCode.PARSE_EXCEPTION)

    # Attempt to update fields
    try:
        version_bumper.update_build_num(None if build_num else build_num_int)
    except VersionBumperInvalidState:
        log.exception("Failed to bump `/build/number` because the recipe was in or going to be in an invalid state.")
        sys.exit(ExitCode.ILLEGAL_OPERATION)
    except VersionBumperPatchError:
        log.exception("Failed to edit `/build/number`.")
        sys.exit(ExitCode.PATCH_ERROR)

    # NOTE: We check if `target_version` is specified to perform a "full bump" for type checking reasons. Also note that
    # the `build_num` flag is invalidated if we are bumping to a new version. The build number must be reset to 0 in
    # this case.
    if target_version is not None:
        _full_version_bump(version_bumper, target_version, retry_interval)

    version_bumper.commit_changes()
    sys.exit(ExitCode.SUCCESS)
