"""
:Description: Unit tests for the top-level types module.
"""

from __future__ import annotations

import pytest

from conda_recipe_manager.types import MessageCategory, MessageTable


@pytest.mark.parametrize(
    "messages_and_contents,expected",
    [
        (
            [
                (MessageCategory.WARNING, "Test warning message"),
            ],
            ("0 errors and 1 warning were found."),
        ),
        (
            [
                (MessageCategory.ERROR, "Test error message"),
            ],
            ("1 error and 0 warnings were found."),
        ),
        (
            [
                (MessageCategory.WARNING, "Test warning message"),
                (MessageCategory.ERROR, "Test error message"),
            ],
            ("1 error and 1 warning were found."),
        ),
        (
            [
                (MessageCategory.WARNING, "Test warning message"),
                (MessageCategory.ERROR, "Test error message"),
                (MessageCategory.ERROR, "Another test error message"),
            ],
            ("2 errors and 1 warning were found."),
        ),
        (
            [
                (MessageCategory.WARNING, "Test warning message"),
                (MessageCategory.ERROR, "Test error message"),
                (MessageCategory.EXCEPTION, "Test exception message"),
            ],
            ("1 error and 1 warning were found."),
        ),
        (
            [
                (MessageCategory.EXCEPTION, "Test exception message"),
            ],
            ("0 errors and 0 warnings were found."),
        ),
    ],
)
def test_message_table_add(messages_and_contents: list[tuple[MessageCategory, str]], expected: str) -> None:
    """
    Tests the addition of messages to the message table and checks the expected output of warnings and errors
    contained in the messaging object.

    :param messages_and_contents: Message category and message content
    :param expected: Expected output
    """
    message_table = MessageTable()
    for category, content in messages_and_contents:
        message_table.add_message(category, content)
    assert message_table.get_totals_message() == expected


@pytest.mark.parametrize(
    "messages_and_contents,expected_count",
    [
        (
            [
                (MessageCategory.EXCEPTION, "Test exception message"),
                (MessageCategory.WARNING, "Test warning message"),
                (MessageCategory.ERROR, "Test error message"),
            ],
            {MessageCategory.EXCEPTION: 1, MessageCategory.WARNING: 1, MessageCategory.ERROR: 1},
        ),
        (
            [
                (MessageCategory.WARNING, "Test warning 1"),
                (MessageCategory.WARNING, "Test warning 2"),
                (MessageCategory.ERROR, "Test error 1"),
            ],
            {MessageCategory.EXCEPTION: 0, MessageCategory.WARNING: 2, MessageCategory.ERROR: 1},
        ),
        ([], {MessageCategory.EXCEPTION: 0, MessageCategory.WARNING: 0, MessageCategory.ERROR: 0}),
    ],
)
def test_message_get_count(
    messages_and_contents: list[tuple[MessageCategory, str]], expected_count: dict[MessageCategory, int]
) -> None:
    """
    Tests the addition of messages to the message table and checks the count of warnings and
    errors contained in the messaging object.

    :param messages_and_contents: Message category and message content
    :param count: Expected count
    """
    message_table = MessageTable()

    for category, content in messages_and_contents:
        message_table.add_message(category, content)

    for category, counts in expected_count.items():
        assert message_table.get_message_count(category) == counts


@pytest.mark.parametrize(
    "messages_and_contents,expected_count",
    [
        (
            [
                (MessageCategory.EXCEPTION, "Test exception message"),
                (MessageCategory.WARNING, "Test warning message"),
                (MessageCategory.ERROR, "Test error message"),
            ],
            {MessageCategory.EXCEPTION: 1, MessageCategory.WARNING: 1, MessageCategory.ERROR: 1},
        ),
        (
            [
                (MessageCategory.WARNING, "Test warning 1"),
                (MessageCategory.WARNING, "Test warning 2"),
                (MessageCategory.ERROR, "Test error 1"),
            ],
            {MessageCategory.EXCEPTION: 0, MessageCategory.WARNING: 2, MessageCategory.ERROR: 1},
        ),
        ([], {MessageCategory.EXCEPTION: 0, MessageCategory.WARNING: 0, MessageCategory.ERROR: 0}),
    ],
)
def test_message_table_clear(
    messages_and_contents: list[tuple[MessageCategory, str]], expected_count: dict[MessageCategory, int]
) -> None:
    """
    Tests whether or not the message table properly clears all messages.

    :param messages_and_contents: Message category and message content
    :param count: Expected count
    """
    message_table = MessageTable()
    for category, content in messages_and_contents:
        message_table.add_message(category, content)

    # Check that there are actually warning and error messages being registered and counted before clearing them
    for category, counts in expected_count.items():
        assert message_table.get_message_count(category) == counts

    message_table.clear_messages()
    assert message_table.get_totals_message() == ""
    assert message_table.get_message_count(category) == 0
