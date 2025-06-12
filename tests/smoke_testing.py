"""
:Description: Collection of smoke test utilities.
"""

from click import Command
from click.testing import CliRunner


def assert_cli_usage(command: Command) -> None:
    """
    Helper smoke test that ensures rendering of the help menu. Called by other CLI tests.

    :param command: The `click` CLI `Command`.
    """
    runner = CliRunner()
    # No commands are provided
    result = runner.invoke(command, [])
    assert result.exit_code != 0
    assert result.output.startswith("Usage:")
    # Help is specified
    result = runner.invoke(command, ["--help"])
    assert result.exit_code == 0
    assert result.output.startswith("Usage:")
