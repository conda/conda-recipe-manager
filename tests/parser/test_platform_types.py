"""
:Description: Unit tests for the platform types module
"""

from __future__ import annotations

import pytest

from conda_recipe_manager.parser.platform_types import (
    Arch,
    OperatingSystem,
    Platform,
    PlatformAlias,
    get_platforms_by_alias,
    get_platforms_by_arch,
    get_platforms_by_os,
)


@pytest.mark.parametrize(
    "arch,expected",
    [
        ("fake_arch", set()),  # Bad input
        (
            "x86",
            {Platform.LINUX_32, Platform.LINUX_64, Platform.OSX_64, Platform.WIN_32, Platform.WIN_64},
        ),  # String input
        (Arch.X_86, {Platform.LINUX_32, Platform.LINUX_64, Platform.OSX_64, Platform.WIN_32, Platform.WIN_64}),
        (Arch.X_86_64, {Platform.LINUX_64, Platform.OSX_64, Platform.WIN_64}),
        (Arch.ARM_64, {Platform.OSX_ARM_64, Platform.WIN_ARM_64}),
        (Arch.SYS_390, {Platform.LINUX_SYS_390}),
        (Arch.ARM_V6L, {Platform.LINUX_ARM_V6L}),
        (Arch.ARM_V7L, {Platform.LINUX_ARM_V7L}),
        (Arch.PPC_64_LE, {Platform.LINUX_PPC_64_LE}),
        (Arch.AARCH_64, {Platform.LINUX_AARCH_64}),
    ],
)
def test_get_platforms_by_arch(arch: Arch | str, expected: set[Platform]) -> None:
    """
    Tests the construction of a selector parse tree by comparing the debug string representation of the tree.

    :param arch: Target Architecture
    :param expected: Expected value to return
    """
    assert get_platforms_by_arch(arch) == expected


@pytest.mark.parametrize(
    "os,expected",
    [
        ("fake_os", set()),  # Bad input
        ("OSX", {Platform.OSX_64, Platform.OSX_ARM_64}),  # String input
        (
            OperatingSystem.LINUX,
            {
                Platform.LINUX_32,
                Platform.LINUX_64,
                Platform.LINUX_AARCH_64,
                Platform.LINUX_ARM_V6L,
                Platform.LINUX_ARM_V7L,
                Platform.LINUX_PPC_64_LE,
                Platform.LINUX_SYS_390,
            },
        ),
        (OperatingSystem.OSX, {Platform.OSX_64, Platform.OSX_ARM_64}),
        (
            OperatingSystem.UNIX,
            {
                Platform.OSX_64,
                Platform.OSX_ARM_64,
                Platform.LINUX_32,
                Platform.LINUX_64,
                Platform.LINUX_AARCH_64,
                Platform.LINUX_ARM_V6L,
                Platform.LINUX_ARM_V7L,
                Platform.LINUX_PPC_64_LE,
                Platform.LINUX_SYS_390,
            },
        ),
        (OperatingSystem.WINDOWS, {Platform.WIN_32, Platform.WIN_64, Platform.WIN_ARM_64}),
    ],
)
def test_get_platforms_by_os(os: OperatingSystem | str, expected: set[Platform]) -> None:
    """
    Tests the construction of a selector parse tree by comparing the debug string representation of the tree.

    :param os: Target Operating System
    :param expected: Expected value to return
    """
    assert get_platforms_by_os(os) == expected


@pytest.mark.parametrize(
    "alias,expected",
    [
        ("fake_alias", set()),
        ("linux32", {Platform.LINUX_32}),
        ("linux64", {Platform.LINUX_64}),
        ("win32", {Platform.WIN_32}),
        ("win64", {Platform.WIN_64}),
        (PlatformAlias.LINUX_32, {Platform.LINUX_32}),
        (PlatformAlias.LINUX_64, {Platform.LINUX_64}),
        (PlatformAlias.WIN_32, {Platform.WIN_32}),
        (PlatformAlias.WIN_64, {Platform.WIN_64}),
    ],
)
def test_get_platforms_by_alias(alias: PlatformAlias | str, expected: set[Platform]) -> None:
    """
    Tests the construction of a selector parse tree by comparing the debug string representation of the tree.

    :param alias: Target Platform Alias
    :param expected: Expected value to return
    """
    assert get_platforms_by_alias(alias) == expected
