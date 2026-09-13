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
entry (`entry.runtime_data.atv`, with a fallback to the pre-2024.6
`hass.data["apple_tv"][entry_id].atv`). That is an internal API and may shift
between Home Assistant releases, so every access is guarded and fails with a
clear error instead of raising.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .ambilight import (
    AmbilightSource,
    add_subscriber,
    get_source,
    list_sources,
    snapshot,
    start_sync,
    stop_all_syncs,
    stop_sync,
)
from . import macros, probe, remote, tvsettings
from .jointspace import JointSpaceError
from .tvprobe import probe_capabilities
from .const import (
    AMBILIGHT_MODES,
    APPLE_TV_DOMAIN,
    DEFAULT_KEY_DELAY_MS,
    DEFAULT_MODE,
    DEFAULT_RATE_HZ,
    DOMAIN,
    MAX_RATE_HZ,
    MIN_RATE_HZ,
    PROBE_OUTCOMES,
)

_PLATFORMS = ["sensor"]

_AMBILIGHT_START_FIELDS = {
    vol.Required("entry_id"): cv.string,
    vol.Required("target"): cv.entity_id,
    vol.Optional("rate", default=DEFAULT_RATE_HZ): vol.All(
        vol.Coerce(int), vol.Range(min=MIN_RATE_HZ, max=MAX_RATE_HZ)
    ),
    vol.Optional("mode", default=DEFAULT_MODE): vol.In(AMBILIGHT_MODES),
}
_AMBILIGHT_STOP_FIELDS = {vol.Required("target"): cv.entity_id}
_AMBILIGHT_PROBE_FIELDS = {
    vol.Required("entry_id"): cv.string,
    vol.Optional("mode", default=DEFAULT_MODE): vol.In(AMBILIGHT_MODES),
}
_TV_PROBE_FIELDS = {
    vol.Required("entry_id"): cv.string,
    vol.Optional("include_raw", default=False): cv.boolean,
}
_TV_SETTINGS_LIST_FIELDS = {
    vol.Required("entry_id"): cv.string,
    vol.Optional("refresh", default=False): cv.boolean,
}
_TV_SETTINGS_GET_FIELDS = {
    vol.Required("entry_id"): cv.string,
    vol.Required("node_ids"): [vol.Coerce(int)],
}
_TV_SETTINGS_SET_FIELDS = {
    vol.Required("entry_id"): cv.string,
    vol.Required("node_id"): vol.Coerce(int),
    vol.Optional("value"): object,  # any JSON scalar/list the node takes
    vol.Optional("data"): dict,
}
_TV_SETTINGS_SWEEP_FIELDS = {
    vol.Required("entry_id"): cv.string,
    vol.Required("start"): vol.Coerce(int),
    vol.Required("end"): vol.Coerce(int),
    vol.Optional("step", default=1): vol.All(vol.Coerce(int), vol.Range(min=1)),
}

# --- key sequences + macros ---
_TV_SEND_KEYS_FIELDS = {
    vol.Required("entry_id"): cv.string,
    vol.Required("keys"): list,
    vol.Optional("delay_ms", default=DEFAULT_KEY_DELAY_MS): vol.Coerce(int),
    vol.Optional("settle_ms"): vol.Coerce(int),
    vol.Optional("anchor"): vol.In(["home"]),
}
_TV_MACRO_FIELDS = {
    vol.Required("entry_id"): cv.string,
    vol.Required("macro"): cv.string,
    vol.Optional("args"): dict,
}
_TV_MACRO_LIST_FIELDS = {vol.Required("entry_id"): cv.string}

# --- probe journal ---
_PROBE_CREATE_FIELDS = {
    vol.Required("name"): cv.string,
    vol.Optional("target"): cv.string,
    vol.Optional("device"): dict,
}
_PROBE_DELETE_FIELDS = {vol.Required("notebook"): cv.string}
_PROBE_FIRE_FIELDS = {
    vol.Required("notebook"): cv.string,
    vol.Required("kind"): vol.In(["remote_key", "service", "http"]),
    vol.Optional("entry_id"): cv.string,
    vol.Optional("target"): cv.string,
    vol.Optional("stimulus", default=dict): dict,
}
_PROBE_ANNOTATE_FIELDS = {
    vol.Required("notebook"): cv.string,
    vol.Optional("id"): cv.string,
    vol.Optional("observation"): cv.string,
    vol.Optional("outcome"): vol.In(PROBE_OUTCOMES),
    vol.Optional("tags"): [cv.string],
}
_PROBE_NOTE_FIELDS = {vol.Required("notebook"): cv.string, vol.Required("text"): cv.string}
_PROBE_EXPORT_FIELDS = {vol.Required("notebook"): cv.string}
_PROBE_PROMOTE_FIELDS = {
    vol.Required("notebook"): cv.string,
    vol.Required("name"): cv.string,
    vol.Optional("entry_ids", default=list): [cv.string],
    vol.Optional("args"): dict,
}

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
    """Register global services/commands, and wire up a Philips source if present.

    Any entry (base bridge or a Philips Ambilight TV) triggers the one-time
    registration of the reusable services and websocket commands. An entry that
    carries a host is additionally a colour source, so we build its client and
    expose a sensor for observability.
    """
    _register_global(hass)

    if entry.data.get(CONF_HOST):
        store = hass.data[DOMAIN]
        store["sources"][entry.entry_id] = AmbilightSource(
            hass, entry.entry_id, entry.data
        )
        await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)
        _LOGGER.debug("Fibbers Bridge: Ambilight source %s ready", entry.data[CONF_HOST])

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Tear down a Philips source; keep the global services across reloads."""
    if entry.data.get(CONF_HOST):
        await stop_all_syncs(hass, entry.entry_id)
        unloaded = await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
        hass.data[DOMAIN]["sources"].pop(entry.entry_id, None)
        return unloaded
    return True


def _register_global(hass: HomeAssistant) -> None:
    """Register services + websocket commands once, idempotently."""
    store = hass.data.setdefault(DOMAIN, {})
    store.setdefault("sources", {})
    store.setdefault("syncs", {})
    store.setdefault("subscribers", set())
    store.setdefault("probe_subscribers", set())
    if store.get("registered"):
        return

    async def _svc_swipe(call: ServiceCall) -> None:
        await _do_swipe(_resolve_atv(hass, call.data["device_id"]), call.data)

    async def _svc_touch(call: ServiceCall) -> None:
        await _do_touch(_resolve_atv(hass, call.data["device_id"]), call.data)

    async def _svc_click(call: ServiceCall) -> None:
        await _do_click(_resolve_atv(hass, call.data["device_id"]), call.data)

    async def _svc_ambilight_start(call: ServiceCall) -> None:
        await start_sync(
            hass,
            entry_id=call.data["entry_id"],
            target=call.data["target"],
            rate=call.data["rate"],
            mode=call.data["mode"],
        )

    async def _svc_ambilight_stop(call: ServiceCall) -> None:
        await stop_sync(hass, call.data["target"])

    async def _svc_ambilight_probe(call: ServiceCall) -> ServiceResponse:
        source = get_source(hass, call.data["entry_id"])
        return await source.probe(call.data["mode"])

    async def _svc_tv_probe_settings(call: ServiceCall) -> ServiceResponse:
        source = get_source(hass, call.data["entry_id"])
        return await probe_capabilities(source, include_raw=call.data["include_raw"])

    async def _svc_tv_settings_list(call: ServiceCall) -> ServiceResponse:
        source = get_source(hass, call.data["entry_id"])
        try:
            return await tvsettings.list_settings(source, refresh=call.data["refresh"])
        except JointSpaceError as err:
            raise HomeAssistantError(str(err)) from err

    async def _svc_tv_settings_get(call: ServiceCall) -> ServiceResponse:
        source = get_source(hass, call.data["entry_id"])
        try:
            current = await tvsettings.read_current(source, call.data["node_ids"])
        except JointSpaceError as err:
            raise HomeAssistantError(str(err)) from err
        return {"nodes": list(current.values())}

    async def _svc_tv_settings_set(call: ServiceCall) -> ServiceResponse:
        source = get_source(hass, call.data["entry_id"])
        try:
            return await tvsettings.write_node(
                source, call.data["node_id"], call.data.get("value"), call.data.get("data")
            )
        except JointSpaceError as err:
            raise HomeAssistantError(str(err)) from err

    async def _svc_tv_settings_sweep(call: ServiceCall) -> ServiceResponse:
        source = get_source(hass, call.data["entry_id"])
        try:
            return await tvsettings.sweep_settings(
                source, call.data["start"], call.data["end"], call.data["step"]
            )
        except JointSpaceError as err:
            raise HomeAssistantError(str(err)) from err

    async def _svc_tv_send_keys(call: ServiceCall) -> ServiceResponse:
        source = get_source(hass, call.data["entry_id"])
        return await remote.send_keys(
            hass,
            source,
            call.data["keys"],
            delay_ms=call.data["delay_ms"],
            settle_ms=call.data.get("settle_ms"),
            anchor=call.data.get("anchor") == "home",
        )

    async def _svc_tv_macro(call: ServiceCall) -> ServiceResponse:
        source = get_source(hass, call.data["entry_id"])
        return await macros.run_macro(hass, source, call.data["macro"], call.data.get("args"))

    async def _svc_tv_macro_list(call: ServiceCall) -> ServiceResponse:
        source = get_source(hass, call.data["entry_id"])
        return {"macros": await macros.list_macros(hass, source)}

    async def _probe(call: ServiceCall) -> probe.ProbeJournal:
        journal = probe.get_journal(hass)
        await journal.ensure_loaded()
        return journal

    async def _svc_probe_create(call: ServiceCall) -> ServiceResponse:
        journal = await _probe(call)
        return journal.create(call.data["name"], call.data.get("target"), call.data.get("device"))

    async def _svc_probe_list(call: ServiceCall) -> ServiceResponse:
        journal = await _probe(call)
        return {"notebooks": journal.list()}

    async def _svc_probe_delete(call: ServiceCall) -> None:
        journal = await _probe(call)
        journal.delete(call.data["notebook"])

    async def _svc_probe_fire(call: ServiceCall) -> ServiceResponse:
        await _probe(call)
        return await probe.fire(
            hass,
            call.data["notebook"],
            kind=call.data["kind"],
            entry_id=call.data.get("entry_id"),
            target=call.data.get("target"),
            stimulus=call.data["stimulus"],
        )

    async def _svc_probe_annotate(call: ServiceCall) -> ServiceResponse:
        journal = await _probe(call)
        return journal.annotate(
            call.data["notebook"],
            call.data.get("id"),
            call.data.get("observation"),
            call.data.get("outcome"),
            call.data.get("tags"),
        )

    async def _svc_probe_note(call: ServiceCall) -> ServiceResponse:
        journal = await _probe(call)
        return journal.note(call.data["notebook"], call.data["text"])

    async def _svc_probe_export(call: ServiceCall) -> ServiceResponse:
        journal = await _probe(call)
        return {"markdown": journal.export(call.data["notebook"])}

    async def _svc_probe_promote(call: ServiceCall) -> ServiceResponse:
        journal = await _probe(call)
        return await journal.promote(
            call.data["notebook"], call.data["entry_ids"], call.data["name"], call.data.get("args")
        )

    hass.services.async_register(
        DOMAIN, "atv_swipe", _svc_swipe, schema=vol.Schema(_SWIPE_FIELDS)
    )
    hass.services.async_register(
        DOMAIN, "atv_touch", _svc_touch, schema=vol.Schema(_TOUCH_FIELDS)
    )
    hass.services.async_register(
        DOMAIN, "atv_click", _svc_click, schema=vol.Schema(_CLICK_FIELDS)
    )
    hass.services.async_register(
        DOMAIN,
        "ambilight_start",
        _svc_ambilight_start,
        schema=vol.Schema(_AMBILIGHT_START_FIELDS),
    )
    hass.services.async_register(
        DOMAIN,
        "ambilight_stop",
        _svc_ambilight_stop,
        schema=vol.Schema(_AMBILIGHT_STOP_FIELDS),
    )
    hass.services.async_register(
        DOMAIN,
        "ambilight_probe",
        _svc_ambilight_probe,
        schema=vol.Schema(_AMBILIGHT_PROBE_FIELDS),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "tv_probe_settings",
        _svc_tv_probe_settings,
        schema=vol.Schema(_TV_PROBE_FIELDS),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "tv_settings_list",
        _svc_tv_settings_list,
        schema=vol.Schema(_TV_SETTINGS_LIST_FIELDS),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "tv_settings_get",
        _svc_tv_settings_get,
        schema=vol.Schema(_TV_SETTINGS_GET_FIELDS),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "tv_settings_set",
        _svc_tv_settings_set,
        schema=vol.Schema(_TV_SETTINGS_SET_FIELDS),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "tv_settings_sweep",
        _svc_tv_settings_sweep,
        schema=vol.Schema(_TV_SETTINGS_SWEEP_FIELDS),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "tv_send_keys",
        _svc_tv_send_keys,
        schema=vol.Schema(_TV_SEND_KEYS_FIELDS),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "tv_macro",
        _svc_tv_macro,
        schema=vol.Schema(_TV_MACRO_FIELDS),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "tv_macro_list",
        _svc_tv_macro_list,
        schema=vol.Schema(_TV_MACRO_LIST_FIELDS),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "probe_notebook_create", _svc_probe_create,
        schema=vol.Schema(_PROBE_CREATE_FIELDS), supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "probe_notebook_list", _svc_probe_list,
        schema=vol.Schema({}), supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "probe_notebook_delete", _svc_probe_delete,
        schema=vol.Schema(_PROBE_DELETE_FIELDS),
    )
    hass.services.async_register(
        DOMAIN, "probe_fire", _svc_probe_fire,
        schema=vol.Schema(_PROBE_FIRE_FIELDS), supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "probe_annotate", _svc_probe_annotate,
        schema=vol.Schema(_PROBE_ANNOTATE_FIELDS), supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "probe_note", _svc_probe_note,
        schema=vol.Schema(_PROBE_NOTE_FIELDS), supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "probe_export", _svc_probe_export,
        schema=vol.Schema(_PROBE_EXPORT_FIELDS), supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "probe_promote", _svc_probe_promote,
        schema=vol.Schema(_PROBE_PROMOTE_FIELDS), supports_response=SupportsResponse.ONLY,
    )

    websocket_api.async_register_command(hass, _ws_swipe)
    websocket_api.async_register_command(hass, _ws_touch)
    websocket_api.async_register_command(hass, _ws_ambilight_subscribe)
    websocket_api.async_register_command(hass, _ws_ambilight_sources)
    websocket_api.async_register_command(hass, _ws_tv_settings_list)
    websocket_api.async_register_command(hass, _ws_tv_settings_get)
    websocket_api.async_register_command(hass, _ws_tv_settings_set)
    websocket_api.async_register_command(hass, _ws_probe_subscribe)
    websocket_api.async_register_command(hass, _ws_probe_fire)
    websocket_api.async_register_command(hass, _ws_probe_annotate)

    store["registered"] = True
    _LOGGER.debug("Fibbers Bridge: services + websocket commands registered")


# --- Apple TV resolution -------------------------------------------------------


def _resolve_atv(hass: HomeAssistant, device_id: str) -> Any:
    """Return the connected pyatv object for an `apple_tv` device_id, or raise.

    Walks device_registry → the device's `apple_tv` config entries →
    `entry.runtime_data.atv` (falling back to the legacy
    `hass.data["apple_tv"][entry_id].atv`). Raises ServiceValidationError with a
    user-facing message when the device, integration, or live connection is absent.
    """
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        raise ServiceValidationError(f"Unknown device_id: {device_id}")

    # Home Assistant 2024.6+ keeps the AppleTVManager on the config entry
    # (`entry.runtime_data`); older cores used `hass.data["apple_tv"][entry_id]`.
    # Both are internal API, so try each and fail with a clear message.
    legacy = hass.data.get(APPLE_TV_DOMAIN)
    if not isinstance(legacy, dict):
        legacy = {}

    entries = hass.config_entries.async_entries(APPLE_TV_DOMAIN)
    if not entries and not legacy:
        raise ServiceValidationError(
            "The Apple TV integration is not set up in Home Assistant."
        )

    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is not None and entry.domain != APPLE_TV_DOMAIN:
            continue
        manager = getattr(entry, "runtime_data", None) if entry is not None else None
        if manager is None:
            manager = legacy.get(entry_id)
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


# --- Ambilight websocket commands (live colour stream + source picker) ---------


@websocket_api.websocket_command(
    {
        vol.Required("type"): "fibbers_bridge/ambilight_subscribe",
        vol.Optional("target"): cv.entity_id,
    }
)
@callback
def _ws_ambilight_subscribe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Stream every ambilight colour update to a card (see docs/API.md).

    Optionally filter to one target light. On subscribe we replay the current
    snapshot so the card renders immediately instead of waiting for the next tick.
    """
    target = msg.get("target")

    @callback
    def _forward(payload: dict[str, Any]) -> None:
        if target is not None and payload.get("target") != target:
            return
        connection.send_message(websocket_api.event_message(msg["id"], payload))

    connection.subscriptions[msg["id"]] = add_subscriber(hass, _forward)
    connection.send_result(msg["id"])
    for snap in snapshot(hass, target):
        connection.send_message(websocket_api.event_message(msg["id"], snap))


@websocket_api.websocket_command(
    {vol.Required("type"): "fibbers_bridge/ambilight_sources"}
)
@callback
def _ws_ambilight_sources(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the paired Philips Ambilight TVs, for the card's source picker."""
    connection.send_result(msg["id"], {"sources": list_sources(hass)})


# --- TV settings websocket commands --------------------------------------------


@websocket_api.websocket_command(
    {
        vol.Required("type"): "fibbers_bridge/tv_settings_list",
        vol.Required("entry_id"): cv.string,
        vol.Optional("refresh", default=False): cv.boolean,
    }
)
@websocket_api.async_response
async def _ws_tv_settings_list(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    try:
        source = get_source(hass, msg["entry_id"])
        result = await tvsettings.list_settings(source, refresh=msg["refresh"])
    except (HomeAssistantError, JointSpaceError) as err:
        connection.send_error(msg["id"], "fibbers_bridge_error", str(err))
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "fibbers_bridge/tv_settings_get",
        vol.Required("entry_id"): cv.string,
        vol.Required("node_ids"): [vol.Coerce(int)],
    }
)
@websocket_api.async_response
async def _ws_tv_settings_get(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    try:
        source = get_source(hass, msg["entry_id"])
        current = await tvsettings.read_current(source, msg["node_ids"])
    except (HomeAssistantError, JointSpaceError) as err:
        connection.send_error(msg["id"], "fibbers_bridge_error", str(err))
        return
    connection.send_result(msg["id"], {"nodes": list(current.values())})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "fibbers_bridge/tv_settings_set",
        vol.Required("entry_id"): cv.string,
        vol.Required("node_id"): vol.Coerce(int),
        vol.Optional("value"): object,
        vol.Optional("data"): dict,
    }
)
@websocket_api.async_response
async def _ws_tv_settings_set(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    try:
        source = get_source(hass, msg["entry_id"])
        result = await tvsettings.write_node(
            source, msg["node_id"], msg.get("value"), msg.get("data")
        )
    except (HomeAssistantError, JointSpaceError) as err:
        connection.send_error(msg["id"], "fibbers_bridge_error", str(err))
        return
    connection.send_result(msg["id"], result)


# --- Probe websocket commands (live journal + fire/annotate) --------------------


@websocket_api.websocket_command(
    {
        vol.Required("type"): "fibbers_bridge/probe_subscribe",
        vol.Required("notebook"): cv.string,
    }
)
@websocket_api.async_response
async def _ws_probe_subscribe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Stream one notebook's entries; replay the existing ones on subscribe."""
    notebook = msg["notebook"]
    journal = probe.get_journal(hass)
    await journal.ensure_loaded()

    @callback
    def _forward(entry: dict[str, Any]) -> None:
        connection.send_message(websocket_api.event_message(msg["id"], entry))

    connection.subscriptions[msg["id"]] = probe.add_probe_subscriber(hass, notebook, _forward)
    connection.send_result(msg["id"])
    try:
        for entry in journal.entries(notebook):
            connection.send_message(websocket_api.event_message(msg["id"], entry))
    except HomeAssistantError:
        pass  # unknown notebook — nothing to replay


@websocket_api.websocket_command(
    {
        vol.Required("type"): "fibbers_bridge/probe_fire",
        vol.Required("notebook"): cv.string,
        vol.Required("kind"): vol.In(["remote_key", "service", "http"]),
        vol.Optional("entry_id"): cv.string,
        vol.Optional("target"): cv.string,
        vol.Optional("stimulus", default=dict): dict,
    }
)
@websocket_api.async_response
async def _ws_probe_fire(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Fire a stimulus and record it — the one-keystroke path for the card."""
    try:
        await probe.get_journal(hass).ensure_loaded()
        entry = await probe.fire(
            hass,
            msg["notebook"],
            kind=msg["kind"],
            entry_id=msg.get("entry_id"),
            target=msg.get("target"),
            stimulus=msg["stimulus"],
        )
    except (HomeAssistantError, JointSpaceError) as err:
        connection.send_error(msg["id"], "fibbers_bridge_error", str(err))
        return
    connection.send_result(msg["id"], entry)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "fibbers_bridge/probe_annotate",
        vol.Required("notebook"): cv.string,
        # `entry_id`, not `id`: the ws envelope reserves `id` for the message seq.
        vol.Optional("entry_id"): cv.string,
        vol.Optional("observation"): cv.string,
        vol.Optional("outcome"): vol.In(PROBE_OUTCOMES),
        vol.Optional("tags"): [cv.string],
    }
)
@websocket_api.async_response
async def _ws_probe_annotate(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Attach an observation/outcome to an entry (defaults to the most recent)."""
    try:
        journal = probe.get_journal(hass)
        await journal.ensure_loaded()
        entry = journal.annotate(
            msg["notebook"],
            msg.get("entry_id"),
            msg.get("observation"),
            msg.get("outcome"),
            msg.get("tags"),
        )
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "fibbers_bridge_error", str(err))
        return
    connection.send_result(msg["id"], entry)
