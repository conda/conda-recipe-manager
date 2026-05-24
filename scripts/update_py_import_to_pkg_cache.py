#!/usr/bin/env python3
"""
:Description: Script that fetches the Conda Forge's import name to package name mapping, shrinks it to decrease the
    cached size, and applies custom mappings for CRM. This data can be found in the `cf-graph-countyfair` project.
    NOTE: There is an on-going effort to combine all conda-forge metadata into one API. At the time of writing this
    tool, the API does not include the `import` naming data. See the links below for more context:
      - https://github.com/conda-forge/conda-forge-metadata/tree/main
      - https://github.com/conda-incubator/conda-recipe-manager/pull/218
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Final, cast

import requests
from jsonschema import validate as schema_validate

from conda_recipe_manager.types import JsonType, SchemaType

logging.basicConfig(
    format="[%(levelname)s] [%(name)s]: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(Path(__file__).name)

## Types ##

# Type alias for the CF-provided mapping file, if it follows the expected schema.
CfMapFile = list[dict[str, str | list[str]]]
# Type alias for the simplified mapping type used by CRM
CrmMapFile = dict[str, list[str]]

## Constants ##

# NOTE: The original file is ~850kb
_MAPPING_FILE_URL: Final[str] = (
    "https://raw.githubusercontent.com/regro/cf-graph-countyfair"
    "/refs/heads/master/mappings/pypi/import_name_priority_mapping.json"
)
# A relative path off of `__file__` is used as the `scripts` directory is not a module of CRM.
_OUTPUT_FILE: Final[Path] = (
    Path(__file__).parent / "../conda_recipe_manager/cached_data/import_to_package_names_map.json"
)

# Appends/overrides any package name mappings not covered by the original data source.
_OVERRIDE_PATCH_TBL: Final[CrmMapFile] = {
    "yaml": ["pyyaml"],
    "PIL": ["pillow"],
    "sklearn": ["scikit-learn"],
    "tables": ["pytables"],
    "cv": ["py-opencv"],
    "cv2": ["py-opencv"],
    "OpenGL": ["pyopengl"],
}

# JSON Schema expected by the Conda Forge datasource.
_CF_JSON_MAP_FILE_SCHEMA: Final[SchemaType] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "import_name": {"type": "string", "minLength": 1},
            "ranked_conda_names": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "import_name",
            "ranked_conda_names",
        ],
    },
}


def _fetch_and_validate_cf_mapping() -> CfMapFile:
    """
    Helper function that retrieves and validates the import mapping data provided by Conda Forge.

    :raises Exception: In the event of a network or schema validation failure.
    :returns: The Conda Forge mapping data, as a Python dictionary.
    """
    log.info("Fetching conda forge data...")
    response = requests.get(_MAPPING_FILE_URL)
    content: Final[JsonType] = json.loads(response.content)
    schema_validate(content, _CF_JSON_MAP_FILE_SCHEMA)
    return cast(CfMapFile, content)


def _apply_overrides(cached_mapping: CrmMapFile) -> None:
    """
    Helper function that applies CRM's custom import name mappings against the original Conda Forge set.

    :param cached_mapping: Mapping format used by CRM.
    """
    for k, v in _OVERRIDE_PATCH_TBL.items():
        cached_mapping[k] = v


def main() -> None:
    """
    Takes a data data source recognized by `conda-pypi` and writes a JSON file mapping PYPI names to their Conda
    equivalents.
    """
    try:
        original_mapping = _fetch_and_validate_cf_mapping()
    except Exception:  # pylint: disable=broad-exception-caught
        log.error("Failed to fetch and validate the conda-forge import mapping file.")
        sys.exit(1)

    cached_mapping: CrmMapFile = {}
    multi_name_cntr = 0
    for entry in original_mapping:
        import_name = cast(str, entry["import_name"])
        conda_names = cast(list[str], entry["ranked_conda_names"])

        if len(conda_names) > 1:
            multi_name_cntr += 1

        if import_name in cached_mapping:
            log.warning("Duplicate import name found: %s", import_name)
            cached_mapping[import_name].extend(conda_names)
            continue
        cached_mapping[import_name] = conda_names

    log.info("Multiple conda names found for %s out of %s entries.", multi_name_cntr, len(original_mapping))

    _apply_overrides(cached_mapping)

    # Sort the cache, to make diffs more obvious.
    cached_mapping = dict(sorted(cached_mapping.items()))
    _OUTPUT_FILE.write_text(json.dumps(cached_mapping), encoding="utf-8")
    log.info("Mapping updated in file: %s (%sKiB)", _OUTPUT_FILE.name, _OUTPUT_FILE.stat().st_size // 1024)


if __name__ == "__main__":
    main()
