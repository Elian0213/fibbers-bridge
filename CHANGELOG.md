# Changelog

All notable changes to this project are documented here. This project adheres to
[Semantic Versioning](https://semver.org/).

## [0.1.1] — 2026-09-12

### Fixed

- **Apple TV resolution on Home Assistant 2024.6+.** `_resolve_atv()` only read the
  live pyatv connection from `hass.data["apple_tv"][entry_id]`, but core's `apple_tv`
  integration moved the `AppleTVManager` onto the config entry's `runtime_data` in
  2024.6. On any newer core `hass.data["apple_tv"]` is empty, so every service call
  (`atv_swipe`/`atv_touch`/`atv_click`) failed with *"The Apple TV integration is not
  set up in Home Assistant"* even when it was. We now read `entry.runtime_data` first
  and fall back to the legacy `hass.data` path, so both old and new cores work.

## [0.1.0] — 2026-09-12

The first release: a generic backend, with Apple TV native touch as the first
capability.

### Added

- **Apple TV native touch.** Reusable services `fibbers_bridge.atv_swipe`,
  `fibbers_bridge.atv_touch` and `fibbers_bridge.atv_click`, plus low-latency
  websocket commands `fibbers_bridge/atv_swipe` and `fibbers_bridge/atv_touch`,
  driving the Apple TV's real touch surface over pyatv's Companion protocol
  (`atv.touch.*`, coordinates 0–1000). This reaches capabilities Home Assistant
  doesn't expose — e.g. a continuous timeline scrub in apps like Netflix that
  report no position, which `media_player.media_seek` can't do.
- **Generic, documented contract.** Any card or automation can call the services
  (`tap_action: call-service`) or the websocket commands (custom cards); the API
  is additive-only so it stays stable. See `docs/API.md`.
- **Graceful degradation.** The live Apple TV connection is borrowed from the core
  `apple_tv` integration and every access is guarded + feature-detected, so a
  missing device, un-paired Companion session, or Home Assistant internal change
  surfaces as a clear error instead of a crash.
