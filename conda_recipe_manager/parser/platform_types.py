"""
:Description: Provides enumerations and look-up tables for conda-recognized platforms.

Resources:
  - https://github.com/conda/conda-build/blob/6b222c76ac0ba3b9f2efaf2f807ed335a3b46c00/conda_build/cli/main_convert.py
  - https://github.com/conda/conda-build/blob/6b222c76ac0ba3b9f2efaf2f807ed335a3b46c00/tests/test_metadata.py#L485
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class OperatingSystem(StrEnum):
    """
    Operating System enumeration. This is a broad (and sometimes inaccurate) qualifier supported by the recipe format.
    """

    LINUX = "linux"
    OSX = "osx"
    UNIX = "unix"  # As far as recipes are concerned, this is "posix". We don't support System V.
    WINDOWS = "win"


# Set of all Operating System options
ALL_OPERATING_SYSTEMS: Final[set[OperatingSystem]] = set(OperatingSystem)


class Arch(StrEnum):
    """
    System Architecture enumeration, referring to the hardware/CPU/ISA of the target device.
    """

    SYS_390 = "s390x"
    X_86 = "x86"
    X_86_64 = "x86_64"
    AARCH_64 = "aarch64"
    ARM_64 = "arm64"
    ARM_V6L = "armv6l"
    ARM_V7L = "armv7l"
    PPC_64_LE = "ppc64le"


# Set of all Architecture options
ALL_ARCHITECTURES: Final[set[Arch]] = set(Arch)


class PlatformAlias(StrEnum):
    """
    Platform alias enumeration. These are selectors that can reference a platform directly.
    """

    LINUX_32 = "linux32"
    LINUX_64 = "linux64"
    WIN_32 = "win32"
    WIN_64 = "win64"


# Set of all PlatformAlias options
ALL_PLATFORM_ALIASES: Final[set[PlatformAlias]] = set(PlatformAlias)


class Platform(StrEnum):
    """
    Platform enumeration. A "platform" is the most specific qualifier recognized by the recipe format.
    """

    # Linux
    LINUX_32 = "linux-32"
    LINUX_64 = "linux-64"
    LINUX_AARCH_64 = "linux-aarch64"
    LINUX_ARM_V6L = "linux-armv6l"
    LINUX_ARM_V7L = "linux-armv7l"
    LINUX_PPC_64_LE = "linux-ppc64le"
    LINUX_SYS_390 = "linux-s390x"
    # OSX
    OSX_64 = "osx-64"
    OSX_ARM_64 = "osx-arm64"
    # Windows
    WIN_32 = "win-32"
    WIN_64 = "win-64"
    WIN_ARM_64 = "win-arm64"
    # TODO add more platforms
    # ("emscripten-wasm32", {"unix", "emscripten", "wasm32"}),
    # ("wasi-wasm32", {"wasi", "wasm32"}),
    # ("freebsd-64", {"freebsd", "x86", "x86_64"}),
    # ("zos-z", {"zos", "z"}),


# Set of all Platform options
ALL_PLATFORMS: Final[set[Platform]] = set(Platform)

# No-arch indicates that there is no specific target platform.
NO_ARCH: Final[str] = "noarch"

# Type alias for any enumeration that could represent a set of target build platforms
PlatformQualifiers = Arch | OperatingSystem | Platform


def get_platforms_by_arch(arch: Arch | str) -> set[Platform]:
    """
    Given an architecture, return the list of supported build platforms.

    :param arch: Target architecture
    :returns: Set of supported platforms for that architecture. An empty set is returned if no matching architecture
        is found.
    """
    if isinstance(arch, str):
        arch_sanitized: Final[str] = arch.strip().lower()
        if not arch_sanitized in ALL_ARCHITECTURES:
            return set()
        arch = Arch(arch_sanitized)

    x86_64_set: Final[set[Platform]] = {Platform.LINUX_64, Platform.OSX_64, Platform.WIN_64}

    match arch:
        case Arch.SYS_390:
            return {Platform.LINUX_SYS_390}
        case Arch.X_86:
            return {Platform.LINUX_32, Platform.WIN_32} | x86_64_set
        case Arch.X_86_64:
            return x86_64_set
        case Arch.AARCH_64:
            return {Platform.LINUX_AARCH_64}
        case Arch.ARM_64:
            return {Platform.OSX_ARM_64, Platform.WIN_ARM_64}
        case Arch.ARM_V6L:
            return {Platform.LINUX_ARM_V6L}
        case Arch.ARM_V7L:
            return {Platform.LINUX_ARM_V7L}
        case Arch.PPC_64_LE:
            return {Platform.LINUX_PPC_64_LE}


def get_platforms_by_os(os: OperatingSystem | str) -> set[Platform]:
    """
    Given an Operating System, return the list of supported build platforms.

    :param os: Target operating system
    :returns: Set of supported platforms for that OS. An empty set is returned if no matching OS is found.
    """
    if isinstance(os, str):
        os_sanitized: Final[str] = os.strip().lower()
        if not os_sanitized in ALL_OPERATING_SYSTEMS:
            return set()
        os = OperatingSystem(os_sanitized)

    osx_set: Final[set[Platform]] = {
        Platform.OSX_64,
        Platform.OSX_ARM_64,
    }
    linux_set: Final[set[Platform]] = {
        Platform.LINUX_32,
        Platform.LINUX_64,
        Platform.LINUX_AARCH_64,
        Platform.LINUX_ARM_V6L,
        Platform.LINUX_ARM_V7L,
        Platform.LINUX_PPC_64_LE,
        Platform.LINUX_SYS_390,
    }

    match os:
        case OperatingSystem.LINUX:
            return linux_set
        case OperatingSystem.OSX:
            return osx_set
        case OperatingSystem.UNIX:
            return osx_set | linux_set
        case OperatingSystem.WINDOWS:
            return {
                Platform.WIN_32,
                Platform.WIN_64,
                Platform.WIN_ARM_64,
            }


def get_platforms_by_alias(alias: PlatformAlias | str) -> set[Platform]:
    """
    Given a platform alias, return the list of supported build platforms.

    :param alias: Target platform alias
    :returns: Set of supported platforms for that alias. An empty set is returned if no matching alias is found.
    """
    if isinstance(alias, str):
        alias_sanitized: Final[str] = alias.strip().lower()
        if not alias_sanitized in ALL_PLATFORM_ALIASES:
            return set()
        alias = PlatformAlias(alias_sanitized)

    match alias:
        case PlatformAlias.LINUX_32:
            return {Platform.LINUX_32}
        case PlatformAlias.LINUX_64:
            return {Platform.LINUX_64}
        case PlatformAlias.WIN_32:
            return {Platform.WIN_32}
        case PlatformAlias.WIN_64:
            return {Platform.WIN_64}
