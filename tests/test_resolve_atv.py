"""Guard tests for `_resolve_atv`.

This is the function that broke in 0.1.0: it read the live pyatv connection only
from `hass.data["apple_tv"][entry_id]`, but core moved the manager onto
`entry.runtime_data` in HA 2024.6, so every service call failed. 0.1.1 reads
`runtime_data` first with the legacy dict as fallback. These tests pin both paths
down so the next core refactor is caught here, not by a user.
"""

from __future__ import annotations

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fibbers_bridge import _resolve_atv
from custom_components.fibbers_bridge.const import APPLE_TV_DOMAIN


class _Manager:
    """Stand-in for core's AppleTVManager — all `_resolve_atv` wants is `.atv`."""

    def __init__(self, atv: object) -> None:
        self.atv = atv


def _add_apple_tv_device(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    """Register an apple_tv config entry + a device wired to it; return device_id."""
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(APPLE_TV_DOMAIN, entry.entry_id)},
    )
    return device.id


async def test_resolves_via_runtime_data(hass: HomeAssistant) -> None:
    """HA 2024.6+ path: the manager lives on `entry.runtime_data`."""
    atv = object()
    entry = MockConfigEntry(domain=APPLE_TV_DOMAIN)
    device_id = _add_apple_tv_device(hass, entry)
    entry.runtime_data = _Manager(atv)

    assert _resolve_atv(hass, device_id) is atv


async def test_resolves_via_legacy_hass_data(hass: HomeAssistant) -> None:
    """Pre-2024.6 fallback: manager only in `hass.data['apple_tv'][entry_id]`."""
    atv = object()
    entry = MockConfigEntry(domain=APPLE_TV_DOMAIN)
    device_id = _add_apple_tv_device(hass, entry)
    entry.runtime_data = None
    hass.data[APPLE_TV_DOMAIN] = {entry.entry_id: _Manager(atv)}

    assert _resolve_atv(hass, device_id) is atv


async def test_non_apple_tv_entry_is_skipped(hass: HomeAssistant) -> None:
    """A device can carry entries from several integrations; ignore the others."""
    atv = object()
    other = MockConfigEntry(domain="light")
    other.add_to_hass(hass)
    apple = MockConfigEntry(domain=APPLE_TV_DOMAIN)
    apple.add_to_hass(hass)
    apple.runtime_data = _Manager(atv)

    registry = dr.async_get(hass)
    device = registry.async_get_or_create(
        config_entry_id=other.entry_id,
        identifiers={("light", "x")},
    )
    device = registry.async_get_or_create(
        config_entry_id=apple.entry_id,
        identifiers={("light", "x")},
    )

    assert _resolve_atv(hass, device.id) is atv


async def test_no_live_connection_raises(hass: HomeAssistant) -> None:
    """Apple TV integration present, but no live pyatv object → clear error."""
    entry = MockConfigEntry(domain=APPLE_TV_DOMAIN)
    device_id = _add_apple_tv_device(hass, entry)
    entry.runtime_data = None  # no manager anywhere

    with pytest.raises(ServiceValidationError, match="No connected Apple TV"):
        _resolve_atv(hass, device_id)


async def test_integration_not_set_up_raises(hass: HomeAssistant) -> None:
    """No apple_tv entries at all → the 'not set up' message, not a crash."""
    other = MockConfigEntry(domain="light")
    other.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id,
        identifiers={("light", "x")},
    )

    with pytest.raises(ServiceValidationError, match="not set up"):
        _resolve_atv(hass, device.id)


async def test_unknown_device_raises(hass: HomeAssistant) -> None:
    """A device_id the registry doesn't know is rejected up front."""
    with pytest.raises(ServiceValidationError, match="Unknown device_id"):
        _resolve_atv(hass, "does-not-exist")
