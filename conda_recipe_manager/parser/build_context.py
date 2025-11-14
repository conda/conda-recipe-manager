"""
:Description: Provides an object that can be configured to perform complex selector queries.
"""

from functools import cache
from typing import Final

from conda_recipe_manager.parser.platform_types import (
    ALL_ARCHITECTURES,
    ALL_OPERATING_SYSTEMS,
    ALL_PLATFORM_ALIASES,
    Platform,
    get_platforms_by_alias,
    get_platforms_by_arch,
    get_platforms_by_os,
)
from conda_recipe_manager.types import Primitives


class BuildContext:
    """
    Class that is used to represent the build environment context for selector and Jinja expression evaluation.
    """

    @staticmethod
    @cache  # type: ignore[misc]
    def _get_platform_context(platform: Platform) -> dict[str, Primitives]:
        """
        Constructs the context for the build platform.

        :returns: The constructed context.
        """
        context: Final[dict[str, Primitives]] = {}
        context["build_platform"] = platform.value
        context["target_platform"] = platform.value
        for alias in ALL_PLATFORM_ALIASES:
            if platform in get_platforms_by_alias(alias):
                context[alias.value] = True
            else:
                context[alias.value] = False
        for arch in ALL_ARCHITECTURES:
            if platform in get_platforms_by_arch(arch):
                context[arch.value] = True
            else:
                context[arch.value] = False
        for os in ALL_OPERATING_SYSTEMS:
            if platform in get_platforms_by_os(os):
                context[os.value] = True
            else:
                context[os.value] = False
        return context

    def _get_py_np_context(self) -> dict[str, Primitives]:
        """
        Constructs the context for the Python and NumPy versions.

        :raises ValueError: If the Python or NumPy version is not a valid version.
        :returns: The constructed Python and NumPy context.
        """
        context: Final[dict[str, Primitives]] = {}
        if self._build_env_vars.get("python"):
            if not isinstance(self._build_env_vars["python"], str):
                raise ValueError(f"Python version {self._build_env_vars["python"]} is not a valid version.")
            python_version_int: Final[str] = self._build_env_vars["python"].replace(".", "")
            if not python_version_int.isdigit():
                raise ValueError(f"Python version {self._build_env_vars["python"]} is not a valid version.")
            context["py"] = int(python_version_int)
            context["py3k"] = self._build_env_vars["python"].startswith("3.")
            context["py2k"] = self._build_env_vars["python"].startswith("2.")
            context["py27"] = context["py"] == 27
            context["py34"] = context["py"] == 34
            context["py35"] = context["py"] == 35
            context["py36"] = context["py"] == 36
        if self._build_env_vars.get("numpy"):
            if not isinstance(self._build_env_vars["numpy"], str):
                raise ValueError(f"NumPy version {self._build_env_vars["numpy"]} is not a valid version.")
            numpy_version_int: Final[str] = self._build_env_vars["numpy"].replace(".", "")
            if not numpy_version_int.isdigit():
                raise ValueError(f"NumPy version {self._build_env_vars["numpy"]} is not a valid version.")
            context["np"] = int(numpy_version_int)
        return context

    def _construct_build_context(self) -> dict[str, Primitives]:
        """
        Constructs the context for the build.

        :returns: The constructed build context.
        """
        return {
            **self._build_env_vars,
            **self._get_py_np_context(),
            **BuildContext._get_platform_context(self._platform),
        }

    def __init__(  # pylint: disable=dangerous-default-value
        self, platform: Platform, build_env_vars: dict[str, Primitives] = {}
    ) -> None:
        """
        Constructs a build context given the platform and build environment variables.

        :param platform: Platform to evaluate the context for.
        :param build_env_vars: Build environment variables to evaluate the context for.
        """
        self._platform: Final[Platform] = platform
        self._build_env_vars: Final[dict[str, Primitives]] = build_env_vars
        self._context: Final[dict[str, Primitives]] = self._construct_build_context()

    def get_context(self) -> dict[str, Primitives]:
        """
        Returns the build context.

        :returns: The build context.
        """
        return self._context

    def get_platform(self) -> Platform:
        """
        Returns the build platform.

        :returns: The build platform.
        """
        return self._platform
