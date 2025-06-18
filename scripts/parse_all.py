# type: ignore
"""
Script to analyze all conda recipes in a directory and collect parsing statistics.

This script processes all feedstock directories, attempts to parse their meta.yaml files
using RecipeReader, and generates reports and visualizations of success/failure statistics.
"""
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib.pyplot as plt

from conda_recipe_manager.parser.recipe_reader import RecipeReader


def analyze_recipes(recipes_dir):
    """
    Analyze all recipes in the given directory and collect exception statistics.

    Args:
        recipes_dir (str): Path to the directory containing recipe feedstocks

    Returns:
        tuple: (exception_counter, success_count, recipe_details)
    """
    exception_counter = Counter()
    recipe_details = defaultdict(list)
    success_count = 0
    total_count = 0

    # Get all feedstock directories
    feedstock_dirs = [
        Path(d)
        for d in os.listdir(recipes_dir)
        if os.path.isdir(os.path.join(recipes_dir, d)) and d.endswith("-feedstock")
    ]

    print(f"Found {len(feedstock_dirs)} feedstock directories to analyze...")

    for i, feedstock_dir in enumerate(feedstock_dirs):
        if i % 100 == 0:
            print(f"Processing {i}/{len(feedstock_dirs)}: {feedstock_dir}")

        feedstock_path = recipes_dir / feedstock_dir
        recipe_path = feedstock_path / "recipe"
        meta_yaml_path = recipe_path / "meta.yaml"

        total_count += 1

        # Check if recipe directory and meta.yaml exist
        if not recipe_path.exists():
            exception_type = "MissingRecipeDirectory"
            exception_counter[exception_type] += 1
            recipe_details[exception_type].append(feedstock_dir)
            continue

        if not meta_yaml_path.exists():
            exception_type = "MissingMetaYaml"
            exception_counter[exception_type] += 1
            recipe_details[exception_type].append(feedstock_dir)
            continue

        # Try to create RecipeReader instance
        try:
            # RecipeReader expects the path to the recipe directory or meta.yaml file
            RecipeReader(meta_yaml_path.read_text())
            success_count += 1
        except Exception as e:  # pylint: disable=broad-exception-caught
            exception_type = type(e).__name__
            exception_counter[exception_type] += 1
            recipe_details[exception_type].append(f"{feedstock_dir}: {str(e)}")

    print(f"\nCompleted analysis of {total_count} recipes.")
    print(f"Successful: {success_count}")
    print(f"Failed: {total_count - success_count}")

    return exception_counter, success_count, recipe_details


def generate_histogram(exception_counter, success_count, output_dir="output"):
    """
    Generate and save histogram of exceptions.

    Args:
        exception_counter (Counter): Counter of exception types
        success_count (int): Number of successful RecipeReader creations
        output_dir (str): Directory to save the histogram
    """
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    # Prepare data for histogram
    labels = list(exception_counter.keys()) + ["Success"]
    counts = list(exception_counter.values()) + [success_count]

    # Create histogram
    plt.figure(figsize=(15, 8))
    bars = plt.bar(range(len(labels)), counts)

    # Customize the plot
    plt.xlabel("Exception Types")
    plt.ylabel("Frequency")
    plt.title("Histogram of RecipeReader Exceptions and Successes")
    plt.xticks(range(len(labels)), labels, rotation=45, ha="right")

    # Add value labels on bars
    for bar, count in zip(bars, counts):
        plt.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.1, str(count), ha="center", va="bottom")

    # Color successful bars differently
    bars[-1].set_color("green")  # Success bar in green

    plt.tight_layout()

    # Save the plot
    output_path = os.path.join(output_dir, "recipe_analysis_histogram.png")
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    print(f"Histogram saved to: {output_path}")

    # Also save as text report
    report_path = os.path.join(output_dir, "recipe_analysis_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("Recipe Analysis Report\n")
        f.write("=====================\n\n")
        f.write(f"Total recipes analyzed: {sum(counts)}\n")
        f.write(f"Successful: {success_count}\n")
        f.write(f"Failed: {sum(counts) - success_count}\n\n")
        f.write("Exception breakdown:\n")
        for exception_type, count in exception_counter.most_common():
            f.write(f"  {exception_type}: {count}\n")

    print(f"Text report saved to: {report_path}")

    # Show the plot
    plt.show()


def print_detailed_report(exception_counter, success_count, recipe_details):
    """
    Print a detailed report of the analysis results.
    """
    total = sum(exception_counter.values()) + success_count

    print("\n" + "=" * 50)
    print("DETAILED RECIPE ANALYSIS REPORT")
    print("=" * 50)
    print(f"Total recipes analyzed: {total}")
    print(f"Successful RecipeReader creations: {success_count} ({success_count/total*100:.1f}%)")
    failed_count = sum(exception_counter.values())
    print(f"Failed RecipeReader creations: {failed_count} ({failed_count/total*100:.1f}%)")

    print("\nException breakdown:")
    print("-" * 30)
    for exception_type, count in exception_counter.most_common():
        print(f"{exception_type:30} {count:6d} ({count/total*100:5.1f}%)")

    print("\nAll distinct exception messages for each exception type:")
    print("-" * 60)
    for exception_type, examples in recipe_details.items():
        print(f"\n{exception_type} ({exception_counter[exception_type]} occurrences):")

        # Extract distinct exception messages
        distinct_messages = set()
        feedstock_by_message = {}

        for example in examples:
            if ": " in example:
                feedstock, message = example.split(": ", 1)
                distinct_messages.add(message)
                if message not in feedstock_by_message:
                    feedstock_by_message[message] = []
                feedstock_by_message[message].append(feedstock)
            else:
                # For cases like MissingRecipeDirectory where there's no error message
                distinct_messages.add(f"Missing component in feedstock: {example}")

        # Display each distinct message with count and examples
        for i, message in enumerate(sorted(distinct_messages), 1):
            if message.startswith("Missing component"):
                # For missing directory/file cases, just show the message
                print(f"  {i}. {message}")
            else:
                # For actual exceptions, show message and affected feedstocks
                affected_feedstocks = feedstock_by_message.get(message, [])
                count = len(affected_feedstocks)
                print(f"  {i}. Message: {message}")
                print(f"     Count: {count}")
                examples_str = ", ".join(affected_feedstocks[:5])
                print(f"     Examples: {examples_str}")
                if len(affected_feedstocks) > 5:
                    print(f"     ... and {len(affected_feedstocks) - 5} more")
                print()


def main():
    """Main function to run the recipe analysis."""
    # Path to the recipes directory
    recipes_dir = Path("recipes_v0/anaconda_recipes_01")

    if not os.path.exists(recipes_dir):
        print(f"Error: Directory {recipes_dir} does not exist!")
        sys.exit(1)

    print("Starting recipe analysis...")

    # Analyze recipes
    exception_counter, success_count, recipe_details = analyze_recipes(recipes_dir)

    # Print detailed report
    print_detailed_report(exception_counter, success_count, recipe_details)

    # Generate histogram
    generate_histogram(exception_counter, success_count)

    print("\nAnalysis complete!")


if __name__ == "__main__":
    main()
