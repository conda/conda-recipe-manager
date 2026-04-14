"""
:Description: Parser that is capable of comprehending Conda Build Configuration (CBC) files.
"""

from __future__ import annotations

import logging
from typing import Final

from conda_recipe_manager.parser.cbc_reader import CbcReader

log: Final[logging.Logger] = logging.getLogger(__name__)


class CbcParser(CbcReader):
    """
    Parses a Conda Build Configuration (CBC) file and provides editing capabilities. Often these files are named
    `conda_build_configuration.yaml` or `cbc.yaml`.

    As of writing, this is a placeholder for future work; to follow in the naming conventions established by the recipe
    parser and reader classes.
    """

    pass
