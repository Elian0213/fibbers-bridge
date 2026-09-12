"""Shared test fixtures.

`enable_custom_integrations` is what lets Home Assistant's test harness find and
load `custom_components/fibbers_bridge` — without it the component is invisible to
`hass` under test. It's auto-used so every test gets it for free.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load our custom component in every test (harness fixture does the work)."""
    yield
