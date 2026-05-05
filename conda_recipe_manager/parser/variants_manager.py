"""
:Description: Provides a class that manages the variants of a recipe, given a list of CBC files.
"""

from __future__ import annotations

import json
from typing import Final, cast

from conda_recipe_manager.parser.build_context import BuildContext
from conda_recipe_manager.parser.cbc_reader import CbcReader
from conda_recipe_manager.parser.recipe_reader_deps import RecipeReaderDeps
from conda_recipe_manager.parser.recipe_variant import RecipeVariant
from conda_recipe_manager.parser.types import GeneratedVariantsType, NoArchType, RecipeReaderFlags
from conda_recipe_manager.types import PRIMITIVES_TUPLE, Primitives


class VariantsManager:
    """
    Class that manages the variants of a recipe, given a list of CBC files.
    """

    def __init__(
        self,
        recipe_str: str,
        cbc_strs: list[str],
        build_context: BuildContext,
        flags: RecipeReaderFlags = RecipeReaderFlags.NONE,
    ):
        """
        Initializes the VariantsManager.

        :param recipe_str: String representation of the recipe.
        :param cbc_strs: List of string representations of the CBC files.
        :param build_context: Build context to generate the variants for.
        :param flags: RecipeReaderFlags to be set. Defaults to `RecipeReaderFlags.NONE`.
        """
        self._build_context = build_context
        self._cbc_parsers: list[CbcReader] = [CbcReader(cbc_str) for cbc_str in cbc_strs]
        variants: Final[GeneratedVariantsType] = CbcReader.generate_variants(self._cbc_parsers, build_context)
        self._base_recipe: RecipeReaderDeps = RecipeReaderDeps(recipe_str, flags=flags)
        self._recipe_variants: list[RecipeVariant] = []
        # Tracks the structure of the recipe variant AND variable usage. Selector evaluations can cause changes that may
        # be opaque when comparing variable usage exclusively. Conversely, identically-structured recipes may vary
        # if they use variables with multiple defined values.
        known_used_vars_by_hash: dict[str, set[str]] = {}
        for full_var in variants:
            variant = {key: value for key, value in full_var.items() if isinstance(value, PRIMITIVES_TUPLE)}
            post_cbc_build_context: BuildContext = BuildContext(
                build_context.get_platform(), {**build_context.get_context(), **variant}
            )
            recipe_variant = RecipeVariant(recipe_str, post_cbc_build_context, flags=flags)
            if recipe_variant.get_value("/build/skip", default=None, sub_vars=True) is True:
                continue

            # De-duplicate identical variations while also mimicking conda-build's behavior around `python` versions.
            # We do this by checking variable usage within rendered variations.
            # NOTE:
            # - Selectors should be fully evaluated by the `RecipeVariant` class at construction, so we don't need to
            #   worry about CBC variables used in selectors. BUT we DO have to worry about selectors changing the
            #   structure of the variants.
            # - We have to assume that variable usage changes with selector evaluations, so we can't save compute by
            #   "caching" the variable values seen in the unrendered recipe file.
            recipe_variant_vars = recipe_variant.list_variables()
            # The `python` variable found commonly in CBC files is treated differently. Recipe files rarely, if ever,
            # reference `python` as a selector or variable. Yet the expected behavior in `conda-build` is to generate
            # 1-variant-per-python version.
            # TODO Future: Figure out if there are other common CBC variables that work this way.
            python_version = None if not recipe_variant.is_python_recipe() else variant.get("python", None)
            used_vars: dict[str, Primitives] = {
                var: cast(Primitives, recipe_variant.get_variable(var)) for var in recipe_variant_vars if var in variant
            }
            if python_version is not None:
                # `noarch` Python packages should only have 1-Python variant, so we use the same value for all `python`
                # versions.
                noarch_type = recipe_variant.get_noarch_type()
                used_vars["python"] = str(noarch_type) if noarch_type == NoArchType.PYTHON else python_version
            serialized_used_vars = json.dumps(used_vars, sort_keys=True)

            recipe_variant_hash: str = recipe_variant.calc_sha256()
            if recipe_variant_hash in known_used_vars_by_hash:
                if serialized_used_vars in known_used_vars_by_hash[recipe_variant_hash]:
                    continue
            else:
                # Allocate set on first hash
                known_used_vars_by_hash[recipe_variant_hash] = set()

            known_used_vars_by_hash[recipe_variant_hash].add(serialized_used_vars)
            self._recipe_variants.append(recipe_variant)

    def get_base_recipe(self) -> RecipeReaderDeps:
        """
        Returns the base (unrendered) recipe instance.

        :returns: The base recipe instance.
        """
        return self._base_recipe

    def get_recipe_variants(self) -> list[RecipeVariant]:
        """
        Returns the recipe variants as a list.

        :returns: The rendered recipe variants, as a list.
        """
        return self._recipe_variants

    def get_cbc_parsers(self) -> list[CbcReader]:
        """
        Returns the Conda Build Config parsers.

        :returns: A list of Conda Build Config (CBC) reader-instances that initialized this instance.
        """
        return self._cbc_parsers
