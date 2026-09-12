"""Config flow for Fibbers Bridge — a single, input-less instance.

The bridge has nothing to configure; the flow exists only so it can be added from
Settings → Devices & Services (which triggers `async_setup_entry`). `manifest.json`
sets `single_config_entry: true`, so Home Assistant blocks a second instance.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class FibbersBridgeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Fibbers Bridge."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm, then create the single entry."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            return self.async_create_entry(title="Fibbers Bridge", data={})
        return self.async_show_form(step_id="user")
