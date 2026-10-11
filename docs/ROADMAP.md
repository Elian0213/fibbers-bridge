# Roadmap

Rough and subject to change — the point is the direction, not the dates.

## Shipped
- Apple TV native touch (`atv_swipe` / `atv_touch` / `atv_click`), used by the Fibbers
  remote touchpad over `fibbers_bridge/atv_touch`.
- Philips TV: Ambilight sync, settings read/write, key sequences + macros, the probe
  journal. Brand assets in-repo.

## Next
- **Zero-touch setup (YAML import).** Add a `fibbers_bridge:` config-schema + import
  flow so declaring the key in `configuration.yaml` auto-creates the config entry on
  restart — no clicking through Devices & Services. (A standalone custom integration
  can't self-register without *some* trigger — a config entry or a YAML key — so a true
  "download + restart, done" isn't possible; this is the closest correct mechanism. The
  one-click UI stays.) Pending live verification via the Chrome extension.
- **More Apple TV verbs** worth exposing beyond the standard `remote`: text input,
  `atv.touch.click` variants, app-launch niceties.
- **Own Companion session (optional).** A config-flow that pairs its own pyatv
  connection, so the bridge doesn't reach into the `apple_tv` integration's internals —
  more robust, at the cost of a second pairing. Adopt if the borrowed path proves
  fragile across HA releases.

## Later
- A short docs site.
- **HACS default store** submission once there's a tagged release, passing checks,
  topics, and issues enabled.

## Non-goals
- Not a frontend. No cards live here — those are in
  [fibbers-home-assistant](https://github.com/Elian0213/fibbers-home-assistant).
- Not an Apple-TV-only project. Apple TV is just the first capability.
