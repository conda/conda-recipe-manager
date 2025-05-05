"""
:Description: Provides unit tests for the `PyProjectDependencyScanner` class.
"""

import pytest
from conda.models.match_spec import MatchSpec

from conda_recipe_manager.parser.dependency import DependencySection
from conda_recipe_manager.scanner.dependency.base_dep_scanner import ProjectDependency
from conda_recipe_manager.scanner.dependency.pyproject_dep_scanner import PyProjectDependencyScanner
from conda_recipe_manager.types import MessageCategory
from tests.file_loading import get_test_path


@pytest.mark.parametrize(
    "project_fn,expected",
    [
        (
            "crm_mock_pyproject.toml",
            {
                ProjectDependency(MatchSpec("click"), DependencySection.RUN),
                ProjectDependency(MatchSpec("jinja2"), DependencySection.RUN),
                ProjectDependency(MatchSpec("pyyaml"), DependencySection.RUN),
                ProjectDependency(MatchSpec("jsonschema"), DependencySection.RUN),
                ProjectDependency(MatchSpec("requests"), DependencySection.RUN),
                ProjectDependency(MatchSpec("gitpython"), DependencySection.RUN),
                ProjectDependency(MatchSpec("networkx"), DependencySection.RUN),
                ProjectDependency(MatchSpec("matplotlib"), DependencySection.RUN),
                ProjectDependency(MatchSpec("pygraphviz"), DependencySection.RUN),
                # Optional dependencies
                ProjectDependency(MatchSpec("pytest"), DependencySection.RUN_CONSTRAINTS),
                ProjectDependency(MatchSpec("conda-build"), DependencySection.RUN_CONSTRAINTS),
            },
        ),
        (
            "crm_mock_pyproject_version_constraints.toml",
            {
                ProjectDependency(MatchSpec("click >= 1.2"), DependencySection.RUN),
                ProjectDependency(MatchSpec("jinja2"), DependencySection.RUN),
                ProjectDependency(MatchSpec("pyyaml"), DependencySection.RUN),
                ProjectDependency(MatchSpec("jsonschema"), DependencySection.RUN),
                ProjectDependency(MatchSpec("requests >= 2.8.1, == 2.8.*"), DependencySection.RUN),
                ProjectDependency(MatchSpec("gitpython"), DependencySection.RUN),
                ProjectDependency(MatchSpec("networkx"), DependencySection.RUN),
                ProjectDependency(MatchSpec("matplotlib"), DependencySection.RUN),
                ProjectDependency(MatchSpec("pygraphviz"), DependencySection.RUN),
                # Optional dependencies
                ProjectDependency(MatchSpec("pytest ~= 8.1"), DependencySection.RUN_CONSTRAINTS),
                ProjectDependency(MatchSpec("conda-build"), DependencySection.RUN_CONSTRAINTS),
            },
        ),
        (
            "crm_mock_pyproject_only_deps.toml",
            {
                ProjectDependency(MatchSpec("click"), DependencySection.RUN),
                ProjectDependency(MatchSpec("jinja2"), DependencySection.RUN),
                ProjectDependency(MatchSpec("pyyaml"), DependencySection.RUN),
                ProjectDependency(MatchSpec("jsonschema"), DependencySection.RUN),
                ProjectDependency(MatchSpec("requests"), DependencySection.RUN),
                ProjectDependency(MatchSpec("gitpython"), DependencySection.RUN),
                ProjectDependency(MatchSpec("networkx"), DependencySection.RUN),
                ProjectDependency(MatchSpec("matplotlib"), DependencySection.RUN),
                ProjectDependency(MatchSpec("pygraphviz"), DependencySection.RUN),
            },
        ),
        (
            "crm_mock_pyproject_only_optional.toml",
            {
                ProjectDependency(MatchSpec("pytest"), DependencySection.RUN_CONSTRAINTS),
                ProjectDependency(MatchSpec("conda-build"), DependencySection.RUN_CONSTRAINTS),
            },
        ),
    ],
)
def test_scan(project_fn: str, expected: set[ProjectDependency]) -> None:
    """
    Tests scanning for Python dependencies with a mocked-out Python project.

    :param project_fn: Name of the dummy `pyproject.toml` file to use.
    :param expected: Expected value
    """
    scanner = PyProjectDependencyScanner(get_test_path() / "pyproject_toml", project_fn)
    assert scanner.scan() == expected


def test_scan_missing_pyproject() -> None:
    """
    Tests that the scanner fails gracefully if a `pyproject.toml` file could not be found
    """
    scanner = PyProjectDependencyScanner(get_test_path() / "pyproject_toml", "the_limit_dne.toml")
    assert scanner.scan() == set()
    assert scanner.get_message_table().get_messages(MessageCategory.EXCEPTION) == [
        "`the_limit_dne.toml` file not found."
    ]


def test_scan_corrupt_pyproject() -> None:
    """
    Tests that the scanner fails gracefully if the `pyproject.toml` file is corrupt.
    """
    scanner = PyProjectDependencyScanner(get_test_path() / "pyproject_toml", "corrupt_pyproject.toml")
    assert scanner.scan() == set()
    assert scanner.get_message_table().get_messages(MessageCategory.EXCEPTION) == [
        "Could not parse `corrupt_pyproject.toml` file."
    ]


def test_scan_missing_project_pyproject() -> None:
    """
    Tests that the scanner fails gracefully if the `pyproject.toml` file is missing a `project` section.
    """
    scanner = PyProjectDependencyScanner(get_test_path() / "pyproject_toml", "no_project_pyproject.toml")
    assert scanner.scan() == set()
    assert scanner.get_message_table().get_messages(MessageCategory.ERROR) == [
        "`no_project_pyproject.toml` file is missing a `project` section."
    ]
