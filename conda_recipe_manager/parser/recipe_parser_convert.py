"""
:Description: Provides a subclass of RecipeParser that performs the conversion of a v0 recipe to the new v1 recipe
                format. This tooling was originally part of the base class, but was broken-out for easier/cleaner code
                maintenance.
"""

from __future__ import annotations

from typing import Final, Optional, cast

from conda.models.match_spec import MatchSpec

from conda_recipe_manager.licenses.spdx_utils import SpdxUtils
from conda_recipe_manager.parser._types import ROOT_NODE_VALUE, CanonicalSortOrder, Regex
from conda_recipe_manager.parser._utils import search_any_regex, set_key_conditionally, stack_path_to_str
from conda_recipe_manager.parser.dependency import Dependency, DependencyConflictMode
from conda_recipe_manager.parser.enums import SchemaVersion, SelectorConflictMode
from conda_recipe_manager.parser.recipe_parser import RecipeParser
from conda_recipe_manager.parser.recipe_parser_deps import RecipeParserDeps
from conda_recipe_manager.parser.types import CURRENT_RECIPE_SCHEMA_FORMAT
from conda_recipe_manager.types import JsonPatchType, JsonType, MessageCategory, MessageTable, Primitives, SentinelType


class RecipeParserConvert(RecipeParserDeps):
    """
    Extension of the base RecipeParseDeps class that enables upgrading recipes from the old to V1 format.
    This was originally part of the RecipeParserDeps class but was broken-out for easier maintenance.
    """

    def __init__(self, content: str):
        """
        Constructs a convertible recipe object. This extension of the parser class keeps a modified copy of the original
        recipe to work on and tracks some debugging state.

        :param content: conda-build formatted recipe file, as a single text string.
        """
        super().__init__(content)
        # `copy.deepcopy()` produced some bizarre artifacts, namely single-line comments were being incorrectly rendered
        # as list members. Although inefficient, we have tests that validate round-tripping the parser and there
        # is no development cost in utilizing tools we already must maintain.
        self._v1_recipe: RecipeParserDeps = RecipeParserDeps(self.render())

        self._spdx_utils = SpdxUtils()
        self._msg_tbl = MessageTable()

    ## Patch utility functions ##

    def _patch_and_log(self, patch: JsonPatchType) -> bool:
        """
        Convenience function that logs failed patches to the message table.

        :param patch: Patch operation to perform
        :returns: Forwards patch results for further logging/error handling
        """
        result: Final[bool] = self._v1_recipe.patch(patch)
        if not result:
            self._msg_tbl.add_message(MessageCategory.ERROR, f"Failed to patch: {patch}")
        return result

    def _comment_and_log(self, path: str, comment: str) -> bool:
        """
        Convenience function that logs failed comment additions to the message table.

        :param path: Path to apply the comment to.
        :param comment: Comment to apply.
        :returns: Forwards commenting results for further logging/error handling
        """
        try:
            self._v1_recipe.add_comment(path, comment)
        except (ValueError, KeyError):
            self._msg_tbl.add_message(MessageCategory.ERROR, f"Failed to add comment on path {path}: {comment}")
            return False
        return True

    def _patch_add_missing_path(self, base_path: str, ext: str, value: JsonType = None) -> None:
        """
        Convenience function that constructs missing paths. Useful when you have to construct more than 1 path level at
        once (the JSON patch standard only allows the creation of 1 new level at a time).

        :param base_path: Base path, to be extended
        :param ext: Extension to create the full path to check for
        :param value: `value` field for the patch-add operation
        """
        temp_path: Final[str] = RecipeParser.append_to_path(base_path, ext)
        if self._v1_recipe.contains_value(temp_path):
            return
        self._patch_and_log({"op": "add", "path": temp_path, "value": value})

    def _patch_move_base_path(self, base_path: str, old_ext: str, new_ext: str) -> None:
        """
        Convenience function that moves a value under an old path to a new one sharing a common base path BUT only if
        the old path exists.

        :param base_path: Shared base path from old and new locations
        :param old_ext: Old extension to the base path containing the data to move
        :param new_ext: New extension to the base path of where the data should go
        """
        old_path: Final[str] = RecipeParser.append_to_path(base_path, old_ext)
        if not self._v1_recipe.contains_value(old_path):
            return
        self._patch_and_log({"op": "move", "from": old_path, "path": RecipeParser.append_to_path(base_path, new_ext)})

    def _patch_move_new_path(self, base_path: str, old_ext: str, new_path: str, new_ext: Optional[str] = None) -> None:
        """
        Convenience function that moves an old path to a new path that is now under a new path that must be
        conditionally added, if it is not present.

        Examples:
          - `/build/entry_points` -> `/build/python/entry_points`
          - `/build/missing_dso_whitelist` -> `/build/dynamic_linking/missing_dso_allowlist`

        :param base_path: Shared base path from old and new locations
        :param old_ext: Old extension to the base path containing the data to move
        :param new_path: New path to extend to the base path, if the path does not currently exist
        :param new_ext: (Optional) New extension to the base path of where the data should go. Use this when the target
            value has been renamed. Defaults to the value of `old_ext`.
        """
        if new_ext is None:
            new_ext = old_ext
        if self._v1_recipe.contains_value(RecipeParser.append_to_path(base_path, old_ext)):
            self._patch_add_missing_path(base_path, new_path)
        self._patch_move_base_path(base_path, old_ext, RecipeParser.append_to_path(new_path, new_ext))

    def _patch_deprecated_fields(self, base_path: str, fields: list[str]) -> None:
        """
        Automatically deprecates fields found in a common path.

        :param base_path: Shared base path where fields can be found
        :param fields: List of deprecated fields
        """
        for field in fields:
            path = RecipeParser.append_to_path(base_path, field)
            if not self._v1_recipe.contains_value(path):
                continue
            if self._patch_and_log({"op": "remove", "path": path}):
                self._msg_tbl.add_message(MessageCategory.WARNING, f"Field at `{path}` is no longer supported.")

    ## Upgrade functions ##

    def _upgrade_jinja_to_context_obj(self) -> None:
        """
        Upgrades the old proprietary JINJA templating usage to the new YAML-parsable `context` object and `$`-escaped
        JINJA substitutions.
        """
        # Convert the JINJA variable table to a `context` section. Empty tables still add the `context` section for
        # future developers' convenience.
        context_obj: dict[str, Primitives] = {}
        var_comments: dict[str, str] = {}
        # TODO Add selectors support? (I don't remember if V1 allows for selectors in `/context`)
        for name, node_var in self._v1_recipe._vars_tbl.items():  # pylint: disable=protected-access
            value = node_var.get_value()
            # Filter-out any value not covered in the V1 format
            if not isinstance(value, (str, int, float, bool)):
                self._msg_tbl.add_message(MessageCategory.WARNING, f"The variable `{name}` is an unsupported type.")
                continue

            # Track comments
            rendered_comment = node_var.render_comment()
            # TODO Handle selectors in issue #383
            if rendered_comment and not node_var.contains_selector():
                var_comments[RecipeParser.append_to_path("/context", name)] = rendered_comment

            # Function calls need to preserve JINJA escaping or else they turn into unevaluated strings.
            # See issue #271 for details about upgrading the `env.get(` function.
            # See issue #366 for details and fixes around escaping complex JINJA functions.
            # TODO Add support for #368
            if isinstance(value, str) and (
                search_any_regex(Regex.JINJA_FUNCTIONS_SET, value) or value.startswith("env.get(")
            ):
                value = "{{ " + value + " }}"
            context_obj[name] = value

        # Ensure that we do not include an empty context object (which is forbidden by the schema).
        if context_obj:
            # Check for Jinja that is too complex to convert
            # TODO remove after supporting issue #368
            complex_jinja = [
                key
                for key, value in context_obj.items()
                if isinstance(value, str) and any(pattern.search(value) for pattern in Regex.V0_UNSUPPORTED_JINJA)
            ]
            if complex_jinja:
                complex_jinja_display = ", ".join(complex_jinja)
                self._msg_tbl.add_message(
                    MessageCategory.WARNING,
                    f"The following key(s) contain partially unsupported syntax: {complex_jinja_display}",
                )

            self._patch_and_log({"op": "add", "path": "/context", "value": cast(JsonType, context_obj)})
            # Recover any comments associated with
            for var_path, var_comment in var_comments.items():
                self._comment_and_log(var_path, var_comment)

        # Similarly, patch-in the new `schema_version` value to the top of the file
        self._patch_and_log({"op": "add", "path": "/schema_version", "value": CURRENT_RECIPE_SCHEMA_FORMAT})

        # Swap all JINJA to use the new `${{ }}` format. A regex is used as `str.replace()` will replace all instances
        # and a value containing multiple variables could be visited multiple times, causing multiple `${{}}`
        # encapsulations.
        jinja_sub_locations: Final[set[str]] = set(self._v1_recipe.search(Regex.JINJA_V0_SUB))
        for path in jinja_sub_locations:
            value = self._v1_recipe.get_value(path)
            # Values that match the regex should only be strings. This prevents crashes that should not occur.
            if not isinstance(value, str):
                self._msg_tbl.add_message(
                    MessageCategory.WARNING, f"A non-string value was found as a JINJA substitution: {value}"
                )
                continue
            # Safely replace `{{` but not any existing `${{` instances
            value = Regex.JINJA_REPLACE_V0_STARTING_MARKER.sub("${{", value)
            self._patch_and_log({"op": "replace", "path": path, "value": value})

    def _upgrade_ambiguous_deps(self) -> None:
        """
        Attempts to update all dependency sections to use unambiguous version constraints. This uses the dependency
        tooling to prevent repeated logic. See Issue #276 and PR prefix-dev/rattler-build#1271 for more details.

        This must be run before selectors are upgraded to the V1 format, as V1 support for dependency management is not
        yet available.
        """
        try:
            dep_map = self._v1_recipe.get_all_dependencies()
        except (KeyError, ValueError):
            self._msg_tbl.add_message(
                MessageCategory.ERROR,
                "Could not parse dependencies when attempting to upgrade ambiguous version numbers.",
            )
            return

        for _, deps in dep_map.items():
            for dep in deps:
                # Warn and quit-early if there is a potential for a ambiguous version variable.
                if not isinstance(dep.data, MatchSpec):  # type: ignore[misc]
                    # TODO: Reduce spammy-ness by looking at the variables table
                    self._msg_tbl.add_message(
                        MessageCategory.WARNING,
                        (
                            "Recipe upgrades cannot currently upgrade ambiguous version constraints on dependencies"
                            f" that use variables: {dep.data.name}"
                        ),
                    )
                    continue

                if dep.data.version is None or not isinstance(dep.data.original_spec_str, str):  # type: ignore[misc]
                    continue

                spec_str = dep.data.original_spec_str
                # Corrects fairly common typos when dealing with >= and <= operators in dependency version selection
                # statements.
                spec_str = Regex.AMBIGUOUS_DEP_VERSION_GE_TYPO.sub(r"\1>=\2", spec_str)
                spec_str = Regex.AMBIGUOUS_DEP_VERSION_LE_TYPO.sub(r"\1<=\2", spec_str)
                # Corrects cases where two operators are used (i.e. `foo >=1.2.*`). We can't rely on MatchSpec to detect
                # multiple operators, so we fall back to using a regular expression. We drop the trailing `.*` to be
                # in alignment with `rattler-build`'s preferences:
                # https://github.com/conda/rattler/blob/main/crates/rattler_conda_types/src/version_spec/parse.rs#L224
                spec_str = Regex.AMBIGUOUS_DEP_MULTI_OPERATOR.sub(r"\1\2\3", spec_str)

                # Add a trailing `.*` to ambiguous dependencies that lack an operator. This is not that easy as
                # `VersionSpec` does not make a distinction between a version that contains a `==` operator and a
                # version with no operator (which is ambiguous per the V1 specification).
                if (
                    cast(bool, dep.data.version.is_exact())  # type: ignore[misc]
                    and "=" not in dep.data.original_spec_str
                ):
                    spec_str = f"{spec_str}.*"

                # Only commit changes to modified dependencies.
                if dep.data.original_spec_str == spec_str:
                    continue

                # TODO add IGNORE conflict mode for selectors???
                self._v1_recipe.add_dependency(
                    Dependency(
                        required_by=dep.required_by,
                        path=dep.path,
                        type=dep.type,
                        data=MatchSpec(spec_str),
                        selector=dep.selector,
                    ),
                    dep_mode=DependencyConflictMode.EXACT_POSITION,
                    sel_mode=SelectorConflictMode.OR,
                )
                self._msg_tbl.add_message(MessageCategory.WARNING, f"Version on dependency changed to: {spec_str}")

    def _upgrade_selectors_to_conditionals(self) -> None:
        """
        Upgrades the proprietary comment-based selector syntax to equivalent conditional logic statements.

        TODO warn if selector is unrecognized? See list:
          https://prefix-dev.github.io/rattler-build/latest/selectors/#available-variables
        conda docs for common selectors:
          https://docs.conda.io/projects/conda-build/en/latest/resources/define-metadata.html#preprocessing-selectors
        """
        for selector, instances in self._v1_recipe._selector_tbl.items():  # pylint: disable=protected-access
            for info in instances:
                # Selectors can be applied to the parent node if they appear on the same line. We'll ignore these when
                # building replacements.
                if not info.node.is_leaf():
                    continue

                # Strip the []'s around the selector
                bool_expression = selector[1:-1]
                # Convert to a public-facing path representation
                selector_path = stack_path_to_str(info.path)

                # Some commonly used selectors (like `py<36`) need to be upgraded. Otherwise, these expressions will be
                # interpreted as strings. See this CEP PR for more details: https://github.com/conda/ceps/pull/71
                bool_expression = Regex.SELECTOR_PYTHON_VERSION_REPLACEMENT.sub(
                    r'match(python, "\1\2.\3")', bool_expression
                )
                # Upgrades for less common `py36` and `not py27` selectors
                bool_expression = Regex.SELECTOR_PYTHON_VERSION_EQ_REPLACEMENT.sub(
                    r'match(python, "==\1.\2")', bool_expression
                )
                bool_expression = Regex.SELECTOR_PYTHON_VERSION_NE_REPLACEMENT.sub(
                    r'match(python, "!=\1.\2")', bool_expression
                )
                # Upgrades for less common `py2k` and `py3k` selectors
                bool_expression = Regex.SELECTOR_PYTHON_VERSION_PY2K_REPLACEMENT.sub(
                    r'match(python, ">=2,<3")', bool_expression
                )
                bool_expression = Regex.SELECTOR_PYTHON_VERSION_PY3K_REPLACEMENT.sub(
                    r'match(python, ">=3,<4")', bool_expression
                )

                # TODO other common selectors to support:
                # - GPU variants (see pytorch and llama.cpp feedstocks)

                # For now, if a selector lands on a boolean value, use a ternary statement. Otherwise use the
                # conditional logic.
                patch: JsonPatchType = {
                    "op": "replace",
                    "path": selector_path,
                    "value": "${{ true if " + bool_expression + " }}",
                }
                # `skip` is special and can be a single boolean expression or a list of boolean expressions.
                if selector_path.endswith("/build/skip"):
                    patch["value"] = bool_expression
                if not isinstance(info.node.value, bool):
                    # CEP-13 states that ONLY list members may use the `if/then/else` blocks
                    if not info.node.list_member_flag:
                        self._msg_tbl.add_message(
                            MessageCategory.WARNING, f"A non-list item had a selector at: {selector_path}"
                        )
                        continue
                    bool_object = {
                        "if": bool_expression,
                        "then": None if isinstance(info.node.value, SentinelType) else info.node.value,
                    }
                    patch = {
                        "op": "replace",
                        "path": selector_path,
                        "value": cast(JsonType, bool_object),
                    }
                # Apply the patch
                self._patch_and_log(patch)
                self._v1_recipe.remove_selector(selector_path)

    def _correct_common_misspellings(self, base_package_paths: list[str]) -> None:
        """
        Corrects common spelling mistakes in field names.

        :param base_package_paths: Set of base paths to process that could contain this section.
        """
        for base_path in base_package_paths:
            build_path = RecipeParser.append_to_path(base_path, "/build")
            about_path = RecipeParser.append_to_path(base_path, "/about")
            # "If I had a nickel for every time `skip` was misspelled, I would have several nickels. Which isn't a lot,
            #  but it is weird that it has happened multiple times."
            #                                                             - Dr. Doofenshmirtz, probably
            self._patch_move_base_path(build_path, "skipt", "skip")
            self._patch_move_base_path(build_path, "skips", "skip")
            self._patch_move_base_path(build_path, "Skip", "skip")

            # Various misspellings of "license_file" and "license_family". Note that `license_family` is deprecated,
            # but we fix the spelling so it can be removed at a later phase.
            self._patch_move_base_path(about_path, "licence_file", "license_file")
            self._patch_move_base_path(about_path, "licensse_file", "license_file")
            self._patch_move_base_path(about_path, "license_filte", "license_file")
            self._patch_move_base_path(about_path, "licsense_file", "license_file")
            self._patch_move_base_path(about_path, "icense_file", "license_file")
            self._patch_move_base_path(about_path, "licence_family", "license_family")
            self._patch_move_base_path(about_path, "license_familiy", "license_family")
            self._patch_move_base_path(about_path, "license_familly", "license_family")

            # Other about fields
            self._patch_move_base_path(about_path, "Description", "description")

            # `/extras` -> `/extra`
            self._patch_move_base_path(base_path, "extras", "extra")

    def _upgrade_source_section(self, base_package_paths: list[str]) -> None:
        """
        Upgrades/converts the `source` section(s) of a recipe file.

        :param base_package_paths: Set of base paths to process that could contain this section.
        """
        for base_path in base_package_paths:
            source_path = RecipeParser.append_to_path(base_path, "/source")
            if not self._v1_recipe.contains_value(source_path):
                continue

            # The `source` field can contain a list of elements or a single element (not encapsulated in a list).
            # This logic sets up a list to iterate through that will handle both cases.
            source_data = self._v1_recipe.get_value(source_path)
            source_paths = []
            if isinstance(source_data, list):
                for x in range(len(source_data)):
                    source_paths.append(RecipeParser.append_to_path(source_path, f"/{x}"))
            else:
                source_paths.append(source_path)

            for src_path in source_paths:
                # SVN and HG source options are no longer supported. This seems to have been deprecated a long
                # time ago and there are unlikely any recipes that fall into this camp. Still, we should flag it.
                if self._v1_recipe.contains_value(RecipeParser.append_to_path(src_path, "svn_url")):
                    self._msg_tbl.add_message(
                        MessageCategory.WARNING, "SVN packages are no longer supported in the V1 format"
                    )
                if self._v1_recipe.contains_value(RecipeParser.append_to_path(src_path, "hg_url")):
                    self._msg_tbl.add_message(
                        MessageCategory.WARNING, "HG (Mercurial) packages are no longer supported in the V1 format"
                    )

                # Basic renaming transformations
                self._patch_move_base_path(src_path, "/fn", "/file_name")
                self._patch_move_base_path(src_path, "/folder", "/target_directory")

                # `git` source transformations (`conda` does not appear to support all of the new features)
                self._patch_move_base_path(src_path, "/git_url", "/git")
                self._patch_move_base_path(src_path, "/git_tag", "/tag")
                self._patch_move_base_path(src_path, "/git_rev", "/rev")
                self._patch_move_base_path(src_path, "/git_depth", "/depth")

                # Canonically sort this section
                self._v1_recipe._sort_subtree_keys(  # pylint: disable=protected-access
                    src_path, CanonicalSortOrder.V1_SOURCE_SECTION_KEY_SORT_ORDER
                )

    def _upgrade_build_script_section(self, build_path: str) -> None:
        """
        Upgrades the `/build/script` section if needed. Some fields like `script_env` will need to be wrapped into a new
        `Script` object. Simple `script` sections can be left unchanged.

        :param build_path: Build section path to upgrade
        """
        script_env_path: Final[str] = RecipeParser.append_to_path(build_path, "/script_env")
        # The environment list could contain dictionaries if the variables are conditionally included.
        script_env_lst: Final[list[str | dict[str, str]]] = cast(
            list[str | dict[str, str]], self._v1_recipe.get_value(script_env_path, [])
        )
        if not script_env_lst:
            return

        script_path: Final[str] = RecipeParser.append_to_path(build_path, "/script")
        new_script_obj: JsonType = {}
        # Set environment variables need to be parsed and then re-added as a dictionary. Unset variables are listed
        # in the `secrets` section.
        new_env: dict[str, str] = {}
        new_secrets: list[str | dict[str, str]] = []
        for item in script_env_lst:
            # Attempt to edit conditional variables
            if isinstance(item, dict):
                if "then" not in item:
                    self._msg_tbl.add_message(
                        MessageCategory.ERROR, f"Could not parse dictionary `{item}` found in {script_env_path}"
                    )
                    continue
                tokens = [i.strip() for i in item["then"].split("=")]
                if len(tokens) == 1:
                    new_secrets.append(item)
                else:
                    # The spec does not support conditional statements in a dictionary. As per discussions with the
                    # community, the best course of action is manual intervention.
                    self._msg_tbl.add_message(
                        MessageCategory.ERROR,
                        f"Converting `{item}` found in {script_env_path} is not supported."
                        " Manually replace the selector with a `cmp()` function.",
                    )
                continue

            tokens = [i.strip() for i in item.split("=")]
            if len(tokens) == 1:
                new_secrets.append(tokens[0])
            elif len(tokens) == 2:
                new_env[tokens[0]] = tokens[1]
            else:
                self._msg_tbl.add_message(MessageCategory.ERROR, f"Could not parse `{item}` found in {script_env_path}")

        set_key_conditionally(cast(dict[str, JsonType], new_script_obj), "env", cast(JsonType, new_env))
        set_key_conditionally(cast(dict[str, JsonType], new_script_obj), "secrets", cast(JsonType, new_secrets))

        script_value = self._v1_recipe.get_value(script_path, "")
        patch_op: Final[str] = "replace" if script_value else "add"
        # TODO: Simple script files should be set as `file` not `content`
        set_key_conditionally(cast(dict[str, JsonType], new_script_obj), "content", script_value)

        self._patch_and_log({"op": patch_op, "path": script_path, "value": new_script_obj})
        self._patch_and_log({"op": "remove", "path": script_env_path})

    def _upgrade_build_section(self, base_package_paths: list[str]) -> None:
        """
        Upgrades/converts the `build` section(s) of a recipe file.

        :param base_package_paths: Set of base paths to process that could contain this section.
        """
        build_deprecated: Final[list[str]] = [
            "pre-link",
            "noarch_python",
            "features",
            "msvc_compiler",
            "requires_features",
            "provides_features",
            "preferred_env",
            "preferred_env_executable_paths",
            "disable_pip",
            "pin_depends",
            "overlinking_ignore_patterns",
            "rpaths_patcher",
            "post-link",
            "pre-unlink",
            "pre-link",
        ]

        for base_path in base_package_paths:
            # Move `run_exports` and `ignore_run_exports` from `build` to `requirements`

            # `run_exports`
            old_re_path = RecipeParser.append_to_path(base_path, "/build/run_exports")
            if self._v1_recipe.contains_value(old_re_path):
                requirements_path = RecipeParser.append_to_path(base_path, "/requirements")
                new_re_path = RecipeParser.append_to_path(base_path, "/requirements/run_exports")
                if not self._v1_recipe.contains_value(requirements_path):
                    self._patch_and_log({"op": "add", "path": requirements_path, "value": None})
                self._patch_and_log({"op": "move", "from": old_re_path, "path": new_re_path})
            # `ignore_run_exports`
            for old_ire_name, new_ire_name in [
                ("ignore_run_exports", "by_name"),
                ("ignore_run_exports_from", "from_package"),
            ]:
                old_ire_path = RecipeParser.append_to_path(base_path, f"/build/{old_ire_name}")
                if self._v1_recipe.contains_value(old_ire_path):
                    self._patch_add_missing_path(base_path, "/requirements")
                    self._patch_move_new_path(
                        base_path,
                        f"/build/{old_ire_name}",
                        "/requirements/ignore_run_exports",
                        new_ire_name,
                    )

            # Perform internal section changes per `build/` section
            build_path = RecipeParser.append_to_path(base_path, "/build")
            if not self._v1_recipe.contains_value(build_path):
                continue

            # Simple transformations
            self._patch_move_base_path(build_path, "merge_build_host", "merge_build_and_host_envs")
            self._patch_move_base_path(build_path, "no_link", "always_copy_files")

            # `build/entry_points` -> `build/python/entry_points`
            self._patch_move_new_path(build_path, "/entry_points", "/python")

            # `build/force_use_keys` -> `build/variant/use_keys`
            self._patch_move_new_path(build_path, "/force_use_keys", "/variant", "use_keys")

            # New `prefix_detection` section changes
            # NOTE: There is a new `force_file_type` field that may map to an unknown field that conda supports.
            self._patch_move_new_path(build_path, "/ignore_prefix_files", "/prefix_detection", "/ignore")
            self._patch_move_new_path(
                build_path, "/detect_binary_files_with_prefix", "/prefix_detection", "/ignore_binary_files"
            )

            # New `dynamic_linking` section changes
            # NOTE: `overdepending_behavior` and `overlinking_behavior` are new fields that don't have a direct path
            #       to conversion.
            self._patch_move_new_path(build_path, "/rpaths", "/dynamic_linking", "/rpaths")
            self._patch_move_new_path(build_path, "/binary_relocation", "/dynamic_linking", "/binary_relocation")
            self._patch_move_new_path(
                build_path, "/missing_dso_whitelist", "/dynamic_linking", "/missing_dso_allowlist"
            )
            self._patch_move_new_path(build_path, "/runpath_whitelist", "/dynamic_linking", "/rpath_allowlist")

            self._upgrade_build_script_section(build_path)
            self._patch_deprecated_fields(build_path, build_deprecated)

            # Canonically sort this section
            self._v1_recipe._sort_subtree_keys(  # pylint: disable=protected-access
                build_path, CanonicalSortOrder.V1_BUILD_SECTION_KEY_SORT_ORDER
            )

    def _upgrade_requirements_section(self, base_package_paths: list[str]) -> None:
        """
        Upgrades/converts the `requirements` section(s) of a recipe file.

        :param base_package_paths: Set of base paths to process that could contain this section.
        """
        for base_path in base_package_paths:
            requirements_path = RecipeParser.append_to_path(base_path, "/requirements")
            if not self._v1_recipe.contains_value(requirements_path):
                continue

            # Renames `run_constrained` to the new equivalent name
            self._patch_move_base_path(requirements_path, "/run_constrained", "/run_constraints")

    def _fix_bad_licenses(self, about_path: str) -> None:
        """
        Attempt to correct licenses to match SPDX-recognized names.

        For now, this does not call-out to an SPDX database. Instead, we attempt to correct common mistakes.

        :param about_path: Path to the `about` section, where the `license` field is located.
        """
        license_path: Final[str] = RecipeParser.append_to_path(about_path, "/license")
        old_license: Final[Optional[str]] = cast(Optional[str], self._v1_recipe.get_value(license_path, default=None))
        if old_license is None:
            self._msg_tbl.add_message(MessageCategory.WARNING, f"No `license` provided in `{about_path}`")
            return

        corrected_license: Final[Optional[str]] = self._spdx_utils.find_closest_license_match(old_license)

        if corrected_license is None:
            self._msg_tbl.add_message(MessageCategory.WARNING, f"Could not patch unrecognized license: `{old_license}`")
            return

        # If it ain't broke, don't patch it
        if old_license == corrected_license:
            return

        # Alert the user that a patch was made, in case it needs manual verification. This warning will not emit if
        # the patch failed (failure will generate an arguably more important message)
        if self._patch_and_log({"op": "replace", "path": license_path, "value": corrected_license}):
            self._msg_tbl.add_message(
                MessageCategory.WARNING, f"Changed {license_path} from `{old_license}` to `{corrected_license}`"
            )

    def _upgrade_about_section(self, base_package_paths: list[str]) -> None:
        """
        Upgrades/converts the `about` section of a recipe file.

        :param base_package_paths: Set of base paths to process that could contain this section.
        """
        about_rename_mapping: Final[list[tuple[str, str]]] = [
            ("home", "homepage"),
            ("dev_url", "repository"),
            ("doc_url", "documentation"),
        ]
        about_deprecated: Final[list[str]] = [
            "prelink_message",
            "license_family",
            "identifiers",
            "tags",
            "keywords",
            "doc_source_url",
        ]

        for base_path in base_package_paths:
            about_path = RecipeParser.append_to_path(base_path, "/about")

            # Skip transformations if there is no `/about` section
            if not self._v1_recipe.contains_value(about_path):
                continue

            # Transform renamed fields
            for old, new in about_rename_mapping:
                self._patch_move_base_path(about_path, old, new)

            self._fix_bad_licenses(about_path)

            # R packages like to use multiline strings without multiline markers, which get interpreted as list members
            # TODO address this at parse-time, adding a new multiline mode
            summary_path = RecipeParser.append_to_path(about_path, "/summary")
            summary = self._v1_recipe.get_value(summary_path, "")
            if isinstance(summary, list):
                self._patch_and_log(
                    {"op": "replace", "path": summary_path, "value": "\n".join(cast(list[str], summary))}
                )

            # Remove deprecated `about` fields
            self._patch_deprecated_fields(about_path, about_deprecated)

    def _upgrade_test_pip_check(self, test_path: str) -> None:
        """
        Replaces the commonly used `pip check` test-case with the new `python/pip_check` attribute, if applicable.

        :param test_path: Test path for the build target to upgrade
        """
        # Replace `- pip check` in `commands` with the new flag. If not found, set the flag to `False` (as the
        # flag defaults to `True`). DO NOT ADD THIS FLAG IF THE RECIPE IS NOT A "PYTHON RECIPE".
        if not self._v1_recipe.is_python_recipe():
            return

        pip_check_variants: Final[set[str]] = {
            "pip check",
            "python -m pip check",
            "python3 -m pip check",
        }

        commands_path: Final[str] = RecipeParser.append_to_path(test_path, "/commands")
        commands = cast(Optional[list[str]], self._v1_recipe.get_value(commands_path, []))
        # Normalize the rare edge case where the list may be null (usually caused by commented-out code)
        if commands is None:
            commands = []
        pip_check = False
        for i, command in enumerate(commands):
            # TODO Future: handle selector cases (pip check will be in the `then` section of a dictionary object)
            if not isinstance(command, str) or command not in pip_check_variants:
                continue
            # For now, we will only patch-out the first instance when no selector is attached
            self._patch_and_log({"op": "remove", "path": RecipeParser.append_to_path(commands_path, f"/{i}")})
            pip_check = True
            break

        # Edge-case: Remove `commands` (which will soon become `script`) and `requirements` if `pip check` was the only
        # command present. Otherwise, we will effectively create an empty test object.
        if pip_check and len(commands) == 1:
            # `/commands` must exist in order to get a single command in the list checked above
            self._patch_and_log({"op": "remove", "path": commands_path})
            # `/requirements` should exist AND should be requiring `pip`. In the event it doesn't, let's be resilient.
            requirements_path: Final[str] = RecipeParser.append_to_path(test_path, "/requirements")
            if self._v1_recipe.contains_value(requirements_path):
                self._patch_and_log({"op": "remove", "path": requirements_path})

        self._patch_add_missing_path(test_path, "/python")
        self._patch_and_log(
            {"op": "add", "path": RecipeParser.append_to_path(test_path, "/python/pip_check"), "value": pip_check}
        )

    def _upgrade_test_section(self, base_package_paths: list[str]) -> None:
        # pylint: disable=too-complex
        # TODO Refactor and simplify ^
        """
        Upgrades/converts the `test` section(s) of a recipe file.

        :param base_package_paths: Set of base paths to process that could contain this section.
        """
        # NOTE: For now, we assume that the existing test section comprises of a single test entity. Developers will
        # have to use their best judgement to manually break-up the test into multiple tests as they see fit.
        for base_path in base_package_paths:
            test_path = RecipeParser.append_to_path(base_path, "/test")
            if not self._v1_recipe.contains_value(test_path):
                continue

            # Moving `files` to `files/recipe` is not possible in a single `move` operation as a new path has to be
            # created in the path being moved.
            test_files_path = RecipeParser.append_to_path(test_path, "/files")
            if self._v1_recipe.contains_value(test_files_path):
                test_files_value = self._v1_recipe.get_value(test_files_path)
                # TODO: Fix, replace does not work here, produces `- null`, Issue #20
                # self._patch_and_log({"op": "replace", "path": test_files_path, "value": None})
                self._patch_and_log({"op": "remove", "path": test_files_path})
                self._patch_and_log({"op": "add", "path": test_files_path, "value": None})
                self._patch_and_log(
                    {
                        "op": "add",
                        "path": RecipeParser.append_to_path(test_files_path, "/recipe"),
                        "value": test_files_value,
                    }
                )
            # Edge case: `/source_files` exists but `/files` does not
            elif self._v1_recipe.contains_value(RecipeParser.append_to_path(test_path, "/source_files")):
                self._patch_add_missing_path(test_path, "/files")
            self._patch_move_base_path(test_path, "/source_files", "/files/source")

            if self._v1_recipe.contains_value(RecipeParser.append_to_path(test_path, "/requires")):
                self._patch_add_missing_path(test_path, "/requirements")
            self._patch_move_base_path(test_path, "/requires", "/requirements/run")

            # Upgrade `pip-check`, if applicable
            self._upgrade_test_pip_check(test_path)

            self._patch_move_base_path(test_path, "/commands", "/script")
            if self._v1_recipe.contains_value(RecipeParser.append_to_path(test_path, "/imports")):
                self._patch_add_missing_path(test_path, "/python")
                self._patch_move_base_path(test_path, "/imports", "/python/imports")
            self._patch_move_base_path(test_path, "/downstreams", "/downstream")

            # Canonically sort the python section, if it exists
            self._v1_recipe._sort_subtree_keys(  # pylint: disable=protected-access
                RecipeParser.append_to_path(test_path, "/python"), CanonicalSortOrder.V1_PYTHON_TEST_KEY_SORT_ORDER
            )

            # Move `test` to `tests` and encapsulate the pre-existing object into a list
            new_test_path = f"{test_path}s"
            test_element = cast(Optional[dict[str, JsonType]], self._v1_recipe.get_value(test_path, default=None))
            # Handle empty test sections (commonly seen in bioconda and R recipes)
            if test_element is None:
                continue
            test_array: list[JsonType] = []
            # There are 3 types of test elements. We break them out of the original object, if they exist.
            # `Python` Test Element
            if "python" in test_element:
                test_array.append({"python": test_element["python"]})
                del test_element["python"]
            # `Downstream` Test Element
            if "downstream" in test_element:
                test_array.append({"downstream": test_element["downstream"]})
                del test_element["downstream"]
            # What remains should be the `Command` Test Element type
            if test_element:
                test_array.append(test_element)
            self._patch_and_log({"op": "add", "path": new_test_path, "value": test_array})
            self._patch_and_log({"op": "remove", "path": test_path})

    def _upgrade_multi_output(self, base_package_paths: list[str]) -> None:
        """
        Upgrades/converts sections pertaining to multi-output recipes.

        :param base_package_paths: Set of base paths to process that could contain this section.
        """
        if not self._v1_recipe.contains_value("/outputs"):
            return

        # TODO Complete
        # On the top-level, `package` -> `recipe`
        self._patch_move_base_path(ROOT_NODE_VALUE, "/package", "/recipe")

        for output_path in base_package_paths:
            if output_path == ROOT_NODE_VALUE:
                continue

            # Move `name` and `version` under `package`
            if self._v1_recipe.contains_value(
                RecipeParser.append_to_path(output_path, "/name")
            ) or self._v1_recipe.contains_value(RecipeParser.append_to_path(output_path, "/version")):
                self._patch_add_missing_path(output_path, "/package")
            self._patch_move_base_path(output_path, "/name", "/package/name")
            self._patch_move_base_path(output_path, "/version", "/package/version")

            # Not all the top-level keys are found in each output section, but all the output section keys are
            # found at the top-level. So for consistency, we sort on that ordering.
            self._v1_recipe._sort_subtree_keys(  # pylint: disable=protected-access
                output_path, CanonicalSortOrder.TOP_LEVEL_KEY_SORT_ORDER
            )

    @staticmethod
    def pre_process_recipe_text(content: str) -> str:
        """
        Takes the content of a recipe file and performs manipulations prior to the parsing stage. This should be
        used sparingly for solving conversion issues.

        Ideally the pre-processor phase is only used when:
          - There is no other feasible way to solve a conversion issue.
          - There is a proof-of-concept fix that would be easier to develop as a pre-processor step that could be
            refactored into the parser later.
          - The number of recipes afflicted by an issue does not justify the engineering effort required to handle
            the issue in the parsing phase.

        :param content: Recipe file contents to pre-process
        :returns: Pre-processed recipe file contents
        """
        # Some recipes use `foo.<function()>` instead of `{{ foo | <function()> }}` in JINJA statements. This causes
        # rattler-build to fail with `invalid operation: object has no method named <function()>`
        # NOTE: This is currently done BEFORE converting to use `env.get()` to wipe-out those changes.
        content = Regex.PRE_PROCESS_JINJA_DOT_FUNCTION_IN_ASSIGNMENT.sub(r"\1 | \2", content)
        content = Regex.PRE_PROCESS_JINJA_DOT_FUNCTION_IN_SUBSTITUTION.sub(r"\1 | \2", content)
        # Strip any problematic parenthesis that may be left over from the previous operations.
        content = Regex.PRE_PROCESS_JINJA_DOT_FUNCTION_STRIP_EMPTY_PARENTHESIS.sub(r"\1", content)
        # Attempt to normalize quoted multiline strings into the common `|` syntax.
        # TODO: Handle multiple escaped newlines (very uncommon)
        content = Regex.PRE_PROCESS_QUOTED_MULTILINE_STRINGS.sub(r"\1\2: |\1  \3\1  \4", content)

        # rattler-build@0.18.0: Introduced checks for deprecated `max_pin` and `min_pin` fields. This replacement
        # addresses the change in numerous JINJA functions that use this nomenclature.
        content = Regex.PRE_PROCESS_MIN_PIN_REPLACEMENT.sub("lower_bound=", content)
        content = Regex.PRE_PROCESS_MAX_PIN_REPLACEMENT.sub("upper_bound=", content)

        # Convert the old JINJA `environ[""]` variable usage to the new `get.env("")` syntax.
        # NOTE:
        #   - This is mostly used by Bioconda recipes and R-based-packages in the `license_file` field.
        #   - From our search, it looks like we never deal with more than one set of outer quotes within the brackets
        replacements: list[tuple[str, str]] = []
        for groups in cast(list[tuple[str, ...]], Regex.PRE_PROCESS_ENVIRON.findall(content)):
            # Each match should return ["<quote char>", "<key>", "<quote_char>"]
            quote_char = groups[0]
            key = groups[1]
            replacements.append(
                (
                    f"environ[{quote_char}{key}{quote_char}]",
                    f"env.get({quote_char}{key}{quote_char})",
                )
            )

        for groups in cast(list[tuple[str, ...]], Regex.PRE_PROCESS_ENVIRON_GET.findall(content)):
            environ_key = f"{groups[0]}{groups[1]}{groups[2]}"
            environ_default = f"{groups[3]}{groups[4]}{groups[5]}"

            replacements.append(
                (
                    f"environ | get({environ_key}, {environ_default})",
                    f"env.get({environ_key}, default={environ_default})",
                )
            )

        for old, new in replacements:
            content = content.replace(old, new, 1)

        # Replace `{{ hash_type }}:` with the value of `hash_type`, which is likely `sha256`. This is an uncommon
        # practice that is not part of the V1 specification. Currently, about 70 AnacondaRecipes and conda-forge files
        # do this in our integration testing sample.
        return RecipeParser.pre_process_remove_hash_type(content)

    def render_to_v1_recipe_format(self) -> tuple[str, MessageTable, str]:
        """
        Takes the current recipe representation and renders it to the V1 format WITHOUT modifying the current recipe
        state.

        This "new" format is defined in the following CEPs:
          - https://github.com/conda/ceps/blob/main/cep-0013.md
          - https://github.com/conda/ceps/blob/main/cep-0014.md

        :returns: Returns a tuple containing: - The converted recipe, as a string - A `MessageTbl` instance that
            contains error logging - Converted recipe file debug string. USE FOR DEBUGGING PURPOSES ONLY!
        """
        # Approach: In the event that we want to expand support later, this function should be implemented in terms
        # of a `RecipeParser` tree. This will make it easier to build an upgrade-path, if we so choose to pursue one.

        # Log the original comments
        old_comments: Final[dict[str, str]] = self._v1_recipe.get_comments_table()

        # Attempts to update ambiguous dependency constraints. See function comments for more details.
        self._upgrade_ambiguous_deps()

        # Convert selectors into ternary statements or `if` blocks. We process selectors first so that there is no
        # chance of selector comments getting accidentally wiped by patch or other operations.
        self._upgrade_selectors_to_conditionals()

        # JINJA templates -> `context` object
        self._upgrade_jinja_to_context_obj()

        # Cached copy of all of the "outputs" in a recipe. This is useful for easily handling multi and single output
        # recipes in 1 loop construct.
        base_package_paths: Final[list[str]] = self._v1_recipe.get_package_paths()

        # TODO Fix: comments are not preserved with patch operations (add a flag to `patch()`?)

        # There are a number of recipe files that contain the same misspellings. This is an attempt to
        # solve the more common issues.
        self._correct_common_misspellings(base_package_paths)

        # Upgrade common sections found in a recipe
        self._upgrade_source_section(base_package_paths)
        self._upgrade_build_section(base_package_paths)
        self._upgrade_requirements_section(base_package_paths)
        self._upgrade_about_section(base_package_paths)
        self._upgrade_test_section(base_package_paths)
        self._upgrade_multi_output(base_package_paths)

        ## Final clean-up ##

        # TODO: Comment tracking may need improvement. The "correct way" of tracking comments with patch changes is a
        #       fairly big engineering effort and refactor.
        # Alert the user which comments have been dropped.
        new_comments: Final[dict[str, str]] = self._v1_recipe.get_comments_table()
        diff_comments: Final[dict[str, str]] = {k: v for k, v in old_comments.items() if k not in new_comments}
        for path, comment in diff_comments.items():
            if not self._v1_recipe.contains_value(path):
                self._msg_tbl.add_message(MessageCategory.WARNING, f"Could not relocate comment: {comment}")

        # TODO Complete: move operations may result in empty fields we can eliminate. This may require changes to
        #                `contains_value()`
        # TODO Complete: Attempt to combine consecutive If/Then blocks after other modifications. This should reduce the
        #                risk of screwing up critical list indices and ordering.

        # Hack: Wipe the existing table so the JINJA `set` statements don't render the final form
        self._v1_recipe._vars_tbl = {}  # pylint: disable=protected-access

        # Sort the top-level keys to a "canonical" ordering. This should make previous patch operations look more
        # "sensible" to a human reader.
        self._v1_recipe._sort_subtree_keys(  # pylint: disable=protected-access
            "/", CanonicalSortOrder.TOP_LEVEL_KEY_SORT_ORDER
        )

        # Override the schema value as the recipe conversion is now complete.
        self._v1_recipe._schema_version = SchemaVersion.V1  # pylint: disable=protected-access
        # Update the variable table
        self._v1_recipe._init_vars_tbl()  # pylint: disable=protected-access
        # TODO update selector table when V1 selectors are supported!

        return self._v1_recipe.render(), self._msg_tbl, str(self._v1_recipe)
