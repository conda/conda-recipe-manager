"""
:Description: Module that allows the reading, parsing, and editing of Conda recipe files and related infrastructure.
"""

import logging

# Default to emitting no logs. It is up to the client program to define logging conditions.
logging.getLogger(__name__).addHandler(logging.NullHandler())
