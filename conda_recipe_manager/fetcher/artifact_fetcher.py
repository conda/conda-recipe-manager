"""
:Description: Module that provides general Artifact Fetching utilities and factory methods.
"""

from __future__ import annotations

from typing import cast

from conda_recipe_manager.fetcher.base_artifact_fetcher import BaseArtifactFetcher
from conda_recipe_manager.fetcher.exceptions import FetchUnsupportedError
from conda_recipe_manager.fetcher.git_artifact_fetcher import GitArtifactFetcher
from conda_recipe_manager.fetcher.http_artifact_fetcher import HttpArtifactFetcher
from conda_recipe_manager.parser.recipe_reader import RecipeReader
from conda_recipe_manager.parser.types import SchemaVersion
from conda_recipe_manager.types import Primitives
from conda_recipe_manager.utils.typing import optional_str


def _render_git_key(recipe: RecipeReader, key: str) -> str:
    """
    Given the V0 name for a target key used in git-backed recipe sources, return the equivalent key for the recipe
    format.

    :param recipe: Parser instance for the target recipe
    :param key: V0 Name for the target git source key
    :raises FetchUnsupportedError: If an unrecognized key has been provided.
    :returns: The equivalent key for the recipe's schema.
    """
    match recipe.get_schema_version():
        case SchemaVersion.V0:
            return key
        case SchemaVersion.V1:
            match key:
                case "git_url":
                    return "git"
                case "git_branch":
                    return "branch"
                case "git_tag":
                    return "tag"
                case "git_rev":
                    return "rev"
                # If this case happens, a developer made a typo. Therefore it should ignore the `ignore_unsupported`
                # flag in the hopes of being caught early by a unit test.
                case _:
                    raise FetchUnsupportedError(f"The following key is not supported for git sources: {key}")


def from_recipe(recipe: RecipeReader, ignore_unsupported: bool = False) -> dict[str, BaseArtifactFetcher]:
    """
    Parses and constructs a list of artifact-fetching objects based on the contents of a recipe.

    NOTE: To keep this function fast, this function does not invoke `fetch()` on any artifacts found. It is up to the
    caller to manage artifact retrieval.

    Currently supported sources (per recipe schema):
      - HTTP/HTTPS with tar or zip artifacts (V0 and V1)
      - git (unauthenticated) (V0 and V1)

    :param recipe: Parser instance for the target recipe
    :param ignore_unsupported: (Optional) If set to `True`, ignore currently unsupported artifacts found in the source
        section and return the list of supported sources. Otherwise, throw an exception.
    :raises FetchUnsupportedError: If an unsupported source format is found.
    :returns: A map containing one path and Artifact Fetcher instance pair per source found in the recipe file.
    """
    sources: dict[str, BaseArtifactFetcher] = {}
    parsed_sources = cast(
        dict[str, Primitives] | list[dict[str, Primitives]], recipe.get_value("/source", sub_vars=True, default=[])
    )
    # TODO Handle selector evaluation/determine how common it is to have a selector in `/source`

    # Normalize to a list to handle both single and multi-source cases.
    is_src_lst = True
    if not isinstance(parsed_sources, list):
        parsed_sources = [parsed_sources]
        is_src_lst = False

    recipe_name = recipe.get_recipe_name()
    if recipe_name is None:
        recipe_name = "Unknown Recipe"

    for i, parsed_source in enumerate(parsed_sources):
        # NOTE: `optional_str()` is used to force evaluation of potentially unknown types to strings for input
        #       sanitation purposes.
        # NOTE: `url` is the same for both V0 and V1 formats.
        url = optional_str(parsed_source.get("url"))
        git_url = optional_str(parsed_source.get(_render_git_key(recipe, "git_url")))

        src_name = recipe_name if len(parsed_sources) == 1 else f"{recipe_name}_{i}"

        # If the source section is not a list, it contains one "flag" source object.
        src_path = f"/source/{i}" if is_src_lst else "/source"
        if url is not None:
            sources[src_path] = HttpArtifactFetcher(src_name, url)
        elif git_url is not None:
            sources[src_path] = GitArtifactFetcher(
                src_name,
                git_url,
                branch=optional_str(parsed_source.get(_render_git_key(recipe, "git_branch"))),
                tag=optional_str(parsed_source.get(_render_git_key(recipe, "git_tag"))),
                rev=optional_str(parsed_source.get(_render_git_key(recipe, "git_rev"))),
            )
        elif not ignore_unsupported:
            raise FetchUnsupportedError(f"{recipe_name} contains an unsupported source object at `{src_path}`.")

    return sources
