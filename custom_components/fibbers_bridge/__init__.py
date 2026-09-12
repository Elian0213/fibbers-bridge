"""Fibbers Bridge — a generic backend for Home Assistant cards.

The bridge exposes low-level device capabilities that Home Assistant doesn't
surface natively, as reusable **services** (for automations and card
`tap_action: call-service`) and low-latency **websocket commands** (for custom
cards). Any dashboard — Fibbers or third-party — can call them; the contract is
documented in docs/API.md and kept additive so it stays stable.

First capability: **Apple TV native touch** over pyatv's Companion protocol
(`atv.touch.swipe/action/click`). This reproduces the physical Siri Remote's
touch surface — e.g. a continuous timeline scrub in apps like Netflix that report
no position to Home Assistant, which `media_player.media_seek` therefore cannot do.

We reach the live pyatv object through the core `apple_tv` integration's config
entry (`hass.data["apple_tv"][entry_id].atv`). That is an internal API and may
shift between Home Assistant releases, so every access is guarded and fails with a
clear error instead of raising.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .const import APPLE_TV_DOMAIN, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Companion touch coordinates are 0–1000 on both axes (normalised, not pixels).
_COORD = vol.All(vol.Coerce(int), vol.Range(min=0, max=1000))
_DURATION = vol.All(vol.Coerce(int), vol.Range(min=1, max=10000))

_SWIPE_FIELDS = {
    vol.Required("device_id"): cv.string,
    vol.Required("start_x"): _COORD,
    vol.Required("start_y"): _COORD,
    vol.Required("end_x"): _COORD,
    vol.Required("end_y"): _COORD,
    vol.Optional("duration_ms", default=500): _DURATION,
}
_TOUCH_FIELDS = {
    vol.Required("device_id"): cv.string,
    vol.Required("x"): _COORD,
    vol.Required("y"): _COORD,
    vol.Required("mode"): vol.In(["press", "hold", "release"]),
}
_CLICK_FIELDS = {
    vol.Required("device_id"): cv.string,
    vol.Optional("action", default="single"): vol.In(["single", "double", "hold"]),
}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Register the bridge's services and websocket commands (once)."""
    store = hass.data.setdefault(DOMAIN, {})
    if store.get("registered"):
        return True

    async def _svc_swipe(call: ServiceCall) -> None:
        await _do_swipe(_resolve_atv(hass, call.data["device_id"]), call.data)

    async def _svc_touch(call: ServiceCall) -> None:
        await _do_touch(_resolve_atv(hass, call.data["device_id"]), call.data)

    async def _svc_click(call: ServiceCall) -> None:
        await _do_click(_resolve_atv(hass, call.data["device_id"]), call.data)

    hass.services.async_register(
        DOMAIN, "atv_swipe", _svc_swipe, schema=vol.Schema(_SWIPE_FIELDS)
    )
    hass.services.async_register(
        DOMAIN, "atv_touch", _svc_touch, schema=vol.Schema(_TOUCH_FIELDS)
    )
    hass.services.async_register(
        DOMAIN, "atv_click", _svc_click, schema=vol.Schema(_CLICK_FIELDS)
    )

    websocket_api.async_register_command(hass, _ws_swipe)
    websocket_api.async_register_command(hass, _ws_touch)

    store["registered"] = True
    _LOGGER.debug("Fibbers Bridge: services + websocket commands registered")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Keep the global services/commands registered across a config reload."""
    return True


# --- Apple TV resolution -------------------------------------------------------


def _resolve_atv(hass: HomeAssistant, device_id: str) -> Any:
    """Return the connected pyatv object for an `apple_tv` device_id, or raise.

    Walks device_registry → the device's `apple_tv` config entries →
    `hass.data["apple_tv"][entry_id].atv`. Raises ServiceValidationError with a
    user-facing message when the device, integration, or live connection is absent.
    """
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        raise ServiceValidationError(f"Unknown device_id: {device_id}")

    managers = hass.data.get(APPLE_TV_DOMAIN)
    if not managers:
        raise ServiceValidationError(
            "The Apple TV integration is not set up in Home Assistant."
        )

    for entry_id in device.config_entries:
        manager = managers.get(entry_id)
        atv = getattr(manager, "atv", None) if manager is not None else None
        if atv is not None:
            return atv

    raise ServiceValidationError(
        f"No connected Apple TV for device {device_id} — is it powered on and "
        "paired via the Companion protocol (tvOS 15+)?"
    )


def _require_feature(atv: Any, feature_name: str) -> None:
    """Best-effort feature gate. No-op if the pyatv version lacks the name/API,
    so a genuinely-unsupported call still surfaces as a clean runtime error."""
    try:
        from pyatv.const import FeatureName, FeatureState  # noqa: PLC0415
    except ImportError:  # pragma: no cover - pyatv is a manifest requirement
        return
    feature = getattr(FeatureName, feature_name, None)
    if feature is None:
        return
    try:
        available = atv.features.in_state(FeatureState.Available, feature)
    except Exception:  # noqa: BLE001 - feature API differs across pyatv versions
        return
    if not available:
        raise ServiceValidationError(
            f"This Apple TV does not support {feature_name} "
            "(needs the Companion protocol / tvOS 15+)."
        )


# --- pyatv touch calls ---------------------------------------------------------


async def _do_swipe(atv: Any, data: dict[str, Any]) -> None:
    _require_feature(atv, "Swipe")
    try:
        await atv.touch.swipe(
            data["start_x"],
            data["start_y"],
            data["end_x"],
            data["end_y"],
            data.get("duration_ms", 500),
        )
    except Exception as err:  # noqa: BLE001 - surface pyatv errors cleanly
        raise HomeAssistantError(f"Apple TV swipe failed: {err}") from err


async def _do_touch(atv: Any, data: dict[str, Any]) -> None:
    from pyatv.const import TouchAction  # noqa: PLC0415

    _require_feature(atv, "TouchAction")
    mode = {
        "press": TouchAction.Press,
        "hold": TouchAction.Hold,
        "release": TouchAction.Release,
    }[data["mode"]]
    try:
        await atv.touch.action(data["x"], data["y"], mode)
    except Exception as err:  # noqa: BLE001
        raise HomeAssistantError(f"Apple TV touch failed: {err}") from err


async def _do_click(atv: Any, data: dict[str, Any]) -> None:
    from pyatv.const import InputAction  # noqa: PLC0415

    _require_feature(atv, "TouchClick")
    action = {
        "single": InputAction.SingleTap,
        "double": InputAction.DoubleTap,
        "hold": InputAction.Hold,
    }[data.get("action", "single")]
    try:
        await atv.touch.click(action)
    except Exception as err:  # noqa: BLE001
        raise HomeAssistantError(f"Apple TV click failed: {err}") from err


# --- websocket commands (low-latency card path) --------------------------------


@websocket_api.websocket_command(
    {
        vol.Required("type"): "fibbers_bridge/atv_swipe",
        **_SWIPE_FIELDS,
    }
)
@websocket_api.async_response
async def _ws_swipe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Stream a swipe from a custom card (see docs/API.md)."""
    try:
        await _do_swipe(_resolve_atv(hass, msg["device_id"]), msg)
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "fibbers_bridge_error", str(err))
        return
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "fibbers_bridge/atv_touch",
        **_TOUCH_FIELDS,
    }
)
@websocket_api.async_response
async def _ws_touch(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Stream a press/hold/release from a custom card (see docs/API.md)."""
    try:
        await _do_touch(_resolve_atv(hass, msg["device_id"]), msg)
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "fibbers_bridge_error", str(err))
        return
    connection.send_result(msg["id"], {"ok": True})
