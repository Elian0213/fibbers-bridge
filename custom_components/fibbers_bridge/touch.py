"""Per-device sequencing for Apple TV native touch.

Every websocket message runs in its own task, and nothing used to order them:
overlapping `atv_swipe` calls interleaved their press/hold/release streams, a
stalled Companion connection piled holds up behind it at ~30 Hz, and a failure
mid-gesture left the touch pressed on the Apple TV. A `TouchLane` per device fixes
all three:

- one lock, so phases reach pyatv in arrival order (asyncio.Lock is FIFO, and the
  handlers reach `run` without awaiting anything first, so arrival = acquire order);
- hold coalescing: while a hold is already queued, a newer one only updates the
  coordinates the queued one will send — only the latest finger position matters;
- a timeout on every pyatv call, and a best-effort release when a press/hold
  fails or a pressed touch goes quiet for `STALE_S`.

Pure asyncio, no Home Assistant or pyatv imports, so it is unit-testable alone.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging

_LOGGER = logging.getLogger(__name__)

CALL_TIMEOUT_S = 3.0
STALE_S = 5.0

# send(mode, x, y): perform one touch phase against the live pyatv object.
Sender = Callable[[str, int, int], Awaitable[None]]


class TouchLane:
    """Serialises one Apple TV's touch traffic. See the module docstring."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._hold_queued = False
        self._latest = (500, 500)
        self._pressed = False
        self._watchdog: asyncio.TimerHandle | None = None

    async def touch(self, send: Sender, mode: str, x: int, y: int) -> None:
        """Apply one press/hold/release phase, in order, coalescing queued holds."""
        self._latest = (x, y)
        if mode == "hold":
            if self._hold_queued:
                return  # the hold already waiting will pick up these coordinates
            self._hold_queued = True
        async with self._lock:
            if mode == "hold":
                self._hold_queued = False
                if not self._pressed:
                    return  # released (or failed) while queued — never re-press
                x, y = self._latest
            try:
                async with asyncio.timeout(CALL_TIMEOUT_S):
                    await send(mode, x, y)
            except Exception:
                if mode == "release":
                    self._set_pressed(False, send)
                else:  # a failed press may still have landed on the TV
                    await self._safety_release(send)
                raise
            self._set_pressed(mode != "release", send)

    async def exclusive(self, call: Callable[[], Awaitable[None]]) -> None:
        """Run a self-contained gesture (a whole swipe) with the lane held."""
        async with self._lock:
            async with asyncio.timeout(CALL_TIMEOUT_S + 10):
                await call()

    def cancel(self) -> None:
        """Drop the watchdog (integration unload)."""
        if self._watchdog is not None:
            self._watchdog.cancel()
            self._watchdog = None

    def _set_pressed(self, pressed: bool, send: Sender) -> None:
        self._pressed = pressed
        self.cancel()
        if pressed:
            loop = asyncio.get_running_loop()
            self._watchdog = loop.call_later(
                STALE_S, lambda: loop.create_task(self._stale_release(send))
            )

    async def _stale_release(self, send: Sender) -> None:
        self._watchdog = None
        if not self._pressed:
            return
        _LOGGER.debug("Fibbers Bridge: releasing a touch left pressed for %ss", STALE_S)
        async with self._lock:
            if self._pressed:
                await self._safety_release(send)

    async def _safety_release(self, send: Sender) -> None:
        self._set_pressed(False, send)
        x, y = self._latest
        try:
            async with asyncio.timeout(CALL_TIMEOUT_S):
                await send("release", x, y)
        except Exception:  # noqa: BLE001 - best effort; the original error wins
            _LOGGER.debug("Fibbers Bridge: safety release failed", exc_info=True)


def lane_for(store: dict, device_id: str) -> TouchLane:
    """The device's lane, created on first use under `store["touch_lanes"]`."""
    lanes: dict[str, TouchLane] = store.setdefault("touch_lanes", {})
    lane = lanes.get(device_id)
    if lane is None:
        lane = lanes[device_id] = TouchLane()
    return lane
