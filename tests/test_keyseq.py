"""Pure key-sequence rules — the logic that makes a macro reliable."""

from __future__ import annotations

import pytest

from custom_components.fibbers_bridge.keyseq import (
    collapse_repeats,
    expand_steps,
    saturate_steps,
    with_anchor,
)


def test_saturate_pins_then_steps():
    # select item 2 of a 5-long list, going down: pin up (5+3), then down x2
    assert saturate_steps("down", 2, 5, margin=3) == [
        {"key": "CursorUp", "repeat": 8},
        {"key": "CursorDown", "repeat": 2},
    ]


def test_saturate_index_zero_still_saturates():
    assert saturate_steps("down", 0, 5) == [{"key": "CursorUp", "repeat": 8}]


def test_saturate_rejects_out_of_range():
    with pytest.raises(ValueError):
        saturate_steps("down", 5, 5)
    with pytest.raises(ValueError):
        saturate_steps("down", -1, 5)


def test_expand_flattens_strings_and_repeats():
    keys = [s["key"] for s in expand_steps(["Home", {"key": "CursorUp", "repeat": 2}])]
    assert keys == ["Home", "CursorUp", "CursorUp"]


def test_expand_select_expands_saturation():
    out = expand_steps([{"select": {"direction": "down", "index": 1, "length": 5, "margin": 3}}])
    keys = [s["key"] for s in out]
    assert keys == ["CursorUp"] * 8 + ["CursorDown"]


def test_expand_resolves_timings():
    [home] = expand_steps(["Home"])
    assert home["wait_ms"] == 3000  # Home settles longest
    [confirm] = expand_steps(["Confirm"])
    assert confirm["wait_ms"] == 1200
    [cursor] = expand_steps(["CursorUp"], {"delay_ms": 600})
    assert cursor["wait_ms"] == 600


def test_with_anchor_prepends_and_is_idempotent():
    once = with_anchor(["Home"])
    assert once[:3] == [{"key": "Back"}, {"key": "Back"}, {"key": "Back"}]
    assert with_anchor(once) == once


def test_collapse_repeats():
    assert collapse_repeats(["Up", "Up", "Down", "Up"]) == [
        {"key": "Up", "repeat": 2},
        {"key": "Down", "repeat": 1},
        {"key": "Up", "repeat": 1},
    ]
