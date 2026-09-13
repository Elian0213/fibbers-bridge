"""Send remote key sequences to the TV, server-side with exact timing.

Prefers the core `philips_js` remote (`remote.send_command`) when that integration
is set up for the same host — that's the transport proven to work today — and
falls back to the bridge's own paired ha-philipsjs client.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DEFAULT_KEY_DELAY_MS, PHILIPS_JS_DOMAIN
from .keyseq import expand_steps, with_anchor

if TYPE_CHECKING:
    from .ambilight import AmbilightSource

_LOGGER = logging.getLogger(__name__)


def _philips_js_remote(hass: HomeAssistant, host: str) -> str | None:
    """A philips_js `remote.*` entity for this host, if that integration owns one."""
    registry = er.async_get(hass)
    for entity in registry.entities.values():
        if entity.domain != "remote" or entity.platform != PHILIPS_JS_DOMAIN:
            continue
        entry = hass.config_entries.async_get_entry(entity.config_entry_id or "")
        if entry and entry.data.get(CONF_HOST) == host:
            return entity.entity_id
    return None


async def _send_one(
    hass: HomeAssistant, source: AmbilightSource, remote_entity: str | None, key: str
) -> None:
    if remote_entity:
        await hass.services.async_call(
            "remote",
            "send_command",
            {"entity_id": remote_entity, "command": [key]},
            blocking=True,
        )
        return
    await source.ensure_transport()
    await source.client.sendKey(key)


async def send_keys(
    hass: HomeAssistant,
    source: AmbilightSource,
    steps: list[Any],
    *,
    delay_ms: int = DEFAULT_KEY_DELAY_MS,
    settle_ms: int | None = None,
    anchor: bool = False,
) -> dict[str, Any]:
    """Run a key sequence; return per-key status and total elapsed."""
    raw = with_anchor(steps) if anchor else list(steps)
    defaults: dict[str, Any] = {"delay_ms": delay_ms}
    if settle_ms is not None:
        defaults["settle_ms"] = settle_ms
    expanded = expand_steps(raw, defaults)

    remote_entity = _philips_js_remote(hass, source.host)
    results: list[dict[str, Any]] = []
    started = time.monotonic()
    for step in expanded:
        key = step["key"]
        began = time.monotonic()
        status = "ok"
        try:
            await _send_one(hass, source, remote_entity, key)
        except Exception as err:  # noqa: BLE001 - report the failing key, keep going
            status = f"error: {err}"
            _LOGGER.debug("send_keys %s failed: %s", key, err)
        results.append(
            {"key": key, "status": status, "elapsed_ms": round((time.monotonic() - began) * 1000)}
        )
        await asyncio.sleep(step["wait_ms"] / 1000)

    return {
        "elapsed_ms": round((time.monotonic() - started) * 1000),
        "transport": "philips_js" if remote_entity else "haphilipsjs",
        "results": results,
    }
