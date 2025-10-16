"""
:Description: Module that provides general Artifact Fetching utilities and factory methods.
"""

from __future__ import annotations

import concurrent.futures as cf
import logging
import time
from contextlib import ExitStack, contextmanager
from typing import Final, Generator, cast

from conda_recipe_manager.fetcher.base_artifact_fetcher import BaseArtifactFetcher
from conda_recipe_manager.fetcher.exceptions import FetchError, FetchUnsupportedError
from conda_recipe_manager.fetcher.git_artifact_fetcher import GitArtifactFetcher
from conda_recipe_manager.fetcher.http_artifact_fetcher import HttpArtifactFetcher
from conda_recipe_manager.parser.recipe_reader import RecipeReader
from conda_recipe_manager.parser.types import SchemaVersion
from conda_recipe_manager.types import Primitives
from conda_recipe_manager.utils.typing import optional_str

log: Final = logging.getLogger(__name__)

# Maps the `/source` recipe-section path to a corresponding recipe fetcher instance.
FetcherTable = dict[str, BaseArtifactFetcher]
# Maps a future to its associated `/source` recipe-section path and a fetcher instance that fetched in the future.
FetcherFuturesTable = dict[cf.Future[None], tuple[str, BaseArtifactFetcher]]

# Maximum number of retries to attempt when trying to fetch an external artifact.
DEFAULT_RETRY_LIMIT: Final[int] = 5
# How much longer (in seconds) we should wait per retry.
DEFAULT_RETRY_INTERVAL: Final[float] = 10


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


@contextmanager
def from_recipe(recipe: RecipeReader, ignore_unsupported: bool = False) -> Generator[FetcherTable]:
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
    :returns: A context-managed-generator that yields a map containing one path and Artifact Fetcher instance pair per
        source found in the recipe file.
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

    with ExitStack() as stack:
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
                sources[src_path] = stack.enter_context(HttpArtifactFetcher(src_name, url))
            elif git_url is not None:
                sources[src_path] = stack.enter_context(
                    GitArtifactFetcher(
                        src_name,
                        git_url,
                        branch=optional_str(parsed_source.get(_render_git_key(recipe, "git_branch"))),
                        tag=optional_str(parsed_source.get(_render_git_key(recipe, "git_tag"))),
                        rev=optional_str(parsed_source.get(_render_git_key(recipe, "git_rev"))),
                    )
                )
            elif not ignore_unsupported:
                raise FetchUnsupportedError(f"{recipe_name} contains an unsupported source object at `{src_path}`.")

        yield sources


def _fetch_archive(fetcher: BaseArtifactFetcher, retry_interval: float, retries: int) -> None:
    """
    Fetches the target source archive (with retries) for future use.

    :param fetcher: Artifact fetching instance to use.
    :param retry_interval: (Optional) Base quantity of time (in seconds) to wait between fetch attempts.
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
            if retry_id < retries:
                time.sleep(retry_id * retry_interval)

    raise FetchError(f"Failed to fetch `{fetcher}` after {retries} retries.")


@contextmanager
def fetch_all_artifacts_with_retry(
    recipe_reader: RecipeReader, retry_interval: float = DEFAULT_RETRY_INTERVAL, retries: int = DEFAULT_RETRY_LIMIT
) -> Generator[FetcherFuturesTable]:
    """
    Starts a threadpool that pulls-down all source artifacts for a recipe file, with a built-in retry mechanism.

    :param recipe_reader: READ-ONLY Parser instance for the target recipe. Ensuring this is a read-only parsing class
        provides some thread safety through abusing a type checker (like `mypy`).
    :param retry_interval: (Optional) Base quantity of time (in seconds) to wait between fetch attempts.
    :param retries: (Optional) Number of retries to attempt. Defaults to `_RETRY_LIMIT` constant.
    :raises FetchError: On resolving any returned future, if fetching a source artifact failed.
    :returns: A generator containing a table that maps futures to the source artifact path in the recipe file and
        the fetcher instance itself.
    """
    with from_recipe(recipe_reader, True) as fetcher_tbl:
        with cf.ThreadPoolExecutor() as executor:
            artifact_futures_tbl = {
                executor.submit(_fetch_archive, fetcher, retry_interval, retries): (src_path, fetcher)
                for src_path, fetcher in fetcher_tbl.items()
            }
            yield artifact_futures_tbl
