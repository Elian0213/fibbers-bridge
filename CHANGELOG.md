# Changelog

All notable changes to this project are documented here. This project adheres to
[Semantic Versioning](https://semver.org/).

## [0.3.0] — 2026-09-13

### Added

- **`fibbers_bridge.tv_probe_settings`.** A read-only capability probe: asks a
  paired Philips TV what its JointSpace API really serves, ignoring what it
  advertises in `jsonfeatures`. Returns the HTTP status of each endpoint, so
  *not implemented* (404), *refused* (401/403) and *present but unadvertised*
  (200) stay distinguishable — `getReq` flattens all three to `None`, which is
  right in the sync loop and useless in a diagnostic. Where the settings tree
  exists, it also reports the addressable node ids, which is what
  `menuitems/settings/update` needs to set brightness or a picture profile.

  Motivation: Titan OS sets (`os_type: "Linux"`) advertise a far thinner API than
  the Android ones — on a 43PUS7608/12 the list is `recordings`, `textentry`,
  `inputkey`, `pointer`, `activities`, `alexa`, with no `menuitems` and no
  `ambilight`. Philips has previous form for serving unadvertised endpoints, so
  the absence of a flag is worth testing rather than trusting.

## [0.2.1] — 2026-09-13

### Fixed

- **Green CI at the tag.** The 0.2.0 pairing-flow test constructed
  `haphilipsjs.PairingFailure` without its required `data` argument, so the test
  job failed on the 0.2.0 ref. The config flow itself was correct — no runtime
  change — but the test is fixed so the released ref is green. Safe to skip if
  0.2.0 is working for you.

## [0.2.0] — 2026-09-13

A second capability: **Philips Ambilight → RGB light mirroring**. The TV already
computes a colour, per frame, from whatever is on screen — a games console, any
HDMI input, not just media with metadata. The bridge reads those colours off the
local JointSpace API and relays them to a light, so a Tuya (or any RGB) strip
tracks the screen live. Home Assistant's core `philips_js` integration
deliberately won't surface these values ("would overload the event bus"), which
is exactly the gap the bridge exists to fill.

### Added

- **Philips Ambilight TV source (config flow + PIN pairing).** Add one from
  Settings → Devices & Services → Fibbers Bridge → *Philips Ambilight TV*: enter
  the IP, confirm the PIN the TV shows, done. Pairing follows the same
  digest-auth JointSpace handshake as core's `philips_js` (via `ha-philipsjs`);
  credentials are stored in the config entry. Works on Titan OS sets (JointSpace
  v6).
- **`fibbers_bridge.ambilight_start` / `ambilight_stop`.** Start or stop mirroring
  a source TV's Ambilight colour onto an RGB light, with configurable update rate
  (1–20 Hz) and colour source (`processed` / `measured`). Relays via
  `light.turn_on`, so it works with any colour-capable light, Tuya included.
- **`fibbers_bridge.ambilight_probe`.** One-shot read returning the current
  colour, raw payload and LED topology as a service response — confirm pairing
  and see live values without wiring up a light first.
- **`fibbers_bridge/ambilight_subscribe` + `/ambilight_sources` websocket
  commands.** A live colour stream (off the event bus) for custom cards, plus a
  picker of paired TVs. The current snapshot is replayed on subscribe.
- **Ambilight colour sensor + diagnostics.** Each paired TV exposes a low-rate
  sensor (last colour as hex, RGB + health as attributes) for Developer Tools and
  automations, and a redacted diagnostics dump for troubleshooting.

### Changed

- The bridge now supports multiple config entries (the base services entry plus
  one per Philips TV), so `single_config_entry` is dropped; a duplicate base
  entry is still prevented by unique-id.

### Developer experience

- Colour averaging, dead-band and rate-clamp are pure, unit-tested helpers;
  packet flooding of the bulb is avoided by skipping sub-perceptible changes.
  Gated debug logging traces every poll/relay tick.

## [0.1.2] — 2026-09-12

### Added

- **Test suite + CI guard for `_resolve_atv`.** A `pytest-homeassistant-custom-component`
  harness (`tests/`) exercises both Apple TV resolution paths — the HA 2024.6+
  `entry.runtime_data` path and the legacy `hass.data["apple_tv"]` fallback — plus the
  domain filter and the "not set up" / "no connected Apple TV" / unknown-device error
  cases. A new `tests` job in the Validate workflow runs it on every push, so the
  regression that broke 0.1.0 (core moving the manager off `hass.data`) is now caught by
  CI instead of by users. No runtime behaviour change.

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
