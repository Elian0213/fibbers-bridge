"""Pure key-sequence maths — saturate-then-step, expansion, anchoring, collapse.

No I/O and no Home Assistant imports, so the rules that make a macro reliable are
unit-testable on their own.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .const import (
    _OPPOSITE,
    DEFAULT_KEY_DELAY_MS,
    DIRECTIONS,
    KEY_BACK,
    KEY_HOME,
    PER_KEY_SETTLE_MS,
    HOME_SETTLE_MS,
)

Step = str | Mapping[str, Any]

_ANCHOR: list[dict[str, Any]] = [
    {"key": KEY_BACK},
    {"key": KEY_BACK},
    {"key": KEY_BACK},
    {"key": KEY_HOME, "settle_ms": HOME_SETTLE_MS},
]


def saturate_steps(
    direction: str, index: int, length: int, margin: int = 3
) -> list[dict[str, Any]]:
    """Pin a list to one end, then step `index` the other way.

    Converts "select item N of a list from an unknown cursor position" into an
    absolute address: press the opposite direction more times than the list is
    long (lists clamp), then step exactly `index`.
    """
    if length <= 0:
        raise ValueError("length must be positive")
    if index < 0 or index >= length:
        raise ValueError(f"index {index} out of range for a list of {length}")
    key = DIRECTIONS.get(direction)
    if key is None:
        raise ValueError(f"unknown direction: {direction}")
    steps = [{"key": _OPPOSITE[key], "repeat": length + margin}]
    if index:
        steps.append({"key": key, "repeat": index})
    return steps


def _step_key(step: Step) -> str | None:
    if isinstance(step, str):
        return step
    if isinstance(step, Mapping):
        return step.get("key")
    return None


def _resolve_wait(key: str, overrides: Mapping[str, Any], defaults: Mapping[str, Any]) -> int:
    """How long to pause after a key: explicit > screen-changer default > delay."""
    wait = overrides.get("settle_ms")
    if wait is None and key in PER_KEY_SETTLE_MS:
        wait = defaults.get("settle_ms") or PER_KEY_SETTLE_MS[key]
    if wait is None:
        wait = overrides.get("delay_ms", defaults.get("delay_ms", DEFAULT_KEY_DELAY_MS))
    return int(wait)


def _key_step(key: str, overrides: Mapping[str, Any], defaults: Mapping[str, Any]) -> dict[str, Any]:
    step = {"key": key, "wait_ms": _resolve_wait(key, overrides, defaults)}
    if "hold_ms" in overrides:
        step["hold_ms"] = int(overrides["hold_ms"])
    return step


def expand_steps(steps: list[Step], defaults: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Flatten strings / {key,repeat,...} / {select:{...}} into timed key steps."""
    defaults = defaults or {}
    out: list[dict[str, Any]] = []
    for step in steps:
        if isinstance(step, str):
            out.append(_key_step(step, {}, defaults))
        elif isinstance(step, Mapping) and "select" in step:
            sel = step["select"]
            for s in saturate_steps(
                sel["direction"], int(sel["index"]), int(sel["length"]), int(sel.get("margin", 3))
            ):
                out.extend(_key_step(s["key"], {}, defaults) for _ in range(s["repeat"]))
        elif isinstance(step, Mapping) and "key" in step:
            for _ in range(max(1, int(step.get("repeat", 1)))):
                out.append(_key_step(step["key"], step, defaults))
        else:
            raise ValueError(f"a step needs a key or a select: {step!r}")
    return out


def starts_with_anchor(steps: list[Step]) -> bool:
    return len(steps) >= 4 and [_step_key(s) for s in steps[:4]] == [
        KEY_BACK,
        KEY_BACK,
        KEY_BACK,
        KEY_HOME,
    ]


def with_anchor(steps: list[Step]) -> list[Step]:
    """Prepend Back×3 → Home so a sequence starts from a known screen. Idempotent."""
    steps = list(steps)
    return steps if starts_with_anchor(steps) else [*_ANCHOR, *steps]


def collapse_repeats(keys: list[str]) -> list[dict[str, Any]]:
    """Consecutive identical keys → {key, repeat}."""
    out: list[dict[str, Any]] = []
    for key in keys:
        if out and out[-1]["key"] == key:
            out[-1]["repeat"] += 1
        else:
            out.append({"key": key, "repeat": 1})
    return out
