"""
:Description: Provides a base class for all dependency scanners to be derived from.
"""

from __future__ import annotations

from abc import ABCMeta, abstractmethod
from typing import NamedTuple

from conda_recipe_manager.parser.dependency import DependencyData, DependencySection, dependency_data_from_str
from conda_recipe_manager.types import MessageTable


class ProjectDependency(NamedTuple):
    """
    A dependency found by scanning a software project's files.

    Not to be confused with the `conda_recipe_manager.parser.dependency.Dependency` type, which can be derived from
    recipe file information.
    """

    data: DependencyData
    type: DependencySection


def new_project_dependency(s: str, t: DependencySection) -> ProjectDependency:
    """
    Convenience constructor for the `ProjectDependency` structure.

    :param s: String containing the dependency name and optional version constraints.
    :param t: Type of dependency. This also correlates with the section this dependency should be put in, in a `conda`
        recipe file.
    :returns: A newly constructed `ProjectDependency` instance.
    """
    return ProjectDependency(
        data=dependency_data_from_str(s),
        type=t,
    )


class BaseDependencyScanner(metaclass=ABCMeta):
    """
    Base class for all Dependency Scanner classes.
    """

    def __init__(self) -> None:
        """
        Constructs a `BaseDependencyScanner`.
        """
        self._msg_tbl = MessageTable()

    @abstractmethod
    def scan(self) -> set[ProjectDependency]:
        """
        Actively scans a project for dependencies. Implementation is dependent on the type of scanner used.

        :returns: A set of unique dependencies found by the scanner.
        """

    def get_message_table(self) -> MessageTable:
        """
        Returns the internal message table.

        :returns: Message table object containing logged messages.
        """
        return self._msg_tbl
