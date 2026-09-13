# Philips Titan OS notes

What a 2023+ Titan OS set actually serves over JointSpace, measured on a
**43PUS7608/12** (`os_type: Linux`, JointSpace v6.1.0, digest-auth pairing).
Recorded because none of it is documented and most of it contradicts what the TV
advertises about itself.

Everything below came from `fibbers_bridge.tv_probe_settings` against a paired
set. Re-run it on your own TV before trusting any node id here — ids are
firmware-specific.

---

## The TV under-reports itself

`GET /6/system` is the one endpoint served unauthenticated on port 1925, and it
carries the feature list the whole `ha-philipsjs` library gates on:

```jsonc
"jsonfeatures": {
  "recordings": ["List", "Schedule", "Manage"],
  "textentry":  ["context_based", "initial_string_available"],
  "inputkey":   ["key", "unicode"],
  "pointer":    ["context_based"],
  "activities": ["browser"],
  "alexa":      ["ssl_available"]
},
"systemfeatures": {
  "os_type": "Linux", "pairing_type": "digest_auth_pairing",
  "secured_transport": true, "tvtype": "consumer"
}
```

Note what is **absent**: `menuitems` and `ambilight`. An Android-based Philips
(`os_type: MSAF_*`) advertises both, plus `applications` and `channels`.

**The list is wrong.** The TV serves `menuitems` and `ambilight` endpoints anyway:

| Endpoint | Status | Reality |
| --- | --- | --- |
| `menuitems/settings/structure` | **200** | ~8 KB tree, 22 nodes — despite `menuitems` being unadvertised |
| `ambilight/supportedstyles` | 200 | `{"supportedStyles": []}` |
| `ambilight/currentconfiguration` | 200 | empty body |
| `ambilight/power` | 200 | `{"power": "On"}` |
| `ambilight/topology` | 200 | `layers 0, left 0, top 0, right 0, bottom 0` |
| `screenshot` | 403 | not implemented (see below) |
| `applications` | 403 | not implemented |

Take the advertisement as a hint, not a contract. `ha-philipsjs` treats it as a
contract, which is why the bridge talks to these endpoints directly.

### 403 does not mean "no permission"

On this firmware a path that doesn't exist returns **403 with a 72-byte
`text/html` body**, not 404. The unauthenticated port does the same for every
path except `/system`. So a 403 on an authenticated, paired connection means
"not implemented here" far more often than it means "not allowed" — don't send
the user off to re-pair over one.

There is **no screenshot endpoint**. Worth stating plainly, because sampling a
still frame would be the obvious way to derive a screen colour on a set whose
Ambilight returns nothing.

---

## The settings tree

`menuitems/settings/structure` returns a tree of numbered nodes. Read a node's
value with `POST menuitems/settings/current`, write it with
`POST menuitems/settings/update`.

On this set the tree is **partial**: the Ambilight branch is fully populated, the
picture branch is an empty parent.

```yaml
node_id: 1    PARENT_NODE   Setup_Menu
  node_id: 2  PARENT_NODE   picture      data: {}      # ← nothing underneath
  node_id: 3  PARENT_NODE   ambilight    data: {nodes: [...]}
```

So on Titan OS: **no picture brightness, no picture profiles.** The branch
exists as a stub. Remote-key macros over `inputkey` are the only route to those.

### The 22 nodes

| Node | Type | Context |
| --- | --- | --- |
| 1 | PARENT_NODE | `Setup_Menu` |
| 2 | PARENT_NODE | `picture` *(empty)* |
| 3 | PARENT_NODE | `ambilight` |
| 300 | PARENT_NODE | `ambilight_style` |
| 310 | PARENT_NODE | `ambilight_off` |
| 320 | LIST_NODE | `ambilight_follow_video` |
| 330 | LIST_NODE | `ambilight_follow_audio` |
| 340 | LIST_NODE | `ambilight_lounge_light` |
| 350 | PARENT_NODE | `ambilight_follow_flag` |
| 360 | PARENT_NODE | `ambilight_follow_app` |
| 400 | PARENT_NODE | `ambilight_custom_colour` |
| 500 | PARENT_NODE | `ambisleep` |
| 510 | PARENT_NODE | `ambisleep_on` |
| 520 | PARENT_NODE | `ambisleep_duration` |
| 530 | PARENT_NODE | `ambisleep_brightness` |
| 540 | PARENT_NODE | `ambisleep_colour` |
| 550 | PARENT_NODE | `ambisleep_sound` |
| 700 | PARENT_NODE | `ambilight_advanced` |
| **710** | **SLIDER_NODE** | **`ambilight_brightness`** |
| **720** | **SLIDER_NODE** | **`ambilight_saturation`** |
| 730 | WALL_COLOR_NODE | `ambilight_wall_color` |
| 740 | LIST_NODE | `ambilight_tv_switch_off` |

---

## Writing a node: two ways to fail silently

The TV answers **200 to updates it ignores**. There is no error to catch, so the
only honest confirmation is to read the value back and check it moved. Both
traps are shape mismatches between read and write:

**1. Enums rename their key.** A `LIST_NODE` reads back as `selected_item` and
must be written as `select_item`:

```jsonc
// GET current  →
{"selected_item": 310, "enum_values": [{"enum_id": 320, "controllable": true}]}
// POST update  →
{"select_item": 320}          // NOT "selected_item"
```

**2. Sliders need their id back.** A `SLIDER_NODE` reads as
`{"slider_id": "...", "value": 40}`, and the id has to be sent with the new
value, not just the number.

`Controllable: false` on a read means the TV will refuse the write — check it
first and say so, rather than writing into the void.

---

## `ha-philipsjs` can't reach any of this

Two separate reasons, both worth knowing before reaching for the library:

- **Gated on the advertisement.** `getMenuItemsSettingsStructure()`,
  `getAmbilightSupportedStyles()` and friends check `json_feature_supported(...)`
  first and return `None` when the feature isn't listed — which on Titan OS is
  always.
- **`force=True` doesn't reach the read.** `getMenuItemsSettingsCurrentValue`
  takes `force`, passes it to `getMenuItemsSettingsCurrent`, which then calls the
  inner `_getMenuItemsSettingsCurrent(group)` **without it** when it chunks node
  ids. The gate closes anyway.

Also: `getReq()` collapses 401, 403, 404 and a dead network into the same `None`,
and caches the path as dead for the session. Fine in a polling loop, useless for
finding out what a TV supports.

Hence `jointspace.py` — the client's authenticated session, the real status code,
no gating. Everything else in the bridge still goes through the library.

---

## Ambilight without a strip

This set has an Ambilight RGB header but no strip attached, and the resulting
state is worth recognising, because it looks like a broken integration:

- `ambilight/power` → `On`
- `ambilight/topology` → 0 LEDs on all four sides
- `ambilight/supportedstyles` → `[]`
- `ambilight/processed` and `/measured` → no pixels, so no colour to read
- the **settings menu is fully populated regardless** — brightness, saturation,
  styles, ambisleep are all there

So a populated Ambilight settings branch means the firmware is Ambilight-capable;
a zero topology means nothing is plugged in. Both together mean: connect a strip
to the header and the colour endpoints start returning data, and those 20 nodes
start acting on something.

A zero topology is the check to run before blaming pairing.
