"""Macro argument validation happens before any key is sent."""

from __future__ import annotations

import pytest

from homeassistant.exceptions import ServiceValidationError

from custom_components.fibbers_bridge.macros import _validate_args

_SPEC = {"index": {"type": "int", "min": 0, "max": 4}}


def test_in_range_arg_passes():
    assert _validate_args(_SPEC, {"index": 2}) == {"index": 2}


def test_out_of_range_arg_rejected():
    with pytest.raises(ServiceValidationError):
        _validate_args(_SPEC, {"index": 5})


def test_missing_arg_rejected():
    with pytest.raises(ServiceValidationError):
        _validate_args(_SPEC, {})
