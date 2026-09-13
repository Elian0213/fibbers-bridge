"""Diagnostics for a Philips Ambilight source.

Download this from the device page to see, at a glance, whether the bridge can
reach the TV, what colour it last read, and how the running sync is faring —
without turning on debug logging. Credentials are redacted.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import DOMAIN

TO_REDACT = {CONF_USERNAME, CONF_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    from homeassistant.components.diagnostics import async_redact_data  # noqa: PLC0415

    store = hass.data.get(DOMAIN, {})
    source = store.get("sources", {}).get(entry.entry_id)

    syncs = [
        {
            "target": target,
            "active": sync.active,
            "rate": sync.rate,
            "mode": sync.mode,
            "sent": sync.sent_count,
            "errors": sync.error_count,
        }
        for target, sync in store.get("syncs", {}).items()
        if source is not None and sync.source.entry_id == entry.entry_id
    ]

    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "source": None
        if source is None
        else {
            "host": source.host,
            "name": source.name,
            "model": source.model,
            "available": source.available,
            "last_color": list(source.last_color) if source.last_color else None,
            "last_error": source.last_error,
        },
        "syncs": syncs,
    }
