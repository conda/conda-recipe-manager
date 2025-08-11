"""
:Description: Contains message-tracking/buffering classes used by the recipe conversion process.
"""

import sys
from enum import StrEnum, auto
from typing import Final


class MessageCategory(StrEnum):
    """
    Categories to classify messages into.
    """

    EXCEPTION = auto()
    ERROR = auto()
    WARNING = auto()


class MessageTable:
    """
    Stores and tags messages that may come up during recipe conversion operations. It is up to `crm convert` to render
    these messages accordingly.

    For all other logging needs, please use the standard Python library logger.
    """

    def __init__(self) -> None:
        """
        Constructs an empty message table
        """
        self._tbl: dict[MessageCategory, list[str]] = {}

    def add_message(self, category: MessageCategory, message: str) -> None:
        """
        Adds a message to the table

        :param category:
        :param message:
        """
        if category not in self._tbl:
            self._tbl[category] = []
        self._tbl[category].append(message)

    def get_messages(self, category: MessageCategory) -> list[str]:
        """
        Returns all the messages stored in a given category

        :param category: Category to target
        :returns: A list containing all the messages stored in a category.
        """
        if category not in self._tbl:
            return []
        return self._tbl[category]

    def get_message_count(self, category: MessageCategory) -> int:
        """
        Returns how many messages are stored in a given category

        :param category: Category to target
        :returns: A list containing all the messages stored in a category.
        """
        if category not in self._tbl:
            return 0
        return len(self._tbl[category])

    def get_totals_message(self) -> str:
        """
        Convenience function that returns a displayable count of the number of warnings and errors contained in the
        messaging object.

        :returns: A message indicating the number of errors and warnings that have been accumulated. If there are none,
            an empty string is returned.
        """
        if not self._tbl:
            return ""

        def _pluralize(n: int, s: str) -> str:
            if n == 1:
                return s
            return f"{s}s"

        num_errors: Final[int] = 0 if MessageCategory.ERROR not in self._tbl else len(self._tbl[MessageCategory.ERROR])
        errors: Final[str] = f"{num_errors} " + _pluralize(num_errors, "error")
        num_warnings: Final[int] = (
            0 if MessageCategory.WARNING not in self._tbl else len(self._tbl[MessageCategory.WARNING])
        )
        warnings: Final[str] = f"{num_warnings} " + _pluralize(num_warnings, "warning")

        return f"{errors} and {warnings} were found."

    def clear_messages(self) -> None:
        """
        Clears-out the current messages.
        """
        self._tbl.clear()

    def print_messages_by_category(self, category: MessageCategory) -> None:
        """
        Convenience function for dumping a series of messages of a certain category

        :param category: Category of messages to print
        :param msg_tbl: `MessageTable` instance containing the messages to print
        """
        msgs: Final[list[str]] = self.get_messages(category)
        for msg in msgs:
            print(f"[{category.upper()}]: {msg}", file=sys.stderr)
