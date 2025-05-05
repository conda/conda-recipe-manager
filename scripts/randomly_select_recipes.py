#!/usr/bin/env python3
"""
:Description: Helper script to randomly select and acquire recipe files from a GitHub org.
"""
import argparse
import csv
import multiprocessing as mp
import random
from pathlib import Path
from typing import Final, cast

import requests

# GET request timeout, in seconds
HTTP_GET_TIMEOUT: Final[float] = 15


def fetch_repo(org_repo: str, out_dir: Path) -> str:
    """
    Fetch a feedstock repo's recipe file and dump it to a corresponding location on disk.

    :param org_repo: String containing `org/repo`, which is what `gh repo list` returns
    :param out_dir: Path to the directory where files should be saved to
    :returns: The repository identifier, if successfully pulled and saved. Otherwise returns an empty string
    """
    url_options: Final[list[str]] = [
        f"https://raw.githubusercontent.com/{org_repo}/main/recipe/meta.yaml",
        f"https://raw.githubusercontent.com/{org_repo}/master/recipe/meta.yaml",
    ]

    slash_idx: Final[int] = org_repo.find("/")
    if slash_idx < 0:
        return ""
    repo: Final[str] = org_repo[slash_idx + 1 :]
    file_path: Final[Path] = out_dir / f"{repo}/recipe/meta.yaml"

    for url in url_options:
        try:
            response = requests.get(url, timeout=HTTP_GET_TIMEOUT)
            if response.status_code == 200:
                file_path.parent.mkdir(exist_ok=True, parents=True)
                file_path.write_text(response.text)
                return org_repo
        except requests.exceptions.RequestException:  # type: ignore[misc]
            continue
    return ""


def main() -> None:
    """
    Main execution point of the script
    """
    parser = argparse.ArgumentParser(
        description="Randomly pulls n number of recipe files from a list of repos from a GitHub organization"
    )
    parser.add_argument("--exclude", "-e", default="", type=str, help="File containing a list of repos to exclude")
    parser.add_argument("file", type=Path, help="File containing the output of `gh repo list <org>`")
    parser.add_argument("num_recipes", type=int, help="Target number of recipes to select")
    parser.add_argument("out_dir", type=Path, help="Directory to place fetched recipe files in.")
    args = parser.parse_args()

    # Keep the type checker happy
    exclude: Final[bool] = cast(bool, args.exclude)
    gh_list_file: Final[Path] = cast(Path, args.file)
    num_recipes: Final[int] = cast(int, args.num_recipes)
    out_dir: Final[Path] = cast(Path, args.out_dir)

    # Parse excluded repos
    # TODO: This list probably comes from `ls` and won't have the prefixed org name
    excluded_repos: set[str] = set()
    if exclude:
        with open(exclude, encoding="utf-8") as fd:
            for line in fd:
                excluded_repos.add(line.strip())

    # Parse the GitHub repo list
    all_repos: set[str] = set()
    with open(gh_list_file, encoding="utf-8") as fd:
        reader = csv.reader(fd, delimiter="\t", quotechar='"')
        for row in reader:
            if not row:
                continue
            all_repos.add(row[0])

    # Randomly select N valid repos
    allowed_repos: Final[set[str]] = all_repos - excluded_repos
    picked_repos: Final[set[str]] = (
        allowed_repos if num_recipes >= len(allowed_repos) else set(random.sample(sorted(allowed_repos), num_recipes))
    )

    print(f"Selected {len(picked_repos)} out of {num_recipes} requested repos...")
    print("Fetching...")

    # This method could be refined. But to be lazy and avoid authentication issues and extra dependencies, we make an
    # attempt to pull the raw files based on an assumed location.
    with mp.Pool(mp.cpu_count()) as pool:
        results = pool.starmap(fetch_repo, [(repo, out_dir) for repo in picked_repos])  # type: ignore[misc]

    unique_results: Final[set[str]] = set(results)
    if "" in unique_results:
        unique_results.remove("")
    print(f"Fetched {len(unique_results)} out of {len(picked_repos)} picked repositories...")


if __name__ == "__main__":
    main()
