#!/usr/bin/env python3
"""
:Description: Given a directory of CI logs, parse and organize the JSON output for easier consumption.
                This is a quick and dirty script, not meant to be maintained with the usual standard of quality.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Final, cast, no_type_check

# Adapted from: https://stackoverflow.com/questions/3143070/regex-to-match-an-iso-8601-datetime-string
ISO_8601_REGEX: Final[re.Pattern[str]] = re.compile(r"\d{4}-[01]\d-[0-3]\dT[0-2]\d:[0-5]\d:[0-5]\d\.\d+Z\s")

# Regex used to find a single JSON blob
JSON_OBJ_REGEX: Final[re.Pattern[str]] = re.compile(r"\n\{\n.*\n\}\n", re.MULTILINE | re.DOTALL)

# Basic JSON type to shut the static analyzer up for our purposes. Allows the script to be run independently without
# referencing the better JSON type defined in this project.
BasicJsonType = dict[str, dict[str, int | str] | str]


@no_type_check
def aggregate_stats(stats: list[dict[str, int | float]]) -> dict[str, int | float]:
    """
    Takes a list of dictionaries full of common statistics. All values are added together, unless the value is a
    percentage. Those are averaged together.

    :param stats: List of statistics tables to process
    :returns: One table of accumulated statistics
    """
    accumulated_stats: dict[str, int | float] = {}
    total_tests: Final[int] = len(stats)

    # Track which stats are %'s to average later.
    percent_keys: set[str] = set()

    for tbl in stats:
        # Older versions of the test scripts were not consistent about how the "statistics" section was labeled.
        stats_key = "stats" if "stats" in tbl else "statistics"
        for key, value in tbl[stats_key].items():
            # Ignore non-numeric fields (like the `timinings` data structure)
            if not isinstance(value, (int, float)):
                continue
            if cast(str, key).startswith("percent_"):
                percent_keys.add(key)
            accumulated_stats.setdefault(key, 0)
            accumulated_stats[key] += value

    for key in percent_keys:
        accumulated_stats[key] = round(accumulated_stats[key] / total_tests, 2)

    return accumulated_stats


@no_type_check
def generate_summary(convert_results: list[BasicJsonType], dry_run_results: list[BasicJsonType]) -> BasicJsonType:
    """
    Given the list of parsed JSON blobs of interest from the log files, summarize the results.

    NOTE: Type-checking has been disabled for this function given that the statistics we will track may change
    frequently and we don't want this helper script to become a maintenance headache. The access of JSON values is on
    output that we have direct control over.

    :param convert_results: List of parsed JSON for conversion results
    :param dry_run_results: List of parsed JSON for dry-run results
    :returns: Summary JSON object to display in the final results.
    """
    fields_to_pull: Final[list[str]] = [
        # Conversion phase
        "percent_recipe_exceptions",
        "percent_recipe_errors",
        "percent_recipe_success",
        # rattler dry-run phase
        "percent_errors",
        "percent_success",
    ]
    test_data: dict[str, dict[str, str | int]] = {}

    # Helper function for accumulating counts of tests that have been run per target directory of integration tests.
    def _summarize_tests(results: list[BasicJsonType], test_title: str) -> None:
        for result in results:
            test = Path(result["info"]["directory"]).name
            test_data.setdefault(test, {})
            test_data[test].setdefault("test_count", 0)
            test_data[test]["test_count"] += 1

            stats_key = "stats" if "stats" in result else "statistics"
            for field in fields_to_pull:
                if field in result[stats_key]:
                    test_data[test].setdefault(test_title, {})
                    test_data[test][test_title][field] = result[stats_key][field]

    _summarize_tests(convert_results, "recipe_conversion")
    _summarize_tests(dry_run_results, "recipe_dry_run")

    return {
        "all_stages": {
            "recipe_conversion": aggregate_stats(convert_results),
            "rattler_dry_run": aggregate_stats(dry_run_results),
        },
        "test_summaries": dict(sorted(test_data.items())),
    }


def read_logs(log_dir: Path) -> tuple[list[BasicJsonType], list[BasicJsonType]]:
    """
    Parses-out all the recognized JSON blobs found in the log files.

    :param log_dir: Path to the directory containing all the log files.
    :returns: The lists of parsed JSON blobs from both integration testing phases.
    """
    convert_results: list[BasicJsonType] = []
    dry_run_results: list[BasicJsonType] = []
    for file in log_dir.iterdir():
        if file.is_dir() or file.name == ".DS_Store":
            continue
        content = file.read_text(encoding="utf-8")
        # Strip out all the timestamps
        lines = ISO_8601_REGEX.sub("", content).splitlines()

        start_idx = 0
        for i, line in enumerate(lines):
            if line == "{":
                start_idx = i
            if line == "}":
                # Log the range of lines that failed to be recognized, if need be.
                log_range = f"{file}:{start_idx+1}-{i+1}"
                try:
                    data = cast(BasicJsonType, json.loads("\n".join(lines[start_idx : i + 1])))
                    # Filter-out unrecognized JSON blobs in the logs
                    if "info" not in data or "command_name" not in data["info"]:
                        print(f"Could not recognize JSON object from {log_range}", file=sys.stderr)
                        continue
                    if data["info"]["command_name"] == "convert":  # type: ignore[index]
                        convert_results.append(data)
                    else:
                        dry_run_results.append(data)
                except json.JSONDecodeError:
                    start_idx = 0
                    print(f"Could not parse lines from {log_range}", file=sys.stderr)
                    continue
    return convert_results, dry_run_results


def main() -> None:
    """
    Main execution point of the script
    """
    parser = argparse.ArgumentParser(
        description="Extracts JSON results from CI operations from a directory of CI log files"
    )
    parser.add_argument("dir", type=Path, help="Directory that contains log files to parse.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enables verbose final report.")
    args = parser.parse_args()

    log_dir: Final[Path] = Path(cast(str, args.dir))
    verbose: Final[bool] = cast(bool, args.verbose)

    # Separate test results into their own lists
    convert_results, dry_run_results = read_logs(log_dir)

    # Aggregate the final results, putting the summary information at the top, followed by the raw results from the
    # log files.
    final_results = {
        "summary": cast(BasicJsonType, generate_summary(convert_results, dry_run_results)),
    }
    if verbose:
        final_results["raw_conversion_results"] = convert_results  # type: ignore[assignment]
        final_results["raw_dry_run_results"] = dry_run_results  # type: ignore[assignment]

    print(json.dumps(final_results, indent=2))


if __name__ == "__main__":
    main()
