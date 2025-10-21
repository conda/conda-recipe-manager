"""
:Description: Module that provides general Artifact Fetching utilities and factory methods.
"""

from __future__ import annotations

import concurrent.futures as cf
import logging
import re
import time
from contextlib import ExitStack, contextmanager
from typing import Final, Generator, Optional, cast

from conda_recipe_manager.fetcher.api import pypi
from conda_recipe_manager.fetcher.base_artifact_fetcher import BaseArtifactFetcher
from conda_recipe_manager.fetcher.exceptions import FetchError, FetchUnsupportedError
from conda_recipe_manager.fetcher.git_artifact_fetcher import GitArtifactFetcher
from conda_recipe_manager.fetcher.http_artifact_fetcher import HttpArtifactFetcher
from conda_recipe_manager.parser.recipe_reader import RecipeReader
from conda_recipe_manager.parser.types import SchemaVersion
from conda_recipe_manager.types import Primitives
from conda_recipe_manager.utils.typing import optional_str

log: Final = logging.getLogger(__name__)

# Standardized value returned by a fetching future function. This is a tuple containing:
#   - The artifact fetcher instance used to fetch a source artifact
#   - An optionally-included string containing the new target URL, if a URL correction was requested and occurred.
_FutureFetch = tuple[BaseArtifactFetcher, Optional[str]]

# Maps the `/source` recipe-section path to a corresponding recipe fetcher instance.
FetcherTable = dict[str, BaseArtifactFetcher]
# Maps a future to its associated `/source` recipe-section path. The fetcher instance that performed the fetch and the
# optionally-set corrected/updated URL must be obtained from the resolved future.
FetcherFuturesTable = dict[cf.Future[_FutureFetch], str]

# Maximum number of retries to attempt when trying to fetch an external artifact.
DEFAULT_RETRY_LIMIT: Final[int] = 5
# How much longer (in seconds) we should wait per retry.
DEFAULT_RETRY_INTERVAL: Final[float] = 10


class _RecipePaths:
    """
    Namespace to store common recipe path constants.
    """

    BUILD_NUM: Final[str] = "/build/number"
    SOURCE: Final[str] = "/source"
    SINGLE_URL: Final[str] = f"{SOURCE}/url"
    SINGLE_SHA_256: Final[str] = f"{SOURCE}/sha256"
    VERSION: Final[str] = "/package/version"


class _Regex:
    """
    Namespace that contains all pre-compiled regular expressions used in this tool.
    """

    # Attempts to match PyPi source archive URLs by the start of the URL.
    PYPI_URL: Final[re.Pattern[str]] = re.compile(
        r"https?://pypi\.(?:io|org)/packages/source/[a-zA-Z0-9]/|https?://files\.pythonhosted\.org/"
    )


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


def _fetch_archive(fetcher: BaseArtifactFetcher, retry_interval: float, retries: int) -> _FutureFetch:
    """
    Fetches the target source archive (with retries) for future use.

    :param fetcher: Artifact fetching instance to use.
    :param retry_interval: Base quantity of time (in seconds) to wait between fetch attempts.
    :param retries: Number of retries to attempt.
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
            return (fetcher, None)
        except FetchError:
            if retry_id < retries:
                time.sleep(retry_id * retry_interval)

    raise FetchError(f"Failed to fetch `{fetcher}` after {retries} retries.")


@contextmanager
def fetch_all_artifacts_with_retry(
    recipe_reader: RecipeReader,
    ignore_unsupported: bool = False,
    retry_interval: float = DEFAULT_RETRY_INTERVAL,
    retries: int = DEFAULT_RETRY_LIMIT,
) -> Generator[FetcherFuturesTable]:
    """
    Starts a threadpool that pulls-down all source artifacts for a recipe file, with a built-in retry mechanism.

    :param ignore_unsupported: (Optional) If set to `True`, ignore currently unsupported artifacts found in the source
        section and return the list of supported sources. Otherwise, throw an exception.
    :param recipe_reader: READ-ONLY Parser instance for the target recipe. Ensuring this is a read-only parsing class
        provides some thread safety through abusing a type checker (like `mypy`).
    :param retry_interval: (Optional) Base quantity of time (in seconds) to wait between fetch attempts. Defaults to
        the `DEFAULT_RETRY_INTERVAL` constant.
    :param retries: (Optional) Number of retries to attempt. Defaults to the `DEFAULT_RETRY_LIMIT` constant.
    :raises FetchUnsupportedError: If an unsupported source format is found.
    :raises FetchError: On resolving any returned future, if fetching a source artifact failed.
    :returns: A generator containing a table that maps futures to the source artifact path in the recipe file and
        the fetcher instance itself.
    """
    # In testing, using a process pool took significantly more time and resources. That aligns with how I/O bound this
    # process is. We use the `ThreadPoolExecutor` class over a `ThreadPool` so that we may leverage the error handling
    # features of the `Future` class.
    with from_recipe(recipe_reader, ignore_unsupported=ignore_unsupported) as fetcher_tbl:
        with cf.ThreadPoolExecutor() as executor:
            artifact_futures_tbl = {
                executor.submit(_fetch_archive, fetcher, retry_interval, retries): src_path
                for src_path, fetcher in fetcher_tbl.items()
            }
            yield artifact_futures_tbl


def _correct_pypi_url(recipe_reader: RecipeReader) -> str:
    """
    Handles correcting PyPi URLs by querying the PyPi API. There are many edge cases here that complicate this process,
    like managing JINJA variables commonly found in our URL values.

    :param recipe_reader: Read-only parser (enforced by our static analyzer). Editing may not be thread-safe. It is up
        to the caller to manage that risk.
    :raises FetchError: If an issue occurred while downloading or extracting the archive.
    :returns: Corrected PyPi artifact URL for the fetcher.
    """

    version_value: Final[Optional[str]] = optional_str(
        recipe_reader.get_value(_RecipePaths.VERSION, default=None, sub_vars=True)
    )
    if version_value is None:
        raise FetchError("Unable to determine recipe version for PyPi API request.")

    # TODO we eventually need to handle the case of mapping conda names to PyPi names.
    # TODO alternatively regex-out the PyPi name from the URL. However, in many cases, this might be wasted
    # compute.
    package_name: Final[Optional[str]] = recipe_reader.get_recipe_name()
    if package_name is None:
        raise FetchError("Unable to determine package name for PyPi API request.")

    # TODO add retry mechanism for PyPi API query?
    try:
        pypi_meta: Final[pypi.PackageMetadata] = pypi.fetch_package_version_metadata(package_name, version_value)
    except pypi.ApiException as e:
        raise FetchError("Failed to access the PyPi API to correct a URL.") from e

    if version_value not in pypi_meta.releases:
        raise FetchError(f"Failed to retrieve target version: {version_value}")

    # Using the PyPI metadata we can construct a url that will work for the fetcher. In case the recipe name is
    # different from the PyPI name, we use the PyPI name from the API response to ensure the url is correct.
    # See this issue for more details: https://github.com/conda/conda-recipe-manager/issues/364

    filename: Final = pypi_meta.releases[version_value].filename
    name: Final = pypi_meta.info.name
    if not (filename and name):
        raise FetchError("Unable to determine download url for PyPi API request.")

    new_url: Final = f"https://pypi.org/packages/source/{ name[0] }/{ name }/{ filename }"
    return new_url


def _fetch_corrected_archive(
    recipe_reader: RecipeReader, fetcher: BaseArtifactFetcher, retry_interval: float, retries: int
) -> _FutureFetch:
    """
    Wrapper function that attempts to retrieve an HTTP/HTTPS artifact with a retry mechanism. This also determines if a
    URL correction needs to be made.

    For example, many PyPi archives (as of approximately 2024) now use underscores in the archive file name even though
    the package name still uses hyphens.

    :param recipe_reader: Read-only parser (enforced by our static analyzer). Editing may not be thread-safe. It is up
        to the caller to manage that risk.
    :param fetcher: Artifact fetching instance to use.
    :param retry_interval: Base quantity of time (in seconds) to wait between fetch attempts.
    :param retries: Number of retries to attempt. This may be spread-out across the original URL and the corrected URL.
    :raises FetchUnsupportedError: If an unsupported source format is found.
    :raises FetchError: If an issue occurred while downloading or extracting the archive.
    :returns: The SHA-256 hash of the artifact, if it was able to be downloaded. Optionally includes a corrected URL to
        be updated in the recipe file.
    """
    # The URL correction algorithm only applies to fetchers that have an HTTP URL to correct.
    if not isinstance(fetcher, HttpArtifactFetcher):
        _fetch_archive(fetcher, retry_interval, retries)
        return (fetcher, None)

    # Skip non-PyPI artifacts.
    pypi_match: Final = _Regex.PYPI_URL.match(fetcher.get_archive_url())
    if pypi_match is None:
        _fetch_archive(fetcher, retry_interval, retries)
        return (fetcher, None)

    # Attempt to handle PyPi URLs that might have changed.
    original_retries: Final = retries // 2 + 1 if retries % 2 else retries // 2
    corrected_retries: Final = retries // 2
    try:
        _fetch_archive(fetcher, retry_interval, original_retries)
        return (fetcher, None)
    except FetchError:
        log.info("PyPI URL detected. Attempting to recover URL.")
        # The `corrected_fetcher_url` is the rendered-out URL, without variables.
        corrected_fetcher_url: Final = _correct_pypi_url(recipe_reader)
        corrected_fetcher: Final[HttpArtifactFetcher] = HttpArtifactFetcher(str(fetcher), corrected_fetcher_url)

        _fetch_archive(corrected_fetcher, retry_interval, corrected_retries)
        log.warning("Updated PyPI archive found at %s. Will attempt to update recipe file.", corrected_fetcher_url)
        return (corrected_fetcher, corrected_fetcher_url)


@contextmanager
def fetch_all_corrected_artifacts_with_retry(
    recipe_reader: RecipeReader,
    ignore_unsupported: bool = False,
    retry_interval: float = DEFAULT_RETRY_INTERVAL,
    retries: int = DEFAULT_RETRY_LIMIT,
) -> Generator[FetcherFuturesTable]:
    """
    Starts a threadpool that pulls-down all source artifacts for a recipe file, with a built-in retry mechanism AND
    attempts to find corrected PyPI source URLs.

    :param recipe_reader: READ-ONLY Parser instance for the target recipe. Ensuring this is a read-only parsing class
        provides some thread safety through abusing a type checker (like `mypy`).
    :param ignore_unsupported: (Optional) If set to `True`, ignore currently unsupported artifacts found in the source
        section and return the list of supported sources. Otherwise, throw an exception.
    :param retry_interval: (Optional) Base quantity of time (in seconds) to wait between fetch attempts.
    :param retries: (Optional) Number of retries to attempt. Defaults to `_RETRY_LIMIT` constant.
    :raises FetchError: On resolving any returned future, if fetching a source artifact failed.
    :returns: A generator containing a table that maps futures to the source artifact path in the recipe file and
        the fetcher instance itself.
    """
    # In testing, using a process pool took significantly more time and resources. That aligns with how I/O bound this
    # process is. We use the `ThreadPoolExecutor` class over a `ThreadPool` so that we may leverage the error handling
    # features of the `Future` class.
    with from_recipe(recipe_reader, ignore_unsupported=ignore_unsupported) as fetcher_tbl:
        with cf.ThreadPoolExecutor() as executor:
            artifact_futures_tbl = {
                executor.submit(_fetch_corrected_archive, recipe_reader, fetcher, retry_interval, retries): src_path
                for src_path, fetcher in fetcher_tbl.items()
            }
            yield artifact_futures_tbl
