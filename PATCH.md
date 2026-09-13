# Patch: Bridge 0.5.1 + Fibbers 1.4.1

Two repos, one document. **Backend first** — the frontend fixes are cosmetic, the
backend one is why every control on the card reads empty.

---

## 0. The screen / picture profile question — answered

**Titan OS does not expose picture settings over the API on this TV.** Not a
missing feature in the bridge, and not something anyone forgot to add.

`menuitems/settings/structure` returns the settings tree, and the picture branch
in it is an empty stub:

```yaml
node_id: 1    PARENT_NODE   Setup_Menu
  node_id: 2  PARENT_NODE   picture      data: {}      # ← no children at all
  node_id: 3  PARENT_NODE   ambilight    data: {nodes: [ ... 20 nodes ... ]}
```

That's a plain `GET`, unaffected by the read bug below, and it has come back the
same on every probe. Everything the TV does expose is Ambilight — which is why
the card only shows Ambilight.

**One thing left to rule out.** The read path (§1) has been broken since 0.5.0,
so we have never successfully read *any* node value — including node ids that
might answer without appearing in the structure. Philips has form for exactly
that (the whole `menuitems` feature is unadvertised yet served). So: fix the read
first, then run the sweep in §1.4. If picture nodes answer, they're usable and
the card grows a Picture section. If they don't, §0 is final and we stop asking.

Until that sweep runs, "no picture profiles" is well-evidenced but not proven.

---

# Backend — fibbers-bridge 0.5.1

Both bugs are in `tvsettings.py`, both are one-line envelope mismatches, and both
are confirmed against `ha-philipsjs`'s own TypedDicts in `haphilipsjs/typing.py`.

## 1.1 The read parses a key the TV never sends

```python
# read_current(), current
resp = await jointspace.request_json(source, "POST", _CURRENT, body)
for node in (resp or {}).get("nodes", []):        # ← always empty
```

The **request** body is right (`{"nodes": [{"nodeid": N}]}` matches
`MenuItemsSettingsCurrentPost`). The **response** is not shaped that way:

```python
class MenuItemsSettingsCurrent(TypedDict):
    values: List[MenuItemsSettingsCurrentValue]   # ← "values", not "nodes"
    version: int

class MenuItemsSettingsCurrentValue(TypedDict):
    value: MenuItemsSettingsCurrentValueValue

class MenuItemsSettingsCurrentValueValue(TypedDict):
    Nodeid: int                                   # ← capital N, inside "value"
    Controllable: bool
    Available: bool
    string_id: str
    data: MenuItemsSettingsValueData
```

So `resp["nodes"]` is always missing, the loop never runs, and `read_current`
returns `{}` for everything. That is the whole explanation for:

- `tv_settings_get` → `nodes: []` for **every** node id, including 710 and 720
  which demonstrably exist in the structure
- every control in `tv_settings_list` coming back
  `value: null, controllable: false, available: false`
- the card greying out all seven controls

It is **not** the missing LED strip. The strip explains `topology: 0` and
`supportedStyles: []`; it does not explain an empty read.

**Fix:**

```python
for entry in (resp or {}).get("values", []):
    value = entry.get("value") if isinstance(entry, Mapping) else None
    if not isinstance(value, Mapping):
        continue
    nid = value.get("Nodeid")
    if isinstance(nid, int):
        # some firmwares put `data` beside `value` rather than inside it
        if value.get("data") is None and isinstance(entry.get("data"), Mapping):
            value = {**value, "data": entry["data"]}
        out[nid] = value
```

Note the last two lines: `ha-philipsjs` carries the same workaround in
`getMenuItemsSettingsCurrentValue`, so some sets really do that.

Downstream, `_control()` / `_cur_data()` read `controllable` / `available`
lowercase — the TV sends `Controllable` / `Available` capitalised. Normalise once
at the parse boundary rather than sprinkling `.get()` fallbacks through the merge.

## 1.2 The write envelope uses the wrong case

```python
body = {"values": [{"value": {"nodeid": node_id, "data": payload}}]}
#                              ^^^^^^ lowercase
```

Read and write disagree here, and the TV is strict:

```python
class MenuItemsSettingsUpdateValueValue(TypedDict):
    Nodeid: int        # ← capital N on update, lowercase only on the current *request*
    data: MenuItemsSettingsUpdateValueData
```

`{"values": [{"value": {"Nodeid": node_id, "data": payload}}]}`.

This is the "outer envelope" suspect from the 0.5.0 release notes. It is worth
fixing now rather than waiting for a strip, because with 1.1 fixed it becomes
testable the moment any node reports `Controllable: true`.

## 1.3 Make the read visible to the probe

`tv_probe_settings` only probes `GET` endpoints, so `current` — the one that was
broken — was never covered. Add it:

```python
Endpoint("menuitems/settings/current", "POST", "Read a settings node",
         payload={"nodes": [{"nodeid": 1}]}),
```

`Endpoint` needs an optional `payload`, and `_probe_one` needs to pass it to
`request_raw` (which already accepts one). Node 1 is the root and always exists,
so a 200 with a non-empty `values` array proves the read path end to end.

Had this been in the probe, 0.5.0 would not have shipped with a dead reader.

## 1.4 New: node sweep, for §0

A discovery service, to settle the picture question and to find anything else the
structure omits:

`fibbers_bridge.tv_settings_sweep` — `{ entry_id, start, end, step? }`,
`SupportsResponse.ONLY`. POSTs `current` for each batch of ids in the range
(chunk at 10 — `ha-philipsjs` uses `MAXIMUM_ITEMS_IN_REQUEST` for a reason) and
returns only the ids that came back with a value:

```jsonc
{ "scanned": 300, "found": [ { "node_id": 2110, "string_id": "...", "kind": "int", "value": 50 } ] }
```

Ranges worth sweeping once it works: `1–100`, `100–300` (where picture sits on
Android Philips), `2000–2200`. Keep it out of the card — it's a diagnostic, and
a few hundred POSTs is not something a dashboard should do on render.

## 1.5 Tests

Pin both envelopes by asserting the **exact bytes** posted, not just behaviour —
that is what neither test caught:

- `read_current` parses a realistic `{"values":[{"value":{"Nodeid":710,...}}]}`
  payload and returns `{710: {...}}`
- `read_current` returns `{}` — not an exception — for `{"values": []}`
- a fixture shaped `{"nodes":[...]}` (the old wrong assumption) yields `{}`, so
  the bug can't silently return
- `write_node` posts `Nodeid` capitalised — assert the request body
- `Controllable`/`Available` capitalised on input surface as `controllable` /
  `available` in the merged control
- `data` beside `value` is recovered

`manifest.json` → `0.5.1`, CHANGELOG, tag.

---

# Frontend — fibbers 1.4.1

All three are contained in `tv-settings-util.ts` + `@shared/color`. No backend
dependency; ship independently.

## 2.1 Enum options render raw string ids

The chips currently read `MLM_PHM_KEY_MAIN_AMBILIGHT_STYLE_VIDEO_1_2K20`.

My fault, not the implementer's: `FRONTEND.md` specified the fallback chain
(`label` → `t(context)` → `context`) for **controls**, and options carry no
`context`, so there was nothing to fall back to. Spec gap.

Add `humaniseStringId(id, parentContext?)`:

1. strip a leading `MLM_PHM_KEY_`, then any of `MAIN_`, `ID_`, `DESC_`, `PC_`
2. strip a trailing `_2K\d\d`, `_L\d+`, `_\d+K\d+`
3. split on `_`, drop words already present in the parent's `context`
   (so `AMBILIGHT_STYLE_VIDEO_1` under `ambilight_follow_video` → `1`… guard
   that: if the result is empty or numeric-only, keep the last two words)
4. title-case, join with spaces

`..._STYLE_VIDEO_1_2K20` → "Video 1", `..._GAME_2K23` → "Game",
`..._LOUNGE_LIGHT_MODE_2_2K23` → "Lounge Light Mode 2".

Back it with an optional `tv_settings.option.<string_id>` translation lookup that
wins when present — humanising is the fallback, not the primary.

Unit-test the four examples above plus: an id with no known prefix passes through
readably; an empty result never renders as a blank chip.

## 2.2 Wall colour ints are signed ARGB

The swatches render `#-1651276`. Those are signed 32-bit ARGB and decode cleanly:

```
       -1  →  FFFFFFFF  →  #FFFFFF   white
 -1651276  →  FFE6CDB4  →  #E6CDB4   cream
 -3342439  →  FFCCFF99  →  #CCFF99   pale green
     -256  →  FFFFFF00  →  #FFFF00   yellow
   -26368  →  FFFF9900  →  #FF9900   orange
 -12566464 →  FF404040  →  #404040   dark grey
```

All 23 the TV returned decode to plausible wall tones, alpha `FF` throughout —
so this is not best-effort, it's exact.

Add to `@shared/color`:

```ts
export function argbIntToHex(n: number): string {
  return `#${((n >>> 0) & 0xffffff).toString(16).padStart(6, "0")}`;
}
```

Unit-test those six pairs. Then render actual swatches: a colour circle with a
selection ring, and the hex only in the accessible name — not as the visible
label.

## 2.3 Distinguish "couldn't read" from "unavailable"

Right now a control with `value: null` renders "Unavailable right now", which is
what made the backend bug look like expected no-strip behaviour for a whole
release. They are different states and should read differently:

| Backend says | Card shows |
| --- | --- |
| `available: false` (TV answered, said no) | "Unavailable right now" — current behaviour |
| **no entry for that node at all** | **"Couldn't read this setting"**, distinct styling |

That needs the backend to say which, so pair it with 0.5.1: `tv_settings_list`
should mark a control the read never returned as `read_failed: true` rather than
folding it into `available: false`. A whole section in that state is worth one
line above the group, not a repeated label on every row.

`package.json` → `1.4.1`, `bun run build`, commit `dist/`, CHANGELOG.

---

## Order to do this in

1. Backend 1.1 + 1.3 (read + probe coverage) → redeploy → the card should
   immediately show real values for the Ambilight nodes, or prove the TV really
   does return nothing.
2. Backend 1.4 sweep → settles §0 for good.
3. Backend 1.2 (write envelope) → untestable until something is `Controllable`,
   but ship it; it's a known mismatch either way.
4. Frontend 1.4.1 — independent, any time.
