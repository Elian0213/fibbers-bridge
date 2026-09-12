# Changelog

All notable changes to this project are documented here. This project adheres to
[Semantic Versioning](https://semver.org/).

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
