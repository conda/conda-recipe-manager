"""
:Description: Provides print utility functions
"""

from __future__ import annotations

import sys


def print_out(*args, print_enabled: bool = True, **kwargs) -> None:  # type: ignore
    """
    Convenience wrapper that prints to STDOUT

    :param print_enabled: (Optional) Flag to enable printing. Enabled by default.
    """
    if print_enabled:
        print(*args, file=sys.stdout, **kwargs)  # type: ignore


def print_err(*args, print_enabled: bool = True, **kwargs) -> None:  # type: ignore
    """
    Convenience wrapper that prints to STDERR

    :param print_enable: (Optional) Flag to enable printing. Enabled by default.
    """
    if print_enabled:
        print(*args, file=sys.stderr, **kwargs)  # type: ignore
