"""Tests for the ambilight colour helpers and sync lifecycle.

The pure helpers (`average_zones`, `colour_changed`, `clamp_rate`) carry the logic
that decides what colour the strip shows and how often — so they're pinned here,
independent of any TV or network. The lifecycle tests cover the guard rails a user
actually hits: an unknown source, and a target that can't take an RGB colour.
"""

from __future__ import annotations

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.fibbers_bridge.ambilight import (
    average_zones,
    clamp_rate,
    colour_changed,
    start_sync,
    target_supports_rgb,
)
from custom_components.fibbers_bridge.const import (
    DEFAULT_RATE_HZ,
    MAX_RATE_HZ,
    MIN_RATE_HZ,
)


def _layer(*colors: tuple[int, int, int]) -> dict:
    """Build a JointSpace-shaped payload from a flat list of RGB tuples."""
    pixels = {str(i): {"r": r, "g": g, "b": b} for i, (r, g, b) in enumerate(colors)}
    return {"layer1": {"left": pixels}}


# --- average_zones -------------------------------------------------------------


def test_average_zones_single_pixel() -> None:
    assert average_zones(_layer((10, 20, 30))) == (10, 20, 30)


def test_average_zones_means_every_led_across_sides() -> None:
    payload = {
        "layer1": {
            "left": {"0": {"r": 0, "g": 0, "b": 0}},
            "right": {"0": {"r": 100, "g": 200, "b": 40}},
        }
    }
    # (0+100)/2, (0+200)/2, (0+40)/2
    assert average_zones(payload) == (50, 100, 20)


def test_average_zones_rounds() -> None:
    assert average_zones(_layer((0, 0, 0), (1, 1, 1))) == (0, 0, 0)  # 0.5 → 0 bankers? round
    assert average_zones(_layer((0, 0, 0), (3, 3, 3))) == (2, 2, 2)  # 1.5 → 2


def test_average_zones_none_and_empty_return_none() -> None:
    assert average_zones(None) is None
    assert average_zones({}) is None
    assert average_zones({"layer1": {}}) is None  # Ambilight off / non-Ambilight set


def test_average_zones_skips_malformed_pixels() -> None:
    payload = {
        "layer1": {
            "left": {
                "0": {"r": 10, "g": 10, "b": 10},
                "1": {"r": "nope"},  # malformed → skipped, not a crash
                "2": "garbage",
            }
        }
    }
    assert average_zones(payload) == (10, 10, 10)


# --- colour_changed (dead-band) ------------------------------------------------


def test_colour_changed_first_value_always_sends() -> None:
    assert colour_changed(None, (0, 0, 0)) is True


def test_colour_changed_below_deadband_is_suppressed() -> None:
    assert colour_changed((100, 100, 100), (103, 98, 100), deadband=8) is False


def test_colour_changed_at_or_above_deadband_sends() -> None:
    assert colour_changed((100, 100, 100), (108, 100, 100), deadband=8) is True


# --- clamp_rate ----------------------------------------------------------------


def test_clamp_rate_bounds_and_default() -> None:
    assert clamp_rate(0) == MIN_RATE_HZ
    assert clamp_rate(999) == MAX_RATE_HZ
    assert clamp_rate("nonsense") == DEFAULT_RATE_HZ
    assert clamp_rate(6) == 6


# --- lifecycle guards ----------------------------------------------------------


def test_target_supports_rgb(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "light.rgb", "on", {"supported_color_modes": ["rgb", "brightness"]}
    )
    hass.states.async_set(
        "light.dimmable", "on", {"supported_color_modes": ["brightness"]}
    )
    assert target_supports_rgb(hass, "light.rgb") is True
    assert target_supports_rgb(hass, "light.dimmable") is False
    assert target_supports_rgb(hass, "light.missing") is False


async def test_start_sync_unknown_source_raises(hass: HomeAssistant) -> None:
    hass.states.async_set("light.rgb", "on", {"supported_color_modes": ["rgb"]})
    with pytest.raises(ServiceValidationError, match="not set up"):
        await start_sync(hass, entry_id="nope", target="light.rgb")


async def test_start_sync_non_rgb_target_raises(hass: HomeAssistant) -> None:
    # Register a fake source so we get past the source check to the target check.
    hass.data.setdefault("fibbers_bridge", {}).setdefault("sources", {})[
        "src"
    ] = object()
    hass.states.async_set(
        "light.dimmable", "on", {"supported_color_modes": ["brightness"]}
    )
    with pytest.raises(ServiceValidationError, match="RGB colour"):
        await start_sync(hass, entry_id="src", target="light.dimmable")
