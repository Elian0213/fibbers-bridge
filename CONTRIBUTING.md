# Contributing to Fibbers Bridge

Fibbers Bridge is a single Home Assistant **custom integration** (HACS integration
category) — the backend companion to the [Fibbers](https://github.com/Elian0213/fibbers-home-assistant)
dashboard plugin. It ships no frontend; it publishes services and websocket commands
that any card or automation can call.

## Architecture at a glance

- **`custom_components/fibbers_bridge/__init__.py`** — registers the services
  (`atv_swipe`/`atv_touch`/`atv_click`) and websocket commands
  (`fibbers_bridge/atv_swipe`, `.../atv_touch`) once, in `async_setup_entry`.
  Handlers resolve a `device_id` → the core `apple_tv` config entry →
  `entry.runtime_data.atv` (the live pyatv object; legacy fallback
  `hass.data["apple_tv"][entry_id].atv` for pre-2024.6 cores), then call
  `atv.touch.*`. That path is **internal API** of another integration, so every
  access is wrapped and feature-detected — it must degrade to a clear error, never
  raise into Home Assistant.
- **`config_flow.py`** — a single, input-less instance so it can be added from the
  UI (which triggers setup). `manifest.json` sets `single_config_entry: true`.
- **`services.yaml` / `strings.json` / `translations/en.json`** — the service
  schemas + UI copy (Developer Tools → Actions).
- **`manifest.json`** — `requirements: ["pyatv==0.18.0"]` pinned to match Home
  Assistant core's `apple_tv`, and `after_dependencies: ["apple_tv"]` so it loads
  after it.

## Build & test

There's no build step (pure Python + YAML/JSON).

```bash
python -m py_compile custom_components/fibbers_bridge/*.py   # syntax

pip install -r requirements-test.txt                        # test deps
pytest -q                                                    # unit tests
```

The tests use `pytest-homeassistant-custom-component`, which pulls a matching Home
Assistant. HA is Linux-first (its runner imports `fcntl`) and 2026.3+ needs Python
3.14, so run the suite on Linux/macOS with Python 3.14 — it won't import on Windows.

The **Validate** workflow runs on every push: `hacs/action` (integration category),
Home Assistant's `hassfest`, and the `pytest` suite. All must pass. Full behaviour can
only be verified on a real Home Assistant with a Companion-paired Apple TV — call
`fibbers_bridge.atv_swipe` from Developer Tools and watch the TV.

## The contract is a promise

Cards depend on the service/command names and fields. **Only add** — never rename or
remove a field without a deprecation window. New capabilities get new services; new
options get new *optional* fields. See `docs/API.md` for the versioning policy.

## Home Assistant gotchas

- The Apple TV manager lives on `entry.runtime_data` (HA 2024.6+); older cores put
  it at `hass.data["apple_tv"][entry_id]`. Neither is a public API — guard both and
  keep the legacy fallback (see `_resolve_atv`).
- pyatv touch requires the **Companion** protocol (tvOS 15+); MRP-only devices won't
  have `atv.touch`. Feature-detect with `atv.features.in_state(...)`.
- Keep `manifest.json` `version` in sync with the git tag on release.

## Releasing

Commit + tag `X.Y.Z` (no `v`); the `Release` workflow cuts the GitHub release. HACS
installs the tagged `custom_components/fibbers_bridge/`. Bump `version` in
`manifest.json` and add a `CHANGELOG.md` entry (`## [X.Y.Z] — YYYY-MM-DD`).
