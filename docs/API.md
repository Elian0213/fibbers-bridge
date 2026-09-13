# API contract

This is the stable, public surface of Fibbers Bridge. **It only grows** — names and
existing fields don't change without a deprecation window; new options are added as
*optional* fields; new capabilities get new services/commands. Cards can rely on it.

Coordinates are **0–1000 on both axes** (normalised to the Apple TV touch surface,
0,0 = top-left), matching pyatv's Companion touch API.

---

## Services (automations + `tap_action: call-service`)

### `fibbers_bridge.atv_swipe`
Swipe across the touch surface.

| Field | Type | Req | Default | Range |
| --- | --- | --- | --- | --- |
| `device_id` | string | ✓ | — | an `apple_tv` device |
| `start_x`, `start_y` | int | ✓ | — | 0–1000 |
| `end_x`, `end_y` | int | ✓ | — | 0–1000 |
| `duration_ms` | int | | 500 | 1–10000 |

### `fibbers_bridge.atv_touch`
One touch phase at a point — chain `press` → (`hold`…) → `release` for a custom gesture.

| Field | Type | Req | Values |
| --- | --- | --- | --- |
| `device_id` | string | ✓ | an `apple_tv` device |
| `x`, `y` | int | ✓ | 0–1000 |
| `mode` | enum | ✓ | `press` \| `hold` \| `release` |

### `fibbers_bridge.atv_click`
Click the surface (a select).

| Field | Type | Req | Default | Values |
| --- | --- | --- | --- | --- |
| `device_id` | string | ✓ | — | an `apple_tv` device |
| `action` | enum | | `single` | `single` \| `double` \| `hold` |

---

## Websocket commands (custom cards, low-latency)

Same names with a `/`, same fields plus the standard `id`. Use these when you stream
input (e.g. a touchpad drag) — they reuse the frontend's open socket.

- `fibbers_bridge/atv_swipe` — fields as `atv_swipe` above
- `fibbers_bridge/atv_touch` — fields as `atv_touch` above

```js
const res = await hass.connection.sendMessagePromise({
  type: "fibbers_bridge/atv_swipe",
  device_id, start_x: 500, start_y: 500, end_x: 850, end_y: 500, duration_ms: 200,
});
// → { ok: true }  |  ws error code "fibbers_bridge_error" with a message
```

A card driving a live scrub typically sends one swipe per ~100–150 ms of drag,
mapping the surface's local x/y to 0–1000.

---

## Ambilight (Philips TV → RGB light)

Mirror the colour a Philips Ambilight TV derives from its screen onto any
colour-capable light. Because the TV computes the colour, this works for **any
on-screen source** — a games console, any HDMI input — not just media with
metadata. Add a TV first via the config flow (Settings → Devices & Services →
Fibbers Bridge → *Philips Ambilight TV*, then confirm the PIN it shows). The TV's
config-entry id is the `entry_id` used below.

### Services

`fibbers_bridge.ambilight_start`

| Field | Type | Req | Default | Notes |
| --- | --- | --- | --- | --- |
| `entry_id` | string | ✓ | — | a paired Philips TV config entry |
| `target` | entity_id | ✓ | — | an RGB-capable `light.*` |
| `rate` | int | | 6 | 1–20 Hz |
| `mode` | enum | | `processed` | `processed` \| `measured` |

`fibbers_bridge.ambilight_stop` — `{ target: entity_id }`

`fibbers_bridge.ambilight_probe` — `{ entry_id, mode? }`, **returns a response**:
`{ ok, color: [r,g,b] | null, topology, raw, host, name }`.

### Websocket commands (custom cards)

- `fibbers_bridge/ambilight_subscribe` — `{ target?: entity_id }`. A subscription:
  emits an event per colour update; the current snapshot is replayed immediately
  on subscribe. Each event:
  ```js
  { target, source, source_name, rgb: [r,g,b] | null, active, available,
    health: { sent, errors, last_error } }
  ```
- `fibbers_bridge/ambilight_sources` → `{ sources: [{ entry_id, name, host, available }] }`

```js
const unsub = await hass.connection.subscribeMessage(
  (evt) => { /* evt.rgb → paint your visualiser */ },
  { type: "fibbers_bridge/ambilight_subscribe", target: "light.tv_strip" },
);
```

Runtime errors: an unknown/un-paired source, or a target that can't accept an
`rgb_color`, raise `ServiceValidationError` with a user-facing message.

---

## Discovery / feature detection

Check before you offer the feature, so your card degrades cleanly when the bridge
isn't installed:

```js
const hasBridge = !!this.hass.services.fibbers_bridge?.atv_swipe;
```

Runtime errors you should handle: the device isn't an Apple TV / isn't connected, the
Apple TV integration isn't set up, or the device lacks Companion touch (pre-tvOS 15 /
MRP-only). Services raise `ServiceValidationError`; websocket calls return an error with
code `fibbers_bridge_error`.

---

## Versioning policy

- **Additive only.** New services/commands and new *optional* fields are minor bumps.
- **Deprecations** get a warning log for at least two minor releases before removal.
- Breaking a name/field is a major bump and will be called out in the CHANGELOG.
