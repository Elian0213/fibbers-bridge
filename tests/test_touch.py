"""TouchLane: ordering, hold coalescing, time-boxing and the safety release."""

from __future__ import annotations

import asyncio

import pytest

from custom_components.fibbers_bridge import touch
from custom_components.fibbers_bridge.touch import TouchLane


class _FakeTouch:
    """Records phases; `gate` lets a test stall the 'connection' mid-gesture."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []
        self.gate: asyncio.Event | None = None
        self.fail_on: str | None = None

    async def send(self, mode: str, x: int, y: int) -> None:
        if self.gate is not None:
            await self.gate.wait()
        self.calls.append((mode, x, y))
        if mode == self.fail_on:
            raise RuntimeError("companion dropped")


async def test_phases_arrive_in_order() -> None:
    lane, tv = TouchLane(), _FakeTouch()
    await asyncio.gather(
        lane.touch(tv.send, "press", 100, 500),
        lane.touch(tv.send, "hold", 200, 500),
        lane.touch(tv.send, "release", 300, 500),
    )
    assert [c[0] for c in tv.calls] == ["press", "hold", "release"]


async def test_queued_holds_coalesce_to_the_latest_position() -> None:
    lane, tv = TouchLane(), _FakeTouch()
    await lane.touch(tv.send, "press", 0, 500)
    tv.gate = asyncio.Event()
    tasks = [
        asyncio.create_task(lane.touch(tv.send, "hold", x, 500))
        for x in (100, 200, 300, 400)
    ]
    await asyncio.sleep(0)
    tv.gate.set()
    await asyncio.gather(*tasks)
    holds = [c for c in tv.calls if c[0] == "hold"]
    # the first hold was already in flight; the other three collapse into one
    assert holds == [("hold", 100, 500), ("hold", 400, 500)]
    await lane.touch(tv.send, "release", 400, 500)


async def test_failed_hold_releases_the_touch() -> None:
    lane, tv = TouchLane(), _FakeTouch()
    await lane.touch(tv.send, "press", 0, 500)
    tv.fail_on = "hold"
    with pytest.raises(RuntimeError):
        await lane.touch(tv.send, "hold", 250, 500)
    assert tv.calls[-1] == ("release", 250, 500)
    # later holds of the dead gesture must not re-press the surface
    tv.fail_on = None
    await lane.touch(tv.send, "hold", 300, 500)
    assert tv.calls[-1] == ("release", 250, 500)


async def test_stalled_call_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(touch, "CALL_TIMEOUT_S", 0.01)
    lane, tv = TouchLane(), _FakeTouch()
    tv.gate = asyncio.Event()  # never set: the connection hangs
    with pytest.raises(TimeoutError):
        await lane.touch(tv.send, "press", 0, 500)


async def test_quiet_press_is_released_by_the_watchdog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(touch, "STALE_S", 0.01)
    lane, tv = TouchLane(), _FakeTouch()
    await lane.touch(tv.send, "press", 120, 480)
    await asyncio.sleep(0.05)
    assert tv.calls[-1] == ("release", 120, 480)
