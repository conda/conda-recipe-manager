"""
:Description: CLI for converting an old recipe file to the "new" format.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Optional

import click

from conda_recipe_manager.commands.utils.print import print_err, print_messages, print_out
from conda_recipe_manager.commands.utils.types import ExitCode
from conda_recipe_manager.parser.enums import SchemaVersion
from conda_recipe_manager.parser.recipe_parser_convert import RecipeParserConvert
from conda_recipe_manager.parser.types import V0_FORMAT_RECIPE_FILE_NAME, V1_FORMAT_RECIPE_FILE_NAME
from conda_recipe_manager.types import MessageCategory, MessageTable

# When performing a bulk operation, overall "success" is indicated by the % of recipe files that were converted
# "successfully"
DEFAULT_BULK_SUCCESS_PASS_THRESHOLD: Final[float] = 0.80


@dataclass
class ConversionResult:
    """
    Struct that contains the results, metadata, errors, etc of converting a single recipe file.
    """

    code: ExitCode
    content: str
    file_path: Path
    msg_tbl: MessageTable
    # Extracted out of the path for bulk operations
    project_name: str

    def set_return_code(self) -> None:
        """
        Given the current state of the message table, set the appropriate return code. Does not overwrite the existing
        state unless errors or warnings were found.
        """
        error_count: Final[int] = self.msg_tbl.get_message_count(MessageCategory.ERROR)
        warn_count: Final[int] = self.msg_tbl.get_message_count(MessageCategory.WARNING)
        if error_count > 0:
            self.code = ExitCode.RENDER_ERRORS
        elif warn_count > 0:
            self.code = ExitCode.RENDER_WARNINGS


def _record_unrecoverable_failure(
    conversion_result: ConversionResult,
    exit_code: ExitCode,
    e_msg: str,
    print_output: bool,
    debug: bool,
    e: Optional[Exception] = None,
) -> ConversionResult:
    """
    Convenience function that streamlines the process of recording an unrecoverable conversion failure.

    :param conversion_result: Conversion result instance to use. This is passed into aggregate any other messages that
        could be logged prior to reaching this fatal error case.
    :param exit_code: Exit code to return for this error case.
    :param e_msg: Error message to display, if enabled.
    :param print_output: Prints the recipe to STDERR if the output file is not specified and this flag is `True`.
    :param debug: Enables debug mode output. Prints to STDERR.
    :param e: (Optional) Exception instance to capture, if applicable
    :returns: The final `conversion_result` instance that should be returned immediately.
    """
    print_err(e_msg, print_enabled=print_output)
    if e is not None:
        print_err(e, print_enabled=print_output)
        if print_output and debug:
            traceback.print_exception(e, file=sys.stderr)  #
    conversion_result.msg_tbl.add_message(MessageCategory.EXCEPTION, e_msg)
    conversion_result.code = exit_code
    return conversion_result


def convert_file(file_path: Path, output: Optional[Path], print_output: bool, debug: bool) -> ConversionResult:
    """
    Converts a single recipe file to the V1 format, tracking results.

    :param file_path: Path to the recipe file to convert
    :param output: If specified, the file contents are written to this file path. Otherwise, the file is dumped to
        STDOUT IF `print_output` is set to `True`.
    :param print_output: Prints the recipe to STDOUT/STDERR if the output file is not specified and this flag is `True`.
    :param debug: Enables debug mode output. Prints to STDERR.
    :returns: A struct containing the results of the conversion process, including debugging metadata.
    """
    # pylint: disable=too-complex
    conversion_result = ConversionResult(
        code=ExitCode.SUCCESS, content="", file_path=file_path, msg_tbl=MessageTable(), project_name=""
    )

    recipe_content: str
    try:
        recipe_content = Path(file_path).read_text(encoding="utf-8")
    except Exception as e:  # pylint: disable=broad-exception-caught
        return _record_unrecoverable_failure(
            conversion_result,
            ExitCode.READ_EXCEPTION,
            f"EXCEPTION: Failed to read: {file_path}",
            print_output,
            debug,
            e,
        )

    # Pre-process the recipe
    try:
        recipe_content = RecipeParserConvert.pre_process_recipe_text(recipe_content)
    except Exception as e:  # pylint: disable=broad-exception-caught
        return _record_unrecoverable_failure(
            conversion_result,
            ExitCode.PRE_PROCESS_EXCEPTION,
            "EXCEPTION: An exception occurred while pre-processing the recipe file",
            print_output,
            debug,
            e,
        )

    # Parse the recipe
    parser: RecipeParserConvert
    try:
        parser = RecipeParserConvert(recipe_content)
    except Exception as e:  # pylint: disable=broad-exception-caught
        return _record_unrecoverable_failure(
            conversion_result,
            ExitCode.PARSE_EXCEPTION,
            "EXCEPTION: An exception occurred while parsing the recipe file",
            print_output,
            debug,
            e,
        )

    # Only V0 recipes can be converted
    if parser.get_schema_version() != SchemaVersion.V0:
        return _record_unrecoverable_failure(
            conversion_result,
            ExitCode.ILLEGAL_OPERATION,
            "ILLEGAL OPERATION: Only V0-formatted recipe files can be converted",
            print_output,
            debug,
            None,
        )

    # Print the initial parser, if requested
    print_err("########## PARSED RECIPE FILE ##########", print_enabled=debug)
    print_err(parser, print_enabled=debug)

    # Convert the recipe
    try:
        conversion_result.content, conversion_result.msg_tbl, debug_new_parser = parser.render_to_v1_recipe_format()
        # Print the new parser, if requested
        print_err("########## CONVERTED RECIPE FILE ##########", print_enabled=debug)
        print_err(debug_new_parser, print_enabled=debug)
    except Exception as e:  # pylint: disable=broad-exception-caught
        return _record_unrecoverable_failure(
            conversion_result,
            ExitCode.RENDER_EXCEPTION,
            "EXCEPTION: An exception occurred while converting to the new recipe file",
            print_output,
            debug,
            e,
        )

    # Print or dump the results to a file. Printing is disabled for bulk operations.
    print_out(conversion_result.content, print_enabled=print_output and (output is None))
    if output is not None:
        print_err(
            "WARNING: File is not called `recipe.yaml`.",
            print_enabled=print_output and os.path.basename(output) != "recipe.yaml",
        )
        with open(output, "w", encoding="utf-8") as fptr:
            fptr.write(conversion_result.content)

    conversion_result.set_return_code()
    return conversion_result


def process_recipe(file: Path, path: Path, output: Optional[Path], debug: bool) -> tuple[str, ConversionResult]:
    """
    Helper function that performs the conversion operation for parallelizable execution.

    :param file: Recipe file to convert
    :param path: Path argument provided by the user
    :param output: Output argument file provided by the user
    :param debug: Enables debug mode output. Prints to STDERR.
    :returns: Tuple containing the key/value pairing that tracks the result of the conversion operation
    """
    out_file: Optional[Path] = None if output is None else file.parent / output
    conversion_result = convert_file(file, out_file, False, debug)
    conversion_result.project_name = file.relative_to(path).parts[0]
    return str(file.relative_to(path)), conversion_result


def _get_files_list(path: Path) -> list[Path]:
    """
    Takes the file path from the user and generates the list of target file(s). Exits the script when an unrecoverable
    state has been reached.

    :param path: Path provided from the user.
    :returns: List of files to convert.
    """
    files: list[Path] = []
    # Establish which mode of operation we are in, based on the path passed-in
    if path.is_dir():
        for file_path in path.rglob(V0_FORMAT_RECIPE_FILE_NAME):
            files.append(file_path)
        if not files:
            print_err("Could not find any recipe files in this directory.")
            sys.exit(ExitCode.CLICK_USAGE)
    elif path.is_file():
        files.append(path)
    else:
        print_err("Could not identify path as file or directory.")
        sys.exit(ExitCode.CLICK_USAGE)
    return files


def _collect_issue_stats(project_name: str, issues: list[str], hist: dict[str, int], recipes_lst: list[str]) -> int:
    """
    Given a list of issues (errors, warnings, etc), collect that data into some useful metrics.

    :param project_name: Project/recipe identifier
    :param issues: List of issues to read
    :param hist: Histogram to dump occurrence data into
    :param recipes_lst: List to append to containing recipes that had this type of issue
    :returns: How many issues were found in this recipe file
    """
    for issue in issues:
        hist.setdefault(issue, 0)
        hist[issue] += 1
    if issues:
        recipes_lst.append(project_name)
    return len(issues)


@click.command(short_help="Converts a `meta.yaml` formatted-recipe file to the new `recipe.yaml` format.")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--output",
    "-o",
    type=click.Path(exists=False),
    default=None,
    help=(
        "File to dump a new recipe to."
        f" For bulk operations, specify the file basename only (i.e. {V1_FORMAT_RECIPE_FILE_NAME})."
    ),
)
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
    "--debug",
    "-d",
    is_flag=True,
    help="Debug mode, prints debugging information to STDERR.",
)
def convert(
    path: Path, output: Optional[Path], min_success_rate: float, truncate: bool, debug: bool
) -> None:  # pylint: disable=redefined-outer-name
    """
    Recipe conversion CLI utility. By default, recipes print to STDOUT. Messages always print to STDERR. Takes 1 file or
    a directory containing multiple feedstock repositories. If the `PATH` provided is a directory, the script will
    attempt a bulk operation conversion across all subdirectories.
    """
    start_time: Final[float] = time.time()
    results: dict[str, ConversionResult] = {}
    files: list[Path] = _get_files_list(path)

    ## Single-file case ##
    if len(files) == 1:
        result: Final[ConversionResult] = convert_file(files[0], output, True, debug)
        print_messages(MessageCategory.WARNING, result.msg_tbl)
        print_messages(MessageCategory.ERROR, result.msg_tbl)
        print_err(result.msg_tbl.get_totals_message())
        sys.exit(result.code)

    ## Bulk operation ##

    # Process recipes in parallel
    thread_pool_size: Final[int] = mp.cpu_count()
    with mp.Pool(thread_pool_size) as pool:
        results = dict(
            pool.starmap(process_recipe, [(file, path, output, debug) for file in files])  # type: ignore[misc]
        )

    # Tracking failures from bulk operation
    recipes_with_except: list[str] = []
    recipes_with_errors: list[str] = []
    recipes_with_warnings: list[str] = []
    except_histogram: dict[str, int] = {}
    errors_histogram: dict[str, int] = {}
    warnings_histogram: dict[str, int] = {}
    # Stats from bulk operation
    total_time: Final[float] = time.time() - start_time
    total_recipes: Final[int] = len(files)
    # Total count of errors/warnings
    total_errors: int = 0
    total_warnings: int = 0
    # Count of recipes with at least 1 exception/error/warning
    num_recipe_success: int = 0

    for project_name, result in results.items():
        if result.code in {ExitCode.PARSE_EXCEPTION, ExitCode.READ_EXCEPTION, ExitCode.RENDER_EXCEPTION}:
            recipes_with_except.append(project_name)
            exceptions = result.msg_tbl.get_messages(MessageCategory.EXCEPTION)
            for exception in exceptions:
                except_histogram.setdefault(exception, 0)
                except_histogram[exception] += 1

        errors = result.msg_tbl.get_messages(MessageCategory.ERROR)
        total_errors += _collect_issue_stats(project_name, errors, errors_histogram, recipes_with_errors)
        total_warnings += _collect_issue_stats(
            project_name,
            result.msg_tbl.get_messages(MessageCategory.WARNING),
            warnings_histogram,
            recipes_with_warnings,
        )

        ## Success ##
        if result.code in {ExitCode.SUCCESS, ExitCode.RENDER_WARNINGS} and not errors:
            num_recipe_success += 1

    # Self-check metric. This should be the same as the other calculated success metric.
    num_theoretical_recipe_success: Final[int] = total_recipes - (len(recipes_with_except) + len(recipes_with_errors))
    percent_recipe_success: Final[float] = round(num_recipe_success / total_recipes, 2)

    stats = {
        "total_recipe_files": total_recipes,
        "total_recipes_processed": len(results),
        "total_errors": total_errors,
        "total_warnings": total_warnings,
        "num_recipe_exceptions": len(recipes_with_except),
        "num_recipe_errors": len(recipes_with_errors),
        "num_recipe_warnings": len(recipes_with_warnings),
        "num_recipe_success": num_recipe_success,
        "num_theoretical_recipe_success": num_theoretical_recipe_success,
        "percent_recipe_exceptions": round(len(recipes_with_except) / total_recipes, 2),
        "percent_recipe_errors": round(len(recipes_with_errors) / total_recipes, 2),
        "percent_recipe_warnings": round(len(recipes_with_warnings) / total_recipes, 2),
        "percent_recipe_success": percent_recipe_success,
        "percent_recipe_theoretical_success": round(num_theoretical_recipe_success / total_recipes, 2),
        "timings": {
            "total_exec_time": round(total_time, 2),
            "avg_recipe_time": round(total_time / total_recipes, 2),
            "thread_pool_size": thread_pool_size,
        },
    }

    final_output = {
        "info": {
            "command_name": "convert",
            "directory": Path(path).name,
        },
        "exception_histogram": except_histogram,
        "error_histogram": errors_histogram,
        "warnings_histogram": warnings_histogram,
        "statistics": stats,
    }
    if not truncate:
        final_output["recipes_with_exceptions"] = recipes_with_except
        final_output["recipes_with_errors"] = recipes_with_errors
        final_output["recipes_with_warnings"] = recipes_with_warnings

    print_out(json.dumps(final_output, indent=2))
    sys.exit(ExitCode.SUCCESS if percent_recipe_success >= min_success_rate else ExitCode.MISSED_SUCCESS_THRESHOLD)
