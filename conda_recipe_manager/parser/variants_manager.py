"""
:Description: Provides a class that manages the variants of a recipe, given a list of CBC files.
"""

from __future__ import annotations

from typing import Final, cast

from conda_recipe_manager.parser.build_context import BuildContext
from conda_recipe_manager.parser.cbc_parser import CbcParser, GeneratedVariantsType
from conda_recipe_manager.parser.recipe_parser_deps import RecipeParserDeps
from conda_recipe_manager.parser.recipe_reader_deps import RecipeReaderDeps
from conda_recipe_manager.parser.recipe_variant import RecipeVariant
from conda_recipe_manager.types import PRIMITIVES_TUPLE


class VariantsManager:
    """
    Class that manages the variants of a recipe, given a list of CBC files.
    """

    def __init__(self, recipe_str: str, cbc_strs: list[str], build_context: BuildContext):
        """
        Initializes the VariantsManager.

        :param recipe_str: String representation of the recipe.
        :param cbc_strs: List of string representations of the CBC files.
        :param build_context: Build context to generate the variants for.
        """
        self._build_context = build_context
        self._cbc_parsers: list[CbcParser] = [CbcParser(cbc_str) for cbc_str in cbc_strs]
        variants: Final[GeneratedVariantsType] = CbcParser.generate_variants(self._cbc_parsers, build_context)
        self._base_recipe: RecipeParserDeps = RecipeParserDeps(recipe_str)
        self._recipe_variants: list[RecipeVariant] = []
        known_hashes: set[str] = set()
        for full_var in variants:
            var = {key: value for key, value in full_var.items() if isinstance(value, PRIMITIVES_TUPLE)}
            post_cbc_build_context: BuildContext = BuildContext(
                build_context.get_platform(), {**build_context.get_context(), **var}
            )
            recipe_var = RecipeVariant(recipe_str, post_cbc_build_context)
            if recipe_var.get_value("/build/skip", default=None) is True:
                continue
            recipe_var_hash: str = recipe_var.calc_sha256()
            if recipe_var_hash in known_hashes:
                continue
            known_hashes.add(recipe_var_hash)
            self._recipe_variants.append(recipe_var)

    def get_base_recipe(self) -> RecipeParserDeps:
        """
        Returns the base recipe as a RecipeParserDeps object.
        """
        return self._base_recipe

    def get_recipe_variants(self) -> list[RecipeReaderDeps]:
        """
        Returns the recipe variants as RecipeReaderDeps objects.
        """
        return cast(list[RecipeReaderDeps], self._recipe_variants)

    def get_cbc_parsers(self) -> list[CbcParser]:
        """
        Returns the CBC parsers.
        """
        return self._cbc_parsers
