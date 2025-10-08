"""
:Description: Tests the `convert` CLI
"""

from typing import Final

from click.testing import CliRunner

from conda_recipe_manager.commands.convert import convert
from conda_recipe_manager.commands.utils.types import ExitCode
from tests.file_loading import get_test_path, load_file
from tests.smoke_testing import assert_cli_usage


def test_usage() -> None:
    """
    Smoke test that ensures rendering of the help menu
    """
    assert_cli_usage(convert)


def test_only_allow_v0_recipes() -> None:
    """
    Ensures the user gets an error when a V1 recipe is provided to the conversion script.
    """
    runner: Final = CliRunner()
    result: Final = runner.invoke(convert, [str(get_test_path() / "v1_format/v1_simple-recipe.yaml")])
    assert result.exit_code != ExitCode.SUCCESS
    assert result.output.startswith("ILLEGAL OPERATION:")


def test_convert_single_file() -> None:
    """
    Ensures the user can convert a single recipe file.
    """
    runner: Final = CliRunner(mix_stderr=False)
    result: Final = runner.invoke(convert, [str(get_test_path() / "simple-recipe.yaml")])
    # This recipe has warnings
    assert result.exit_code == ExitCode.RENDER_WARNINGS
    # `crm convert` prints an additional newline
    assert result.stdout == load_file("v1_format/v1_simple-recipe.yaml") + "\n"


def test_convert_fail_on_unsupported_jinja() -> None:
    """
    Ensures the user gets an expected error when the `--fail_on_unsupported_jinja` flag is used. Also ensures that the
    same recipe file _doesn't_ produce an error when the flag is NOT used.
    """
    runner: Final = CliRunner(mix_stderr=False)
    # Fail with flag
    result_fail: Final = runner.invoke(
        convert, [str(get_test_path() / "jinja2_statements/pdfium-binaries.yaml"), "--fail-on-unsupported-jinja"]
    )
    assert result_fail.exit_code == ExitCode.PARSE_EXCEPTION

    # Don't fail without flag.
    result_success: Final = runner.invoke(convert, [str(get_test_path() / "jinja2_statements/pdfium-binaries.yaml")])
    assert result_success.exit_code == ExitCode.RENDER_WARNINGS
