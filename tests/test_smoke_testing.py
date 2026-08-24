"""
:Description: Collection of smoke tests that don't fit under any other test file.
"""

import pytest
import pytest_socket  # type: ignore[import-untyped]
import requests


# pytest-socket@0.8.0+ marks any socket usage with a pytest warning. We must suppress this in order to pass the
# smoke-test that ensures pytest-socket is working as intended.
@pytest.mark.filterwarnings("ignore::UserWarning")
def test_validate_pysocket_plugin() -> None:
    """
    Smoke test that ensures that the `pysocket` plugin is working by running an unmocked HTTP GET request that should
    never reach out to the network.
    """
    result = None
    with pytest.raises(pytest_socket.SocketBlockedError):  # type: ignore[misc]
        result = requests.get("https://www.anaconda.com", timeout=5)
    # Potentially redundant check for safety to ensure that the HTTP GET call did not occur.
    assert result is None
