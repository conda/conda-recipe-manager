"""
:Description: Provides a class that manages the variants of a recipe, given a list of CBC files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final, cast

from conda_recipe_manager.parser.build_context import BuildContext
from conda_recipe_manager.parser.cbc_parser import CbcParser, GeneratedVariantsType
from conda_recipe_manager.parser.recipe_parser_deps import RecipeParserDeps
from conda_recipe_manager.parser.recipe_reader_deps import RecipeReaderDeps
from conda_recipe_manager.types import PRIMITIVES_TUPLE


class VariantsManager:
    """
    Class that manages the variants of a recipe, given a list of CBC files.
    """

    def __init__(self, recipe_path: Path, cbc_paths: list[Path], build_context: BuildContext):
        """
        Initializes the VariantsManager.

        :param recipe_path: Path to the recipe file.
        :param cbc_paths: List of paths to the CBC files.
        :param build_context: Build context to generate the variants for.
        """
        self._build_context = build_context
        cbc_parsers: list[CbcParser] = [CbcParser(cbc_path.read_text()) for cbc_path in cbc_paths]
        self._variants: Final[GeneratedVariantsType] = CbcParser.generate_variants(cbc_parsers, build_context)
        self._base_recipe: RecipeParserDeps = RecipeParserDeps(recipe_path.read_text())
        recipe_variants_first_pass: list[RecipeParserDeps] = [
            RecipeParserDeps(recipe_path.read_text()) for _ in self._variants
        ]
        self._recipe_variants: list[RecipeParserDeps] = []
        known_hashes: set[str] = set()
        for full_var, recipe_var in zip(self._variants, recipe_variants_first_pass):
            var = {key: value for key, value in full_var.items() if isinstance(value, PRIMITIVES_TUPLE)}
            post_cbc_build_context: BuildContext = BuildContext(
                build_context.get_platform(), {**build_context.get_context(), **var}
            )
            recipe_var.filter_by_selectors(post_cbc_build_context)
            recipe_var.evaluate_jinja_expressions(post_cbc_build_context)
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
