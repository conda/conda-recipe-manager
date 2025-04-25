"""
:Description: Provides convenience utilities used by all modules.
"""

from __future__ import annotations

import importlib.metadata


def get_crm_version() -> str:
    """
    Convenience function to programmatically acquire the version of this project.

    :return: The current version of Conda Recipe Manager.
    """
    return importlib.metadata.version(__name__.split(".", maxsplit=1)[0])
