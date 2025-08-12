"""
:Description: Module that provides tooling related to scanning/reading files and other software resources.
"""

import logging

# Default to emitting no logs. It is up to the client program to define logging conditions.
logging.getLogger(__name__).addHandler(logging.NullHandler())
