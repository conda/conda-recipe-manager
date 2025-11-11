"""
:Description: Unit tests for the SelectorParser class
"""

from __future__ import annotations

import pytest

from conda_recipe_manager.parser.enums import SchemaVersion
from conda_recipe_manager.parser.platform_types import ALL_PLATFORMS, Platform
from conda_recipe_manager.parser.selector_parser import SelectorParser
from conda_recipe_manager.parser.selector_query import SelectorQuery


@pytest.mark.parametrize(
    "selector,schema,expected",
    [
        ("", SchemaVersion.V0, "Schema: V0 | Tree: None"),
        ("[]", SchemaVersion.V0, "Schema: V0 | Tree: None"),
        ("osx", SchemaVersion.V0, "Schema: V0 | Tree: osx"),
        ("[osx]", SchemaVersion.V0, "Schema: V0 | Tree: osx"),
        ("[not osx]", SchemaVersion.V0, "Schema: V0 | Tree: not L osx"),
        ("[not osx and unix]", SchemaVersion.V0, "Schema: V0 | Tree: and L not L osx R unix"),
        ("[osx and not unix]", SchemaVersion.V0, "Schema: V0 | Tree: and L osx R not L unix"),
        ("[osx and py37]", SchemaVersion.V0, "Schema: V0 | Tree: and L osx R py37"),
    ],
)
def test_selector_parser_construction(selector: str, schema: SchemaVersion, expected: str) -> None:
    """
    Tests the construction of a selector parse tree by comparing the debug string representation of the tree.

    :param selector: Selector string to parse
    :param schema: Target schema version
    :param expected: Expected value to return
    """
    parser = SelectorParser(selector, schema)
    assert str(parser) == expected
    assert not parser.is_modified()


@pytest.mark.parametrize(
    "selector0,selector1,expected",
    [
        (SelectorParser("[osx]", SchemaVersion.V0), SelectorParser("[osx]", SchemaVersion.V0), True),
        (SelectorParser("[osx]", SchemaVersion.V0), "[osx]", False),
        # TODO: This test case will need to be updated when V1 support for selectors is added.
        (SelectorParser("[osx]", SchemaVersion.V0), SelectorParser("[osx]", SchemaVersion.V1), False),
        (SelectorParser("[osx]", SchemaVersion.V0), SelectorParser("[unix]", SchemaVersion.V0), False),
        (SelectorParser("[unix or osx]", SchemaVersion.V0), SelectorParser("[unix or osx]", SchemaVersion.V0), True),
        (SelectorParser("[unix or osx]", SchemaVersion.V0), SelectorParser("[osx or unix]", SchemaVersion.V0), False),
    ],
)
def test_selector_eq(selector0: SelectorParser, selector1: object, expected: bool) -> None:
    """
    Tests checking for selector equivalency.

    :param selector0: LHS selector
    :param selector1: RHS selector
    :param expected: Expected value to return
    """
    assert (selector0 == selector1) == expected


@pytest.mark.parametrize(
    "selector,schema,expected",
    [
        ("", SchemaVersion.V0, ALL_PLATFORMS),
        ("[]", SchemaVersion.V0, ALL_PLATFORMS),
        ("osx", SchemaVersion.V0, {Platform.OSX_64, Platform.OSX_ARM_64}),
        ("[osx]", SchemaVersion.V0, {Platform.OSX_64, Platform.OSX_ARM_64}),
        (
            "[not osx]",
            SchemaVersion.V0,
            {
                Platform.LINUX_32,
                Platform.LINUX_64,
                Platform.LINUX_AARCH_64,
                Platform.LINUX_ARM_V6L,
                Platform.LINUX_ARM_V7L,
                Platform.LINUX_PPC_64_LE,
                Platform.LINUX_SYS_390,
                Platform.WIN_32,
                Platform.WIN_64,
                Platform.WIN_ARM_64,
            },
        ),
        (
            "[not osx and unix]",
            SchemaVersion.V0,
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
        (
            "[not osx or unix]",
            SchemaVersion.V0,
            {
                Platform.LINUX_32,
                Platform.LINUX_64,
                Platform.LINUX_AARCH_64,
                Platform.LINUX_ARM_V6L,
                Platform.LINUX_ARM_V7L,
                Platform.LINUX_PPC_64_LE,
                Platform.LINUX_SYS_390,
                # OSX is included in the UNIX category, therefore it is included
                Platform.OSX_64,
                Platform.OSX_ARM_64,
                Platform.WIN_32,
                Platform.WIN_64,
                Platform.WIN_ARM_64,
            },
        ),
        ("[osx and not unix]", SchemaVersion.V0, set()),
        # TODO FIX: Python versions should have no effect on which Platforms are included
        # ("[osx and py37]", SchemaVersion.V0, {Platform.OSX_64, Platform.OSX_ARM_64}),
        ("[osx or py37]", SchemaVersion.V0, {Platform.OSX_64, Platform.OSX_ARM_64}),
        ("[win and not x86]", SchemaVersion.V0, {Platform.WIN_ARM_64}),
        (
            "[ppc64le or win]",
            SchemaVersion.V0,
            {Platform.WIN_32, Platform.WIN_64, Platform.WIN_ARM_64, Platform.LINUX_PPC_64_LE},
        ),
        ("[linux and armv7l]", SchemaVersion.V0, {Platform.LINUX_ARM_V7L}),
        (
            "[win or linux and armv6l]",
            SchemaVersion.V0,
            {Platform.LINUX_ARM_V6L, Platform.WIN_32, Platform.WIN_64, Platform.WIN_ARM_64},
        ),
    ],
)
def test_get_selected_platforms(selector: str, schema: SchemaVersion, expected: set[Platform]) -> None:
    """
    Validates the set of platforms that apply to a selector.

    :param selector: Selector string to parse
    :param schema: Target schema version
    :param expected: Expected value to return
    """
    parser = SelectorParser(selector, schema)
    for platform in expected:
        assert parser.does_selector_apply(SelectorQuery(platform=platform))
    for platform in set(Platform) - expected:
        assert not parser.does_selector_apply(SelectorQuery(platform=platform))
    assert not parser.is_modified()


@pytest.mark.parametrize(
    "selector,schema,query,expected",
    [
        ("", SchemaVersion.V0, SelectorQuery(), True),
        (
            "[ANACONDA_ROCKET_ENABLE_PY314]",
            SchemaVersion.V0,
            SelectorQuery(platform=Platform.LINUX_64, build_env_vars={"ANACONDA_ROCKET_ENABLE_PY314": 1}),
            True,
        ),
        (
            "[osx and ANACONDA_ROCKET_ENABLE_PY314]",
            SchemaVersion.V0,
            SelectorQuery(platform=Platform.OSX_64, build_env_vars={"ANACONDA_ROCKET_ENABLE_PY314": 1}),
            True,
        ),
        (
            "[osx and ANACONDA_ROCKET_ENABLE_PY314]",
            SchemaVersion.V0,
            SelectorQuery(platform=Platform.OSX_ARM_64, build_env_vars={"ANACONDA_ROCKET_ENABLE_PY314": 1}),
            True,
        ),
        (
            "[osx and ANACONDA_ROCKET_ENABLE_PY314]",
            SchemaVersion.V0,
            SelectorQuery(platform=Platform.OSX_ARM_64),
            False,
        ),
        (
            "[osx and ANACONDA_ROCKET_ENABLE_PY314]",
            SchemaVersion.V0,
            SelectorQuery(platform=Platform.WIN_64, build_env_vars={"ANACONDA_ROCKET_ENABLE_PY314": 1}),
            False,
        ),
        ("[osx]", SchemaVersion.V0, SelectorQuery(platform=Platform.OSX_64), True),
        ("[osx]", SchemaVersion.V0, SelectorQuery(platform=Platform.WIN_64), False),
        ("[not osx]", SchemaVersion.V0, SelectorQuery(platform=Platform.WIN_64), True),
        ("[not osx]", SchemaVersion.V0, SelectorQuery(platform=Platform.OSX_64), False),
        ("[osx and not unix]", SchemaVersion.V0, SelectorQuery(platform=Platform.LINUX_PPC_64_LE), False),
        ("[osx or not unix]", SchemaVersion.V0, SelectorQuery(platform=Platform.WIN_ARM_64), True),
        ("[osx and arm64 or win]", SchemaVersion.V0, SelectorQuery(platform=Platform.OSX_ARM_64), True),
        ("[osx and arm64 or win]", SchemaVersion.V0, SelectorQuery(platform=Platform.WIN_64), True),
        ("[osx and arm64 or win]", SchemaVersion.V0, SelectorQuery(platform=Platform.OSX_64), False),
        ("[osx and (arm64 or win)]", SchemaVersion.V0, SelectorQuery(platform=Platform.WIN_64), False),
        ("[win or linux and armv6l]", SchemaVersion.V0, SelectorQuery(platform=Platform.LINUX_ARM_V6L), True),
        ("[win or linux and armv6l]", SchemaVersion.V0, SelectorQuery(platform=Platform.WIN_64), True),
        ("[win or (linux and armv6l)]", SchemaVersion.V0, SelectorQuery(platform=Platform.LINUX_ARM_V6L), True),
        ("[win or (linux and armv6l)]", SchemaVersion.V0, SelectorQuery(platform=Platform.WIN_64), True),
        ("[(win or linux) and armv6l]", SchemaVersion.V0, SelectorQuery(platform=Platform.WIN_64), False),
        ("[(win or linux) and armv6l]", SchemaVersion.V0, SelectorQuery(platform=Platform.LINUX_ARM_V6L), True),
    ],
)
def test_does_selector_apply(selector: str, schema: SchemaVersion, query: SelectorQuery, expected: bool) -> None:
    """
    Validates the question: does a selector apply to the current environment query?

    :param selector: Selector string to parse
    :param schema: Target schema version
    :param query: Target selector query
    :param expected: Expected value to return
    """
    parser = SelectorParser(selector, schema)
    assert parser.does_selector_apply(query) == expected


@pytest.mark.parametrize(
    "selector,expected",
    [
        (SelectorParser("[osx]", SchemaVersion.V0), "[osx]"),
        (SelectorParser("[ osx ]", SchemaVersion.V0), "[osx]"),
        (SelectorParser("[not osx]", SchemaVersion.V0), "[not osx]"),
        (SelectorParser("[unix or osx]", SchemaVersion.V0), "[unix or osx]"),
        (SelectorParser("[ unix or osx ]", SchemaVersion.V0), "[unix or osx]"),
        (SelectorParser("[osx and not unix]", SchemaVersion.V0), "[osx and not unix]"),
        (SelectorParser("[osx or not unix]", SchemaVersion.V0), "[osx or not unix]"),
        # TODO Add V1 support
    ],
)
def test_selector_render(selector: SelectorParser, expected: str) -> None:
    """
    Tests selector rendering.

    :param selector: Target selector
    :param expected: Expected value to return
    """
    assert selector.render() == expected
