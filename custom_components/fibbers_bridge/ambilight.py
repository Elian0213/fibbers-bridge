"""Philips Ambilight → RGB light mirroring.

The TV computes, per frame, the colour of every Ambilight LED zone from whatever
is on screen (any HDMI source — a games console included). We read those zones
off the local JointSpace API, average them to a single RGB, and relay that to a
target light. Home Assistant's core `philips_js` integration won't surface these
values, so the bridge reads them itself via ha-philipsjs.

Split into three parts:

* pure helpers (`average_zones`, `colour_changed`) — no I/O, unit-tested;
* `AmbilightSource` — one paired TV, knows how to read a colour and probe;
* `AmbilightSync` — a running loop binding a source to a target light, throttled
  and dead-banded, broadcasting each colour to websocket subscribers.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CONF_API_VERSION,
    CONF_SECURED_TRANSPORT,
    DEFAULT_DEADBAND,
    DEFAULT_MODE,
    DEFAULT_RATE_HZ,
    DOMAIN,
    MAX_RATE_HZ,
    MIN_RATE_HZ,
    MODE_MEASURED,
    RGB_COLOR_MODES,
    SIGNAL_SOURCE_UPDATE,
)

_LOGGER = logging.getLogger(__name__)

RGB = tuple[int, int, int]


# --- pure helpers (no I/O) -----------------------------------------------------


def average_zones(layers: Mapping[str, Any] | None) -> RGB | None:
    """Average every Ambilight LED into one RGB.

    JointSpace returns nested `{"layer1": {"left": {"0": {"r","g","b"}, ...},
    "top": {...}, ...}, ...}`. We walk every layer → side → pixel and take the
    mean of each channel. Returns None when there are no pixels (e.g. Ambilight
    off, or a non-Ambilight set), so callers can distinguish "black" from "no
    data".
    """
    if not layers:
        return None
    r = g = b = 0
    n = 0
    for layer in layers.values():
        if not isinstance(layer, Mapping):
            continue
        for side in layer.values():
            if not isinstance(side, Mapping):
                continue
            for pixel in side.values():
                if not isinstance(pixel, Mapping):
                    continue
                try:
                    r += int(pixel["r"])
                    g += int(pixel["g"])
                    b += int(pixel["b"])
                except (KeyError, TypeError, ValueError):
                    continue
                n += 1
    if n == 0:
        return None
    return (round(r / n), round(g / n), round(b / n))


def colour_changed(old: RGB | None, new: RGB, deadband: int = DEFAULT_DEADBAND) -> bool:
    """True if `new` differs from `old` by at least `deadband` on any channel.

    This is the dead-band that stops us hammering the bulb with sub-perceptible
    changes — the difference between a strip that tracks the screen and one that
    drops off Wi-Fi mid-movie.
    """
    if old is None:
        return True
    return any(abs(a - b) >= deadband for a, b in zip(old, new))


def clamp_rate(rate: Any) -> int:
    """Coerce a requested update rate into the supported Hz range."""
    try:
        value = int(rate)
    except (TypeError, ValueError):
        return DEFAULT_RATE_HZ
    return max(MIN_RATE_HZ, min(MAX_RATE_HZ, value))


def target_supports_rgb(hass: HomeAssistant, entity_id: str) -> bool:
    """Whether a light entity can accept an rgb_color right now."""
    state = hass.states.get(entity_id)
    if state is None:
        return False
    modes = state.attributes.get("supported_color_modes") or []
    return bool(RGB_COLOR_MODES.intersection(modes))


# --- source (one paired TV) ----------------------------------------------------


class AmbilightSource:
    """A single paired Philips TV we can read Ambilight colours from."""

    def __init__(self, hass: HomeAssistant, entry_id: str, data: Mapping[str, Any]):
        self.hass = hass
        self.entry_id = entry_id
        self.host: str = data[CONF_HOST]
        system = data.get("system") or {}
        # A friendly, stable name for logs / the source list / the sensor.
        self.name: str = system.get("name") or f"Philips TV ({self.host})"
        self.model: str | None = system.get("model")
        self._client = _build_client(data)
        self._transport_ready = False
        self.last_color: RGB | None = None
        self.last_error: str | None = None
        self.available: bool = True

    async def _ensure_transport(self) -> None:
        if self._transport_ready:
            return
        # Pin http/https + api version to whatever pairing negotiated; without
        # this the first read can pick the wrong scheme and 403 on a paired TV.
        await self._client.setTransport(self._client.secured_transport)
        self._transport_ready = True

    async def read_color(self, mode: str = DEFAULT_MODE) -> RGB | None:
        """Read the current averaged Ambilight colour, or None if unavailable."""
        try:
            await self._ensure_transport()
            if mode == MODE_MEASURED:
                await self._client.getAmbilightMeasured()
                layers = self._client.ambilight_measured
            else:
                await self._client.getAmbilightProcessed()
                layers = self._client.ambilight_processed
        except Exception as err:  # noqa: BLE001 - network/library errors vary
            self._transport_ready = False
            self.available = False
            self.last_error = str(err)
            _LOGGER.debug("Ambilight read failed for %s: %s", self.host, err)
            return None

        color = average_zones(layers)
        self.available = True
        self.last_error = None
        if color is not None:
            self.last_color = color
            async_dispatcher_send(
                self.hass, f"{SIGNAL_SOURCE_UPDATE}_{self.entry_id}"
            )
        return color

    async def probe(self, mode: str = DEFAULT_MODE) -> dict[str, Any]:
        """One-shot diagnostic read: raw payload + computed colour + topology.

        Surfaced as the `ambilight_probe` service so a user can confirm pairing
        and see live values without wiring up a light first.
        """
        result: dict[str, Any] = {"host": self.host, "name": self.name, "mode": mode}
        try:
            await self._ensure_transport()
            await self._client.getAmbilightTopology()
            result["topology"] = self._client.ambilight_topology
            if mode == MODE_MEASURED:
                await self._client.getAmbilightMeasured()
                layers = self._client.ambilight_measured
            else:
                await self._client.getAmbilightProcessed()
                layers = self._client.ambilight_processed
            result["color"] = average_zones(layers)
            result["raw"] = layers
            result["ok"] = result["color"] is not None
        except Exception as err:  # noqa: BLE001
            self._transport_ready = False
            result["ok"] = False
            result["error"] = str(err)
        return result


def _build_client(data: Mapping[str, Any]):
    """Construct a ha-philipsjs client from stored entry data."""
    from haphilipsjs import PhilipsTV  # noqa: PLC0415 - optional heavy import

    return PhilipsTV(
        data[CONF_HOST],
        api_version=data.get(CONF_API_VERSION, 6),
        secured_transport=data.get(CONF_SECURED_TRANSPORT, True),
        username=data.get(CONF_USERNAME),
        password=data.get(CONF_PASSWORD),
    )


# --- websocket broadcast -------------------------------------------------------
#
# Cards subscribe once and receive every sync's colour; each payload carries the
# target so a card can filter to the light it renders.

Subscriber = Callable[[dict[str, Any]], None]


@callback
def broadcast(hass: HomeAssistant, payload: dict[str, Any]) -> None:
    """Fan a colour update out to all websocket subscribers."""
    subs: set[Subscriber] = hass.data.get(DOMAIN, {}).get("subscribers", set())
    for send in list(subs):
        try:
            send(payload)
        except Exception:  # noqa: BLE001 - a dead connection must not kill others
            subs.discard(send)


# --- sync (source → target loop) -----------------------------------------------


class AmbilightSync:
    """A running mirror: poll a source, relay changed colours to a target light."""

    def __init__(
        self,
        hass: HomeAssistant,
        source: AmbilightSource,
        target: str,
        *,
        rate: int = DEFAULT_RATE_HZ,
        mode: str = DEFAULT_MODE,
        deadband: int = DEFAULT_DEADBAND,
    ):
        self.hass = hass
        self.source = source
        self.target = target
        self.rate = clamp_rate(rate)
        self.mode = mode
        self.deadband = deadband
        self._task: asyncio.Task | None = None
        self._sent: RGB | None = None
        self.sent_count = 0
        self.error_count = 0

    @property
    def active(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.active:
            return
        self._task = self.hass.async_create_background_task(
            self._run(), f"{DOMAIN}_ambilight_{self.target}"
        )
        _LOGGER.debug(
            "Ambilight sync started: %s → %s @ %dHz (%s)",
            self.source.host,
            self.target,
            self.rate,
            self.mode,
        )

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._sent = None
        self._push(None, active=False)
        _LOGGER.debug("Ambilight sync stopped: %s", self.target)

    async def _run(self) -> None:
        interval = 1.0 / self.rate
        while True:
            try:
                color = await self.source.read_color(self.mode)
                if color is not None and colour_changed(self._sent, color, self.deadband):
                    await self._apply(color)
                    self._sent = color
                    self.sent_count += 1
                    self._push(color, active=True)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - keep the loop alive
                self.error_count += 1
                _LOGGER.debug("Ambilight sync tick failed for %s: %s", self.target, err)
            await asyncio.sleep(interval)

    async def _apply(self, color: RGB) -> None:
        await self.hass.services.async_call(
            "light",
            "turn_on",
            {ATTR_ENTITY_ID: self.target, "rgb_color": list(color)},
            blocking=False,
        )

    @callback
    def _push(self, color: RGB | None, *, active: bool) -> None:
        broadcast(
            self.hass,
            {
                "target": self.target,
                "source": self.source.entry_id,
                "source_name": self.source.name,
                "rgb": list(color) if color else None,
                "active": active,
                "available": self.source.available,
                "health": {
                    "sent": self.sent_count,
                    "errors": self.error_count,
                    "last_error": self.source.last_error,
                },
            },
        )


# --- store helpers -------------------------------------------------------------


def _store(hass: HomeAssistant) -> dict[str, Any]:
    store = hass.data.setdefault(DOMAIN, {})
    store.setdefault("sources", {})
    store.setdefault("syncs", {})
    store.setdefault("subscribers", set())
    return store


def get_source(hass: HomeAssistant, entry_id: str) -> AmbilightSource:
    """Return a registered source or raise a clear error."""
    source = _store(hass)["sources"].get(entry_id)
    if source is None:
        raise ServiceValidationError(
            "That Philips Ambilight TV is not set up. Add it via "
            "Settings → Devices & Services → Add Integration → Fibbers Bridge."
        )
    return source


def list_sources(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Sources as plain dicts, for the websocket source picker."""
    return [
        {
            "entry_id": s.entry_id,
            "name": s.name,
            "host": s.host,
            "available": s.available,
        }
        for s in _store(hass)["sources"].values()
    ]


async def start_sync(
    hass: HomeAssistant,
    *,
    entry_id: str,
    target: str,
    rate: int = DEFAULT_RATE_HZ,
    mode: str = DEFAULT_MODE,
) -> AmbilightSync:
    """Start (or restart) a mirror from a source to a target light."""
    source = get_source(hass, entry_id)
    if not target_supports_rgb(hass, target):
        raise ServiceValidationError(
            f"{target} can't accept an RGB colour — pick a light with a colour "
            "mode (rgb / rgbw / hs)."
        )
    syncs: dict[str, AmbilightSync] = _store(hass)["syncs"]
    existing = syncs.get(target)
    if existing is not None:
        await existing.stop()
    sync = AmbilightSync(hass, source, target, rate=rate, mode=mode)
    syncs[target] = sync
    sync.start()
    return sync


async def stop_sync(hass: HomeAssistant, target: str) -> bool:
    """Stop the mirror driving a target light. Returns True if one was running."""
    sync = _store(hass)["syncs"].pop(target, None)
    if sync is None:
        return False
    await sync.stop()
    return True


async def stop_all_syncs(hass: HomeAssistant, entry_id: str | None = None) -> None:
    """Stop every sync (optionally only those bound to one source)."""
    syncs: dict[str, AmbilightSync] = _store(hass)["syncs"]
    for target, sync in list(syncs.items()):
        if entry_id is not None and sync.source.entry_id != entry_id:
            continue
        await sync.stop()
        syncs.pop(target, None)


@callback
def add_subscriber(hass: HomeAssistant, send: Subscriber) -> Callable[[], None]:
    """Register a websocket subscriber; returns an unsubscribe callback."""
    subs: set[Subscriber] = _store(hass)["subscribers"]
    subs.add(send)

    @callback
    def _remove() -> None:
        subs.discard(send)

    return _remove


def snapshot(hass: HomeAssistant, target: str | None = None) -> Iterable[dict[str, Any]]:
    """Current state of running syncs, for a card that just subscribed."""
    syncs: dict[str, AmbilightSync] = _store(hass)["syncs"]
    for tgt, sync in syncs.items():
        if target is not None and tgt != target:
            continue
        yield {
            "target": tgt,
            "source": sync.source.entry_id,
            "source_name": sync.source.name,
            "rgb": list(sync.source.last_color) if sync.source.last_color else None,
            "active": sync.active,
            "available": sync.source.available,
        }
