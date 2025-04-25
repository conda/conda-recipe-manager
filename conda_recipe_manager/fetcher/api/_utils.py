"""
:Description: Contains private utilities used by the API module.
"""

import traceback
from logging import Logger
from typing import Optional

import requests
from jsonschema import validate as schema_validate

from conda_recipe_manager.fetcher.api._types import DEFAULT_HTTP_REQ_TIMEOUT, BaseApiException
from conda_recipe_manager.types import JsonType, SchemaType


def make_request_and_validate(
    endpoint: str,
    schema: SchemaType,
    log: Optional[Logger] = None,
    timeout: int = DEFAULT_HTTP_REQ_TIMEOUT,
    headers: Optional[dict[str, str]] = None,
) -> JsonType:
    # pylint: disable=too-complex
    """
    Makes an HTTP request against the API and validates the result.

    :param endpoint: REST endpoint (URL) used in this request
    :param schema: JSON schema to validate the results against
    :param log: (Optional) Logger instance to log debug information to, if specified.
    :param timeout: (Optional) Timeout for an HTTP request
    :param headers: (Optional) HTTP headers for the request
    :raises BaseApiException: If there is an unrecoverable issue with the API. Callers should wrap this with the API
                              exception specific to their API!
    """
    response = None
    try:
        if log is not None:
            log.debug("Performing GET request on: %s", endpoint)
        response = requests.get(endpoint, timeout=timeout, headers=headers)
    except Exception as e:
        raise BaseApiException("GET request failed.") from e

    # This should not be possible, but we'll guard against it anyways.
    if response is None:
        raise BaseApiException("HTTP response was never set.")

    # Validate HTTP response
    if response.status_code != 200:
        raise BaseApiException(f"API returned a {response.status_code} HTTP status code")
    if "content-type" not in response.headers:
        raise BaseApiException("API returned with no `content-type` header.")
    content_type = response.headers["content-type"]
    if content_type != "application/json":
        raise BaseApiException(f"API returned a non-JSON `content-type`: {content_type}")

    # Validate JSON
    response_json: JsonType = {}
    try:
        response_json = response.json()
    except Exception as e:
        raise BaseApiException("Failed to parse JSON response.") from e
    try:
        schema_validate(response_json, schema)
    except Exception as e:
        if log is not None:
            log.debug("Validation exception trace: %s", traceback.format_exc())
        raise BaseApiException("Returned JSON does not match minimum schema.") from e

    return response_json


def check_for_empty_field(field: str, value: str | None) -> None:
    """
    Convenience function that checks if a critical field is empty/null.

    :param field: Field name (for debugging purposes)
    :param value: Value of the field to check
    :raises BaseApiException: If the field is empty. Callers should wrap this with the API exception specific to their
                              API!
    """
    if value is None or len(value) == 0:
        raise BaseApiException(f"`{field}` field is empty: {value}")
