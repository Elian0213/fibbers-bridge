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

## TV capability probe

`fibbers_bridge.tv_probe_settings` — `{ entry_id, include_raw? }`, **returns a
response**. Read-only: it changes nothing on the TV.

Philips advertises what its API serves in `system.featuring.jsonfeatures`, and
`ha-philipsjs` gates most calls on that. Titan OS sets (`os_type: "Linux"`, 2023+)
publish a much thinner list than the Android ones — usually no `menuitems` (the
settings tree behind picture style, brightness and contrast) and no `ambilight`.
Philips has form for serving endpoints it doesn't advertise, so this probe ignores
the advertisement and asks the TV directly.

The value is in the status codes, which `getReq` otherwise collapses to `None`:

| `verdict` | Status | Means |
| --- | --- | --- |
| `available` | 200 | present, possibly unadvertised — usable via the library's `force=True` |
| `not_implemented` | 404 | this firmware genuinely lacks it |
| `forbidden` | 401/403 | implemented but refused — a pairing problem, not a missing feature |
| `unreachable` | — | no answer; TV asleep or off the network |

```jsonc
{
  "host": "192.168.1.159", "name": "43PUS7608/12", "os_type": "Linux",
  "advertised": { "jsonfeatures": { ... }, "systemfeatures": { ... } },
  "menuitems_advertised": false,
  "endpoints": {
    "menuitems/settings/structure": {
      "status": 404, "verdict": "not_implemented",
      "purpose": "Settings tree — picture style/profile, brightness, contrast, colour"
    }
    // ambilight/supportedstyles, ambilight/currentconfiguration, ambilight/power,
    // ambilight/topology, screenshot, applications
  },
  "settings_available": false,
  "settings_nodes": 0,
  "settings_nodes_sample": [],   // { node_id, type, context, string_id }, capped at 25
  "summary": "This firmware does not implement the settings tree (404). ..."
}
```

A node in `settings_nodes_sample` is what `menuitems/settings/current` reads and
`menuitems/settings/update` writes — so a non-empty list is the green light for
building brightness/picture-profile control. Pass `include_raw: true` for the
complete tree (large).

Where the node ids come from, and why Titan OS lies about them:
[`docs/TITANOS.md`](TITANOS.md).

---

## TV settings (Ambilight brightness, styles, ambisleep)

Read and write a paired TV's settings tree without hardcoding node ids. Titan OS
serves Ambilight settings but not picture ones — see [`docs/TITANOS.md`](TITANOS.md).

`fibbers_bridge.tv_settings_list` / `fibbers_bridge/tv_settings_list` —
`{ entry_id, refresh? }`, **returns a response**. One call renders a card: labels
and ranges from the structure, values and availability merged in from current.

```jsonc
{
  "host": "192.168.1.159", "name": "43PUS7608/12", "version": 4,
  "ambilight": { "power": "On", "leds": 0 },   // leds 0 = no strip attached
  "controls": [
    { "node_id": 710, "kind": "slider", "context": "ambilight_brightness",
      "parent_context": "ambilight_advanced", "min": 0, "max": 100, "step": 1,
      "value": 40, "controllable": true, "available": true },
    { "node_id": 320, "kind": "enum", "context": "ambilight_follow_video",
      "parent_context": "ambilight_style",
      "options": [ { "enum_id": 1, "string_id": "...", "controllable": true } ],
      "value": 1 }
  ],
  "groups": ["ambilight_style", "ambilight_advanced", "ambisleep"]
}
```

`kind` is one of `slider | enum | colors | int | bool | multi_slider` (the last
read-only). A node missing from the current read still ships with `value: null`,
`available: false`.

`fibbers_bridge.tv_settings_get` — `{ entry_id, node_ids: [int] }` → `{ nodes: [...] }`.

`fibbers_bridge.tv_settings_set` — `{ entry_id, node_id, value? , data? }`,
**returns** `{ node_id, changed, before, after, note }`. The TV answers OK to
writes it ignores, so trust **`changed`**, not the call — a card must revert an
optimistic update when `changed` is false.

Bodies are parsed by content type, not size: JSON up to 1 MB is parsed and mined
for node ids, non-JSON never is. A parsed body over 4 KB is dropped from the
response and flagged `json_omitted: true` — it still counts towards
`settings_nodes`.

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
