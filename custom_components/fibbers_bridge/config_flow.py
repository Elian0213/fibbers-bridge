"""Config flow for Fibbers Bridge.

Two kinds of entry share this flow:

* the **base bridge** (no data) — registers the reusable services/websocket
  commands. Adding it is a one-click confirm, as before.
* a **Philips Ambilight TV source** (carries host + paired credentials) — reads
  the colours the TV derives from whatever is on screen and lets a light mirror
  them. Pairing is a PIN handshake modelled on core's `philips_js` config flow
  (which is where this JointSpace pairing dance was first written): connect →
  the TV shows a PIN → type it back → store the granted username/password.
"""

from __future__ import annotations

import logging
import platform
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PIN,
    CONF_USERNAME,
)

from .const import (
    API_VERSIONS,
    CONF_API_VERSION,
    CONF_SECURED_TRANSPORT,
    CONF_SYSTEM,
    DOMAIN,
    PAIR_APP_ID,
    PAIR_APP_NAME,
)

_LOGGER = logging.getLogger(__name__)


class FibbersBridgeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Fibbers Bridge."""

    VERSION = 1

    def __init__(self) -> None:
        self._hub: Any = None
        self._pair_state: dict[str, Any] = {}
        self._host: str | None = None

    # --- entry point: pick what to add -----------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user add the base bridge or a Philips Ambilight TV."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["bridge", "philips"],
        )

    async def async_step_bridge(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the single base bridge entry (services + websocket commands)."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="Fibbers Bridge", data={})

    # --- Philips Ambilight TV: connect -----------------------------------------

    async def async_step_philips(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the TV's IP, connect, then pair if the TV requires it."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._host = user_input[CONF_HOST]
            try:
                await self._async_connect(self._host)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(self._host)
                self._abort_if_unique_id_configured()
                if getattr(self._hub, "pairing_type", None) == "digest_auth_pairing":
                    return await self.async_step_pair()
                return self._create_source_entry()

        return self.async_show_form(
            step_id="philips",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            errors=errors,
        )

    async def _async_connect(self, host: str) -> None:
        """Build a client and read /system, trying each supported API version."""
        from haphilipsjs import ConnectionFailure, PhilipsTV  # noqa: PLC0415

        last_err: Exception | None = None
        for api_version in API_VERSIONS:
            hub = PhilipsTV(host, api_version=api_version)
            try:
                await hub.getSystem()
                await hub.setTransport(hub.secured_transport)
            except ConnectionFailure as err:  # pragma: no cover - network dependent
                last_err = err
                continue
            except Exception as err:  # noqa: BLE001
                last_err = err
                continue
            if hub.system:
                self._hub = hub
                return
        _LOGGER.debug("Philips connect failed for %s: %s", host, last_err)
        raise CannotConnect from last_err

    # --- Philips Ambilight TV: PIN handshake -----------------------------------

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form for the PIN the TV is displaying, then grant."""
        errors: dict[str, str] = {}
        if user_input is None:
            try:
                self._pair_state = await self._hub.pairRequest(
                    PAIR_APP_ID,
                    PAIR_APP_NAME,
                    platform.node() or "homeassistant",
                    platform.system() or "Linux",
                    "native",
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Philips pairRequest failed: %s", err)
                return self.async_abort(reason="pairing_failure")
            return self.async_show_form(
                step_id="pair",
                data_schema=vol.Schema({vol.Required(CONF_PIN): str}),
            )

        try:
            username, password = await self._hub.pairGrant(
                self._pair_state, user_input[CONF_PIN]
            )
        except PairingInvalidPin:
            errors["base"] = "invalid_pin"
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Philips pairGrant failed: %s", err)
            return self.async_abort(reason="pairing_failure")
        else:
            self._hub.username = username
            self._hub.password = password
            return self._create_source_entry(username, password)

        return self.async_show_form(
            step_id="pair",
            data_schema=vol.Schema({vol.Required(CONF_PIN): str}),
            errors=errors,
        )

    # --- create ----------------------------------------------------------------

    def _create_source_entry(
        self, username: str | None = None, password: str | None = None
    ) -> ConfigFlowResult:
        system = getattr(self._hub, "system", None) or {}
        name = system.get("name") or f"Ambilight ({self._host})"
        data: dict[str, Any] = {
            CONF_HOST: self._host,
            CONF_API_VERSION: getattr(self._hub, "api_version", 6),
            CONF_SECURED_TRANSPORT: getattr(self._hub, "secured_transport", True),
            CONF_SYSTEM: system,
        }
        if username is not None:
            data[CONF_USERNAME] = username
            data[CONF_PASSWORD] = password
        return self.async_create_entry(title=f"Ambilight — {name}", data=data)


class CannotConnect(Exception):
    """We couldn't reach the TV's JointSpace API."""


try:  # ha-philipsjs raises this on a wrong PIN; degrade if the name ever moves.
    from haphilipsjs import PairingFailure as PairingInvalidPin
except Exception:  # noqa: BLE001 - keep import-safe without the dependency

    class PairingInvalidPin(Exception):  # type: ignore[no-redef]
        """Wrong PIN entered during pairing."""
