"""
:Description: Module that provides tools for scanning/reading dependencies from various sources.
"""

import logging

# Default to emitting no logs. It is up to the client program to define logging conditions.
logging.getLogger(__name__).addHandler(logging.NullHandler())
