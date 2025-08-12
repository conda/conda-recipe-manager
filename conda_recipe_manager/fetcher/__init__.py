"""
:Description: Module that provides utilities for acquiring remote resources.
"""

import logging

# Default to emitting no logs. It is up to the client program to define logging conditions.
logging.getLogger(__name__).addHandler(logging.NullHandler())
