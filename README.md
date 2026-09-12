<div align="center">

<img src="https://raw.githubusercontent.com/Elian0213/fibbers-home-assistant/main/docs/images/logo.svg" alt="Fibbers Bridge" width="220">

### The backend that gives your cards powers Home Assistant doesn't expose

A small Home Assistant **integration** that publishes generic, reusable **services**
and **websocket commands** — so any Lovelace card or automation can drive low-level
device capabilities the core APIs leave out. The first one: **Apple TV native touch**
(the real Siri-Remote touch surface, over pyatv's Companion protocol).

[![Validate](https://github.com/Elian0213/fibbers-bridge/actions/workflows/validate.yml/badge.svg)](https://github.com/Elian0213/fibbers-bridge/actions/workflows/validate.yml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Elian0213&repository=fibbers-bridge&category=integration)

</div>

---

## Why

Some things the Apple TV remote does — like a **continuous timeline scrub in Netflix**
(the playhead follows your finger) — ride the Apple TV's **touch surface** over the
Companion protocol. Home Assistant's `apple_tv` integration only exposes discrete
button presses (`remote.send_command`) and `media_player.media_seek`, and Netflix
reports no timeline to HA — so neither can do a real scrub. `pyatv` **can**
(`atv.touch.swipe/action/click`), but HA ships no service for it.

Fibbers Bridge fills that gap, and does it **generically**: it exposes the capability
as plain services + websocket commands with a documented, stable contract, so it's not
tied to any one card. Point [Fibbers](https://github.com/Elian0213/fibbers-home-assistant),
`button-card`, or your own card at it.

## Install

**HACS → custom repository** (until it's in the default store):

1. HACS → ⋮ → **Custom repositories**
2. Repository: `https://github.com/Elian0213/fibbers-bridge`, Category: **Integration** → **Add**
3. Install **Fibbers Bridge**, then **restart** Home Assistant
4. **Settings → Devices & Services → Add Integration → Fibbers Bridge** (nothing to configure)

**Requirements:** the core **Apple TV** integration set up and paired via the
**Companion** protocol (tvOS 15+). Fibbers Bridge borrows its live connection.

## Use it from a card or automation

```yaml
# Any card's tap_action, or an automation action:
action: fibbers_bridge.atv_swipe
data:
  device_id: <your Apple TV device>
  start_x: 500
  start_y: 500
  end_x: 850
  end_y: 500
  duration_ms: 400
```

From a **custom card** (low-latency, stream it as the finger moves):

```js
await this.hass.connection.sendMessagePromise({
  type: "fibbers_bridge/atv_swipe",
  device_id: deviceId,
  start_x: 500, start_y: 500, end_x: 850, end_y: 500, duration_ms: 200,
});
```

Full contract — every service, websocket command, parameter, and a feature-detection
snippet — is in **[docs/API.md](docs/API.md)**.

## Services

| Service | Does |
| --- | --- |
| `fibbers_bridge.atv_swipe` | Swipe the touch surface (0–1000 coords) — continuous scrub, list traversal |
| `fibbers_bridge.atv_touch` | One press / hold / release at a point (build custom gestures) |
| `fibbers_bridge.atv_click` | Click the surface: single, double, or hold |

Websocket equivalents: `fibbers_bridge/atv_swipe`, `fibbers_bridge/atv_touch`.

## How it works

See **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — the bridge concept, how it
reaches the Apple TV's pyatv object, why that's guarded, and where it's going
(**[docs/ROADMAP.md](docs/ROADMAP.md)**).

## Development

Python, no build step. `python -m py_compile custom_components/fibbers_bridge/*.py`
for a quick sanity check; the `Validate` workflow runs HACS + `hassfest` on every
push. See **[CONTRIBUTING.md](CONTRIBUTING.md)**.

## License

MIT © 2026 Elian Heutink
