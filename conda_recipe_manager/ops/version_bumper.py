"""
:Description: Provides library tooling to perform recipe version updates or recipe "bumps". Most of the work found
    here originates from the `crm bump-recipe` command line interface.
"""

import logging
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Final, Generator

from conda_recipe_manager.fetcher.artifact_fetcher import FetcherTable, from_recipe
from conda_recipe_manager.fetcher.exceptions import FetchError
from conda_recipe_manager.fetcher.http_artifact_fetcher import HttpArtifactFetcher
from conda_recipe_manager.parser.recipe_parser import RecipeParser

log: Final = logging.getLogger(__name__)


class VersionBumper:
    """
    TODO
    """

    # Maximum number of retries to attempt when trying to fetch an external artifact.
    _RETRY_LIMIT: Final[int] = 5
    # How much longer (in seconds) we should wait per retry.
    _DEFAULT_RETRY_INTERVAL: Final[int] = 10

    def __init__(self) -> None:
        """
        TODO
        """
        # TODO pass this in? or ditch class entirely
        self._recipe_parser = RecipeParser("")

    @staticmethod
    def _fetch_archive(
        fetcher: HttpArtifactFetcher, retry_interval: int = _DEFAULT_RETRY_INTERVAL, retries: int = _RETRY_LIMIT
    ) -> None:
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
    def fetch_all_artifacts_with_retry(self) -> Generator[FetcherTable]:
        """
        Starts a threadpool TODO
        """
        with from_recipe(self._recipe_parser, True) as fetcher_tbl:
            yield fetcher_tbl
