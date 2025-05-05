"""
:Description: CLI tool that performs a bulk build operation for rattler-build.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import operator
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Optional, cast

import click

from conda_recipe_manager.commands.utils.print import print_err
from conda_recipe_manager.commands.utils.types import ExitCode
from conda_recipe_manager.parser.types import V1_FORMAT_RECIPE_FILE_NAME

# When performing a bulk operation, overall "success" is indicated by the % of recipe files that were built
# "successfully"
DEFAULT_BULK_SUCCESS_PASS_THRESHOLD: Final[float] = 0.80
RATTLER_ERROR_REGEX = re.compile(r"Error:\s+.*")
# Timeout to halt operation
DEFAULT_RATTLER_BUILD_TIMEOUT: Final[int] = 120


@dataclass
class BuildResult:
    """
    Struct that contains the results, metadata, errors, etc of building a single recipe file.
    """

    code: int
    errors: list[str]


def build_recipe(file: Path, path: Path, args: list[str]) -> tuple[str, BuildResult]:
    """
    Helper function that performs the build operation for parallelizable execution. Logs rattler-build failures to
    STDERR.

    :param file: Recipe file to build
    :param path: Path argument provided by the user
    :param args: List of arguments to provide whole-sale to rattler-build
    :returns: Tuple containing the key/value pairing that tracks the result of the build operation
    """
    cmd: list[str] = ["rattler-build", "build", "-r", str(file)]
    cmd.extend(args)
    try:
        output: Final[subprocess.CompletedProcess[str]] = subprocess.run(
            " ".join(cmd),
            encoding="utf-8",
            capture_output=True,
            shell=True,
            check=False,
            timeout=DEFAULT_RATTLER_BUILD_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return str(file.relative_to(path)), BuildResult(
            code=ExitCode.TIMEOUT,
            errors=["Recipe build dry-run timed out."],
        )

    return str(file.relative_to(path)), BuildResult(
        code=output.returncode,
        errors=cast(list[str], RATTLER_ERROR_REGEX.findall(output.stderr)),
    )


def create_debug_file(debug_log: Path, results: dict[str, BuildResult], error_histogram: dict[str, int]) -> None:
    """
    Generates a debug file containing an organized dump of all the recipes that got a particular error message.

    :param debug_log: Log file to write to
    :param results:
    :param error_histogram:
    """
    # Metric-driven development: list the recipes associated with each failure, tracking how many recipes the failure
    # is seen in.

    errors = []
    # TODO: This could probably be done more efficiently, but at our current scale for a debugging tool, this is fine.
    for cur_error in error_histogram.keys():
        recipes: list[str] = []
        for file, build_result in results.items():
            if cur_error in build_result.errors:
                recipes.append(file)

        # Sort recipes by name. In theory, this will group similar recipes together (like R packages)
        recipes.sort()
        errors.append(
            {
                "error": cur_error,
                "recipe_count": len(recipes),
                "recipes": recipes,
            }
        )

    errors.sort(key=operator.itemgetter("recipe_count"), reverse=True)
    dump = {"errors": errors}
    debug_log.write_text(json.dumps(dump, indent=2), encoding="utf-8")


@click.command(
    short_help="Given a directory, performs a bulk rattler-build operation. Assumes rattler-build is installed.",
    context_settings=cast(
        dict[str, bool],
        {
            "ignore_unknown_options": True,
            "allow_extra_args": True,
        },
    ),
)
@click.argument("path", type=click.Path(exists=True, path_type=Path, file_okay=False))
@click.option(
    "--min-success-rate",
    "-m",
    type=click.FloatRange(0, 1),
    default=DEFAULT_BULK_SUCCESS_PASS_THRESHOLD,
    help="Sets a minimum passing success rate for bulk operations.",
)
@click.option(
    "--truncate",
    "-t",
    is_flag=True,
    help="Truncates logging. On large tests in a GitHub CI environment, this can eliminate log buffering issues.",
)
@click.option(
    "--debug-log",
    "-l",
    type=click.Path(exists=False, file_okay=True, dir_okay=False, path_type=Path),
    help="Dumps a large debug log to the file specified.",
)
@click.pass_context
def rattler_bulk_build(
    ctx: click.Context, path: Path, min_success_rate: float, truncate: bool, debug_log: Optional[Path]
) -> None:
    """
    Given a directory of feedstock repositories, performs multiple recipe builds using rattler-build.
    All unknown trailing options and arguments for this script are passed directly to `rattler-build build`.
    NOTE:
        - The build command is run as `rattler-build build -r <recipe.yaml> <ARGS>`
        - rattler-build errors are dumped to STDERR

    """
    start_time: Final[float] = time.time()
    files: Final[list[Path]] = []
    for file_path in path.rglob(V1_FORMAT_RECIPE_FILE_NAME):
        files.append(file_path)

    if not files:
        print_err(f"No `recipe.yaml` files found in: {path}")
        sys.exit(ExitCode.NO_FILES_FOUND)

    # Process recipes in parallel
    thread_pool_size: Final[int] = mp.cpu_count()
    with mp.Pool(thread_pool_size) as pool:
        results = dict(pool.starmap(build_recipe, [(file, path, ctx.args) for file in files]))  # type: ignore[misc]

    # Gather statistics
    total_recipes: Final[int] = len(files)
    total_processed: Final[int] = len(results)
    total_errors = 0
    total_success = 0
    recipes_with_errors: list[str] = []
    error_histogram: dict[str, int] = {}
    for file, build_result in results.items():
        if build_result.code == ExitCode.SUCCESS:
            total_success += 1
        else:
            total_errors += 1
            recipes_with_errors.append(file)
        if build_result.errors:
            for error in build_result.errors:
                if error not in error_histogram:
                    error_histogram[error] = 0
                error_histogram[error] += 1
    percent_success: Final[float] = round(total_success / total_recipes, 2)

    total_time: Final[float] = time.time() - start_time
    stats = {
        "total_recipe_files": total_recipes,
        "total_recipes_processed": total_processed,
        "total_errors": total_errors,
        "percent_errors": round(total_errors / total_recipes, 2),
        "percent_success": percent_success,
        "timings": {
            "total_exec_time": round(total_time, 2),
            "avg_recipe_time": round(total_time / total_recipes, 2),
            "thread_pool_size": thread_pool_size,
        },
    }
    final_output = {
        "info": {
            "command_name": "rattler-bulk-build",
            "directory": Path(path).name,
        },
        "error_histogram": error_histogram,
        "statistics": stats,
    }
    if not truncate:
        final_output["recipes_with_build_error_code"] = recipes_with_errors

    if debug_log is not None:
        create_debug_file(debug_log, results, error_histogram)

    print(json.dumps(final_output, indent=2))
    sys.exit(ExitCode.SUCCESS if percent_success >= min_success_rate else ExitCode.MISSED_SUCCESS_THRESHOLD)
