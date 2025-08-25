"""
:Description: Tests for the advanced dependency tools for the `RecipeParser`.
"""

from __future__ import annotations

from typing import Optional

import pytest
from conda.models.match_spec import MatchSpec

from conda_recipe_manager.parser.dependency import Dependency, DependencyConflictMode, DependencySection
from conda_recipe_manager.parser.enums import SelectorConflictMode
from conda_recipe_manager.parser.recipe_parser_deps import RecipeParserDeps
from conda_recipe_manager.parser.selector_parser import SchemaVersion, SelectorParser
from tests.file_loading import load_recipe


@pytest.mark.parametrize(
    "file,dep,dep_mode,sel_mode,expected_return,dep_path,expected_deps,sel_path,expected_sel",
    [
        # Invalid path provided, too long
        (
            "types-toml.yaml",
            Dependency(
                "types-toml",
                "/requirements/run/0/way/more/stuff",
                DependencySection.RUN,
                MatchSpec("openssl >= 1.4.2"),
                None,
            ),
            DependencyConflictMode.REPLACE,
            SelectorConflictMode.REPLACE,
            False,
            "/requirements/run",
            ["python"],
            "/requirements/run/1",
            None,
        ),
        # Invalid path provided, does not end in a digit
        (
            "types-toml.yaml",
            Dependency(
                "types-toml", "/requirements/run/foo", DependencySection.RUN, MatchSpec("openssl >= 1.4.2"), None
            ),
            DependencyConflictMode.REPLACE,
            SelectorConflictMode.REPLACE,
            False,
            "/requirements/run",
            ["python"],
            "/requirements/run/1",
            None,
        ),
        # Invalid path provided, illegal output section
        (
            "cctools-ld64.yaml",
            Dependency(
                "ld64", "/outputs/foo/requirements/run/0", DependencySection.RUN, MatchSpec("openssl >= 1.4.2"), None
            ),
            DependencyConflictMode.REPLACE,
            SelectorConflictMode.REPLACE,
            False,
            "/outputs/1/requirements/host",
            ["llvm-lto-tapi", "libcxx"],
            "/outputs/1/requirements/host/2",
            None,
        ),
        # Invalid path provided, invalid dependency section
        (
            "types-toml.yaml",
            Dependency(
                "types-toml", "/requirements/fake_section/0", DependencySection.RUN, MatchSpec("openssl >= 1.4.2"), None
            ),
            DependencyConflictMode.REPLACE,
            SelectorConflictMode.REPLACE,
            False,
            "/requirements/run",
            ["python"],
            "/requirements/run/1",
            None,
        ),
        # Single-output, default behavior, add a new dependency, no selector
        (
            "types-toml.yaml",
            Dependency("types-toml", "/requirements/run/0", DependencySection.RUN, MatchSpec("openssl >= 1.4.2"), None),
            DependencyConflictMode.REPLACE,
            SelectorConflictMode.REPLACE,
            True,
            "/requirements/run",
            ["python", "openssl >= 1.4.2"],
            "/requirements/run/1",
            None,
        ),
        # Single-output, default behavior, add a new dependency, with a selector
        (
            "types-toml.yaml",
            Dependency(
                "types-toml",
                "/requirements/run/0",
                DependencySection.RUN,
                MatchSpec("openssl >= 1.4.2"),
                SelectorParser("[osx and unix]", SchemaVersion.V0),
            ),
            DependencyConflictMode.REPLACE,
            SelectorConflictMode.REPLACE,
            True,
            "/requirements/run",
            ["python", "openssl >= 1.4.2"],
            "/requirements/run/1",
            "[osx and unix]",
        ),
        # Single-output, duplicate dependency, replace mode, with a selector
        (
            "types-toml.yaml",
            Dependency(
                "types-toml",
                "/requirements/run/0",
                DependencySection.RUN,
                MatchSpec("python >= 3.11"),
                SelectorParser("[osx and unix]", SchemaVersion.V0),
            ),
            DependencyConflictMode.REPLACE,
            SelectorConflictMode.REPLACE,
            True,
            "/requirements/run",
            ["python >= 3.11"],
            "/requirements/run/0",
            "[osx and unix]",
        ),
        # Single-output, duplicate dependency, ignore mode, with a selector
        (
            "types-toml.yaml",
            Dependency(
                "types-toml",
                "/requirements/run/0",
                DependencySection.RUN,
                MatchSpec("python >= 3.11"),
                SelectorParser("[osx and unix]", SchemaVersion.V0),
            ),
            DependencyConflictMode.IGNORE,
            SelectorConflictMode.REPLACE,
            False,
            "/requirements/run",
            ["python"],
            "/requirements/run/1",
            None,
        ),
        # Single-output, duplicate dependency, use-both mode, with a selector
        (
            "types-toml.yaml",
            Dependency(
                "types-toml",
                "/requirements/run/0",
                DependencySection.RUN,
                MatchSpec("python >= 3.11"),
                SelectorParser("[osx and unix]", SchemaVersion.V0),
            ),
            DependencyConflictMode.USE_BOTH,
            SelectorConflictMode.REPLACE,
            True,
            "/requirements/run",
            ["python", "python >= 3.11"],
            "/requirements/run/1",
            "[osx and unix]",
        ),
        # Single-output, duplicate dependency, exact position mode, with a selector
        (
            "types-toml.yaml",
            Dependency(
                "types-toml",
                "/requirements/run/0",
                DependencySection.RUN,
                MatchSpec("python >= 3.11"),
                SelectorParser("[osx and unix]", SchemaVersion.V0),
            ),
            DependencyConflictMode.EXACT_POSITION,
            SelectorConflictMode.REPLACE,
            True,
            "/requirements/run",
            ["python >= 3.11"],
            "/requirements/run/0",
            "[osx and unix]",
        ),
        # Multi-output, default behavior, add a new dependency, no selector
        (
            "cctools-ld64.yaml",
            Dependency(
                "ld64", "/outputs/1/requirements/host/1", DependencySection.HOST, MatchSpec("openssl >= 1.4.2"), None
            ),
            DependencyConflictMode.REPLACE,
            SelectorConflictMode.REPLACE,
            True,
            "/outputs/1/requirements/host",
            ["llvm-lto-tapi", "libcxx", "openssl >= 1.4.2"],
            "/outputs/1/requirements/host/2",
            None,
        ),
        # Multi-output, default behavior, add a new dependency, with a selector
        (
            "cctools-ld64.yaml",
            Dependency(
                "ld64",
                "/outputs/1/requirements/host/1",
                DependencySection.HOST,
                MatchSpec("openssl >= 1.4.2"),
                SelectorParser("[osx and unix]", SchemaVersion.V0),
            ),
            DependencyConflictMode.REPLACE,
            SelectorConflictMode.REPLACE,
            True,
            "/outputs/1/requirements/host",
            ["llvm-lto-tapi", "libcxx", "openssl >= 1.4.2"],
            "/outputs/1/requirements/host/2",
            "[osx and unix]",
        ),
        # Multi-output, duplicate dependency, replace mode, with a selector mode
        (
            "cctools-ld64.yaml",
            Dependency(
                "ld64",
                "/outputs/1/requirements/host/0",
                DependencySection.HOST,
                MatchSpec("libcxx >= 6.9.1"),
                SelectorParser("[unix]", SchemaVersion.V0),
            ),
            DependencyConflictMode.REPLACE,
            SelectorConflictMode.AND,
            True,
            "/outputs/1/requirements/host",
            ["llvm-lto-tapi", "libcxx >= 6.9.1"],
            "/outputs/1/requirements/host/1",
            "[osx and unix]",
        ),
        # Multi-output, duplicate dependency, ignore mode, with a selector mode
        (
            "cctools-ld64.yaml",
            Dependency(
                "ld64",
                "/outputs/1/requirements/host/0",
                DependencySection.HOST,
                MatchSpec("libcxx >= 6.9.1"),
                SelectorParser("[unix]", SchemaVersion.V0),
            ),
            DependencyConflictMode.IGNORE,
            SelectorConflictMode.OR,
            False,
            "/outputs/1/requirements/host",
            ["llvm-lto-tapi", "libcxx"],
            "/outputs/1/requirements/host/1",
            "[osx]",
        ),
        # Multi-output, duplicate dependency, use-both mode, with a selector mode
        (
            "cctools-ld64.yaml",
            Dependency(
                "ld64",
                "/outputs/1/requirements/host/0",
                DependencySection.HOST,
                MatchSpec("libcxx >= 6.9.1"),
                SelectorParser("[unix]", SchemaVersion.V0),
            ),
            DependencyConflictMode.USE_BOTH,
            SelectorConflictMode.AND,
            True,
            "/outputs/1/requirements/host",
            ["llvm-lto-tapi", "libcxx", "libcxx >= 6.9.1"],
            "/outputs/1/requirements/host/2",
            "[unix]",
        ),
        # Multi-output, duplicate dependency, exact position mode, with a selector mode
        (
            "cctools-ld64.yaml",
            Dependency(
                "ld64",
                "/outputs/1/requirements/host/0",
                DependencySection.HOST,
                MatchSpec("libcxx >= 6.9.1"),
                SelectorParser("[unix]", SchemaVersion.V0),
            ),
            DependencyConflictMode.EXACT_POSITION,
            SelectorConflictMode.OR,
            True,
            "/outputs/1/requirements/host",
            ["libcxx >= 6.9.1", "libcxx"],
            "/outputs/1/requirements/host/0",
            "[unix]",
        ),
        # Single-output, add to a non-existent section
        (
            "types-toml.yaml",
            Dependency(
                "types-toml",
                "/requirements/run_constrained/0",
                DependencySection.RUN_CONSTRAINTS,
                MatchSpec("openssl >= 1.4.2"),
                SelectorParser("[osx]", SchemaVersion.V0),
            ),
            DependencyConflictMode.REPLACE,
            SelectorConflictMode.AND,
            True,
            "/requirements/run_constrained",
            ["openssl >= 1.4.2"],
            "/requirements/run_constrained/0",
            "[osx]",
        ),
        # Multi-output, add to a non-existent section
        (
            "cctools-ld64.yaml",
            Dependency(
                "ld64",
                "/outputs/1/requirements/run_constrained/0",
                DependencySection.RUN_CONSTRAINTS,
                MatchSpec("libcxx >= 6.9.1"),
                SelectorParser("[unix]", SchemaVersion.V0),
            ),
            DependencyConflictMode.IGNORE,
            SelectorConflictMode.OR,
            True,
            "/outputs/1/requirements/run_constrained",
            ["libcxx >= 6.9.1"],
            "/outputs/1/requirements/run_constrained/0",
            "[unix]",
        ),
        # Regression: Add a dependency to a recipe containing the dependency: `- numpy {{ numpy }}`
        (
            "h5py.yaml",
            Dependency(
                "h5py",
                "/requirements/host/0",
                DependencySection.RUN_CONSTRAINTS,
                MatchSpec("libcxx >= 6.9.1"),
                SelectorParser("[unix]", SchemaVersion.V0),
            ),
            DependencyConflictMode.IGNORE,
            SelectorConflictMode.OR,
            True,
            "/requirements/host",
            [
                "python",
                "cython >=0.29.15,<4",
                "hdf5 1.12.1",
                "numpy {{ numpy }}",
                "pip",
                "pkgconfig",
                "setuptools",
                "wheel",
                "libcxx >= 6.9.1",
            ],
            "/requirements/host/8",
            "[unix]",
        ),
        # Regression: Add a dependency to an empty section
        (
            "empty_dependency_section.yaml",
            Dependency(
                "test-empty-dependency-section",
                "/requirements/host/0",
                DependencySection.HOST,
                MatchSpec("python"),
                None,
            ),
            DependencyConflictMode.REPLACE,
            SelectorConflictMode.REPLACE,
            True,
            "/requirements/host",
            ["python"],
            "/requirements/host/0",
            None,
        ),
        # TODO Add V1 support
    ],
)
def test_add_dependency(
    file: str,
    dep: Dependency,
    dep_mode: DependencyConflictMode,
    sel_mode: SelectorConflictMode,
    expected_return: bool,
    dep_path: str,
    expected_deps: list[str],
    sel_path: str,
    expected_sel: Optional[str],
) -> None:
    """
    Tests the ability to add a `Dependency` object to a recipe.

    :param file: File to test against
    :param dep: Dependency to add
    :param dep_mode: Target Dependency conflict mode
    :param sel_mode: Target Selector conflict mode
    :param expected_return: Expected return value
    :param dep_path: Dependency section path to use in post-op validation
    :param expected_deps: List of dependencies that should be found in the altered dependency path
    :param sel_path: Selector path to use in post-op validation
    :param expected_deps: Expected Selector value on the new dependency. If no selector was added, set this to `NONE`.
    """
    parser = load_recipe(file, RecipeParserDeps)
    assert parser.add_dependency(dep, dep_mode=dep_mode, sel_mode=sel_mode) == expected_return

    assert parser.get_value(dep_path) == expected_deps
    # Branch to perform different checks, depending if a selector is expected or not.
    if expected_sel is None:
        with pytest.raises(KeyError):
            parser.get_selector_at_path(sel_path)
    else:
        assert parser.get_selector_at_path(sel_path) == expected_sel


@pytest.mark.parametrize(
    "file,dep,expected_return,dep_path,expected_deps",
    [
        # Single-output, dependency exists
        (
            "types-toml.yaml",
            Dependency("types-toml", "/requirements/run/0", DependencySection.RUN, MatchSpec("python"), None),
            True,
            "/requirements/run",
            None,
        ),
        # Single-output, dependency does not exist
        (
            "types-toml.yaml",
            Dependency("types-toml", "/requirements/run/1", DependencySection.RUN, MatchSpec("openssl >= 1.4.2"), None),
            False,
            "/requirements/run",
            ["python"],
        ),
        # Multi-output, dependency exists
        (
            "cctools-ld64.yaml",
            Dependency("ld64", "/outputs/1/requirements/host/1", DependencySection.HOST, MatchSpec("libcxx"), None),
            True,
            "/outputs/1/requirements/host",
            ["llvm-lto-tapi"],
        ),
        # Multi-output, dependency does not exist
        (
            "cctools-ld64.yaml",
            Dependency(
                "ld64", "/outputs/1/requirements/host/2", DependencySection.HOST, MatchSpec("openssl >= 1.4.2"), None
            ),
            False,
            "/outputs/1/requirements/host",
            ["llvm-lto-tapi", "libcxx"],
        ),
        # TODO Add V1 support
    ],
)
def test_remove_dependency(
    file: str,
    dep: Dependency,
    expected_return: bool,
    dep_path: str,
    expected_deps: list[str] | str,
) -> None:
    """
    Tests the ability to remove a `Dependency` object to a recipe.

    :param file: File to test against
    :param dep: Dependency to remove
    :param expected_return: Expected return value
    :param dep_path: Dependency section path to use in post-op validation
    :param expected_deps: List of dependencies that should be found in the altered dependency path
    """
    parser = load_recipe(file, RecipeParserDeps)
    assert parser.remove_dependency(dep) == expected_return
    assert parser.get_value(dep_path) == expected_deps
