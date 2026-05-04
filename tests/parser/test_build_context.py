"""
:Description: Validates functionality of the `BuildContext` member functions.
"""

from typing import Optional

import pytest

from conda_recipe_manager.parser.build_context import BuildContext
from conda_recipe_manager.parser.exceptions import BuildContextVersionException
from conda_recipe_manager.parser.platform_types import Platform
from conda_recipe_manager.types import Primitives

# TODO Future: This class is missing tests for most functions!


@pytest.mark.parametrize(
    ["platform", "build_env_vars"],
    [
        (Platform.LINUX_64, {"python": 3.11}),
    ],
)
def test_build_context_raises_on_construction(platform: Platform, build_env_vars: dict[str, Primitives]) -> None:
    """
    Ensures that a `BuildContext` instance throws on construction if it would be in an invalid state.

    :param platform: Conda-recognized `Platform` to construct with.
    :param build_env_vars: Table of build environment variables to construct with.
    """
    with pytest.raises(BuildContextVersionException):
        BuildContext(platform=platform, build_env_vars=build_env_vars)


@pytest.mark.parametrize(
    ["build_context", "expected"],
    [
        (BuildContext(platform=Platform.LINUX_64), Platform.LINUX_64),
        (BuildContext(platform=Platform.WIN_ARM_64), Platform.WIN_ARM_64),
        (BuildContext(platform=Platform.OSX_64), Platform.OSX_64),
    ],
)
def test_get_platform(build_context: BuildContext, expected: Platform) -> None:
    """
    Ensures a `BuildContext` instance correctly returns the target platform.

    :param build_context: Target `BuildContext` instance to test with.
    :param expected: Expected value to be returned.
    """
    assert build_context.get_platform() == expected


@pytest.mark.parametrize(
    ["build_context", "expected"],
    [
        (BuildContext(platform=Platform.LINUX_64), None),
        (BuildContext(platform=Platform.LINUX_64, build_env_vars={}), None),
        # Usually the `python` variable is provided by the CBC file.
        (BuildContext(platform=Platform.LINUX_64, build_env_vars={"python": "3.11"}), 311),
    ],
)
def test_get_build_str(build_context: BuildContext, expected: Optional[int]) -> None:
    """
    Ensures a `BuildContext` instance correctly returns the associated Python version, if available.

    :param build_context: Target `BuildContext` instance to test with.
    :param expected: Expected value to be returned.
    """
    assert build_context.get_python_version_as_int() == expected
