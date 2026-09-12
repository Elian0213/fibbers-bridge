# Roadmap

Rough and subject to change — the point is the direction, not the dates.

## v0.1 — now
- Apple TV native touch: `atv_swipe` / `atv_touch` / `atv_click` services +
  `atv_swipe` / `atv_touch` websocket commands.
- Custom-repository installable; HACS + hassfest validation green.

## Next
- **Fibbers card tie-in (cross-repo).** The Fibbers remote touchpad gets a
  config-driven hook that streams its drag to `fibbers_bridge/atv_swipe`, so a slide
  on the phone scrubs Netflix's own timeline for real — feature-detected, falling back
  to the frontend's seek-scrub / inert behaviour when the bridge isn't present.
  ```yaml
  # in a fibbers-remote touchpad device:
  touchpad:
    native_touch: { service: fibbers_bridge.atv_swipe }
  ```
- **More Apple TV verbs** worth exposing beyond the standard `remote`: text input,
  `atv.touch.click` variants, app-launch niceties.
- **Own Companion session (optional).** A config-flow that pairs its own pyatv
  connection, so the bridge doesn't reach into the `apple_tv` integration's internals —
  more robust, at the cost of a second pairing. Adopt if the borrowed path proves
  fragile across HA releases.

## Later
- **A second backend capability** unrelated to Apple TV, to prove the "generic bridge"
  shape (a small module = a resolver + services + ws commands + docs).
- **Brand assets in-repo** (`icon.png`, HA 2026.3+ serves them without the central
  brands repo) and a short docs site.
- **HACS default store** submission once there's a tagged release, passing checks,
  topics, and issues enabled.

## Non-goals
- Not a frontend. No cards live here — those are in
  [fibbers-home-assistant](https://github.com/Elian0213/fibbers-home-assistant).
- Not an Apple-TV-only project. Apple TV is just the first capability.
