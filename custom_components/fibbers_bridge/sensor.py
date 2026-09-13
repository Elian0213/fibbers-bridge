"""A small observability sensor per Philips Ambilight source.

The live colour stream runs over websockets (high rate, off the event bus). This
sensor is the low-rate, always-visible counterpart: it shows the last colour the
bridge read as a hex string, with the RGB tuple and health as attributes — handy
in Developer Tools → States and for automations, without the event-bus flood that
made core omit it. It never polls on its own; it only reflects reads a running
sync already made.
"""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .ambilight import AmbilightSource
from .const import DOMAIN, SIGNAL_SOURCE_UPDATE


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the colour sensor for this Philips Ambilight source."""
    source: AmbilightSource = hass.data[DOMAIN]["sources"][entry.entry_id]
    async_add_entities([AmbilightColorSensor(entry, source)])


class AmbilightColorSensor(SensorEntity):
    """Last Ambilight colour read from the TV, as a hex string."""

    _attr_should_poll = False
    _attr_icon = "mdi:television-ambient-light"
    _attr_has_entity_name = True
    _attr_name = "Ambilight colour"

    def __init__(self, entry: ConfigEntry, source: AmbilightSource) -> None:
        self._source = source
        self._attr_unique_id = f"{entry.entry_id}_ambilight_color"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": source.name,
            "manufacturer": "Philips",
            "model": source.model or "Ambilight TV",
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_SOURCE_UPDATE}_{self._source.entry_id}",
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> str | None:
        color = self._source.last_color
        if color is None:
            return None
        return "#{:02x}{:02x}{:02x}".format(*color)

    @property
    def available(self) -> bool:
        return self._source.available

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        color = self._source.last_color
        return {
            "rgb_color": list(color) if color else None,
            "host": self._source.host,
            "last_error": self._source.last_error,
        }
