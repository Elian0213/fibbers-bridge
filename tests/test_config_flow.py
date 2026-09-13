"""Config flow tests.

Covers the two things a user does: add the base bridge, and pair a Philips
Ambilight TV. The pairing path mocks `haphilipsjs.PhilipsTV` so the PIN handshake
is exercised without a real TV — the same handshake core's philips_js flow uses.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PIN, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.fibbers_bridge.const import CONF_SYSTEM, DOMAIN


def _fake_hub(*, pairing: bool = True) -> MagicMock:
    hub = MagicMock()
    hub.getSystem = AsyncMock()
    hub.setTransport = AsyncMock()
    hub.pairRequest = AsyncMock(return_value={"auth_key": "k", "timestamp": 1})
    hub.pairGrant = AsyncMock(return_value=("user123", "pass456"))
    hub.system = {"name": "Living room TV", "model": "43PUS7608/12"}
    hub.api_version = 6
    hub.secured_transport = True
    hub.pairing_type = "digest_auth_pairing" if pairing else None
    return hub


async def test_add_base_bridge(hass: HomeAssistant) -> None:
    """The menu → bridge path creates the input-less services entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == FlowResultType.MENU

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "bridge"}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Fibbers Bridge"
    assert result["data"] == {}


async def test_pair_philips_tv(hass: HomeAssistant) -> None:
    """Full PIN handshake → an entry carrying host + granted credentials."""
    hub = _fake_hub()
    with patch("haphilipsjs.PhilipsTV", return_value=hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "philips"}
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "philips"

        # Enter the IP → connects → TV requires pairing → PIN form appears.
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.168.1.159"}
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "pair"
        hub.pairRequest.assert_awaited_once()

        # Enter the PIN → grant → entry created.
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PIN: "1234"}
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Ambilight — Living room TV"
    data = result["data"]
    assert data[CONF_HOST] == "192.168.1.159"
    assert data[CONF_USERNAME] == "user123"
    assert data[CONF_PASSWORD] == "pass456"
    assert data[CONF_SYSTEM]["model"] == "43PUS7608/12"


async def test_pair_philips_wrong_pin_shows_error(hass: HomeAssistant) -> None:
    """A rejected PIN re-shows the form with an error rather than aborting."""
    from custom_components.fibbers_bridge.config_flow import PairingInvalidPin

    hub = _fake_hub()
    hub.pairGrant = AsyncMock(side_effect=PairingInvalidPin())
    with patch("haphilipsjs.PhilipsTV", return_value=hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "philips"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.168.1.159"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PIN: "0000"}
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "pair"
    assert result["errors"] == {"base": "invalid_pin"}


async def test_cannot_connect_shows_error(hass: HomeAssistant) -> None:
    """An unreachable TV keeps the user on the host form with a clear error."""
    hub = _fake_hub()
    hub.getSystem = AsyncMock(side_effect=Exception("no route"))
    hub.system = None
    with patch("haphilipsjs.PhilipsTV", return_value=hub):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "philips"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "10.0.0.5"}
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "philips"
    assert result["errors"] == {"base": "cannot_connect"}
