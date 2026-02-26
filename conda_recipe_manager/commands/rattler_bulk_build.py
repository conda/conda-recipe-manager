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

# Common variables seen in Conda Build Config (CBC) files. As of `rattler-build v0.58.0+`, our integration tests will
# erroneously fail if these are not provided. We could use a conda-forge or Anaconda-provided CBC file, but this method
# ensures we are consistent across ecosystems represented in the tests AND prevents discrepancies with changing external
# files.
_RATTLER_BUILD_VARIANT_VARS: Final = [
    "python=3.11",
    "python=3.12",
    "python=3.13",
    "python_implementation=cpython",
    "python_impl=cpython",
    "numpy=2.4.2",
    "blas_impl=openblas",
    "c_compiler=gcc",
    "c_stdlib=sysroot",
    "cxx_compiler=gxx",
    "cuda_compiler=cuda-nvcc",
    "fortran_compiler=gfortran",
    "m2w64_c_compiler=m2w64-toolchain",
    "m2w64_cxx_compiler=m2w64-toolchain",
    "m2w64_fortran_compiler=m2w64-toolchain",
    "ucrt64_c_compiler=ucrt64-gcc-toolchain",
    "ucrt64_cxx_compiler=ucrt64-gcc-toolchain",
    "ucrt64_fortran_compiler=ucrt64-gcc-toolchain",
    "rust_compiler=rust",
    "rust_nightly_compiler=rust-nightly",
    "rust_compiler_version=1.93.1",
    "rust_nightly_compiler_version=1.92.0_2025-10-13",
    "rust_gnu_compiler=rust-gnu",
    "rust_gnu_compiler_version=1.93.1",
    "VERBOSE_AT=V=1",
    "VERBOSE_CM=VERBOSE=1",
    "cran_mirror=https://cran.r-project.org",
    "c_compiler_version=14.3.0",
    "c_stdlib_version=2.28",
    "cxx_compiler_version=14.3.0",
    "cuda_compiler_version=12.4",
    "fortran_compiler_version=14.3.0",
    "clang_variant=clang",
    "go_compiler=go-nocgo",
    "go_compiler_version=1.21",
    "cgo_compiler=go-cgo",
    "cgo_compiler_version=1.21",
    "r_base=4.3.1",
    "r_version=4.3.1",
    "r_implementation=r-base",
]


@dataclass
class BuildResult:
    """
    Struct that contains the results, metadata, errors, etc of building a single recipe file.
    """

    code: int
    errors: list[str]


def _build_recipe(file: Path, path: Path, inject_vars: bool, args: list[str]) -> tuple[str, BuildResult]:
    """
    Helper function that performs the build operation for parallelizable execution. Logs rattler-build failures to
    STDERR.

    :param file: Recipe file to build
    :param path: Path argument provided by the user
    :param inject_vars: Flag indicating if fake recipe variables should be injected into the build command. Used for
        CRM's integration tests.
    :param args: List of arguments to provide whole-sale to rattler-build
    :returns: Tuple containing the key/value pairing that tracks the result of the build operation
    """
    cmd: list[str] = ["rattler-build", "build", "-r", str(file)]
    if inject_vars:
        for var in _RATTLER_BUILD_VARIANT_VARS:
            cmd += ["--variant", var]
    cmd.extend(args)
    try:
        output: Final[subprocess.CompletedProcess[str]] = subprocess.run(
            cmd,
            encoding="utf-8",
            capture_output=True,
            shell=False,
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


def _create_debug_file(debug_log: Path, results: dict[str, BuildResult], error_histogram: dict[str, int]) -> None:
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
# Added to support `rattler-build v0.58.0+`, which fails builds if JINJA variables are not defined. These variables
# are commonly found in Conda Build Config files.
@click.option(
    "--inject-vars",
    is_flag=True,
    help="Injects variables for `rattler-build` so that integration tests don't fail on undefined variables.",
)
@click.pass_context
def rattler_bulk_build(
    ctx: click.Context,
    path: Path,
    min_success_rate: float,
    truncate: bool,
    debug_log: Optional[Path],
    inject_vars: bool,
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
        results = dict(
            pool.starmap(_build_recipe, [(file, path, inject_vars, ctx.args) for file in files])  # type: ignore[misc]
        )

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
        _create_debug_file(debug_log, results, error_histogram)

    print(json.dumps(final_output, indent=2))
    sys.exit(ExitCode.SUCCESS if percent_success >= min_success_rate else ExitCode.MISSED_SUCCESS_THRESHOLD)
