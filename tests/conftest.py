"""Test setup."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(request: pytest.FixtureRequest) -> None:
    """Let Home Assistant load the integration from custom_components."""
    request.getfixturevalue("enable_custom_integrations")
