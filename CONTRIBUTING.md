# Contributing to Fibbers Bridge

Fibbers Bridge is a single Home Assistant **custom integration** (HACS integration
category) — the backend companion to the [Fibbers](https://github.com/Elian0213/fibbers-home-assistant)
dashboard plugin. It ships no frontend; it publishes services and websocket commands
that any card or automation can call.

## Architecture at a glance

- **`custom_components/fibbers_bridge/__init__.py`** — registers every service and
  websocket command once, in `async_setup_entry` (see `docs/API.md` for the list).
  Apple TV handlers resolve a `device_id` → the core `apple_tv` config entry →
  `entry.runtime_data.atv` (the live pyatv object), then call `atv.touch.*` through
  the device's `TouchLane` (`touch.py`: ordering, hold coalescing, timeouts, safety
  release). That path is **internal API** of another integration, so every access is
  wrapped and feature-detected — it must degrade to a clear error, never raise into
  Home Assistant.
- **Philips TV modules** — `ambilight.py` (colour sync), `jointspace.py` /
  `tvprobe.py` / `tvsettings.py` (raw JointSpace API), `remote.py` / `keyseq.py` /
  `macros.py` (key sequences), `probe.py` / `journal.py` (the probe journal).
- **`config_flow.py`** — an input-less Apple TV entry, or a Philips TV paired by PIN.
- **`services.yaml` / `strings.json` / `translations/en.json`** — the service
  schemas + UI copy (Developer Tools → Actions).
- **`manifest.json`** — `pyatv` and `ha-philipsjs` pinned to match Home Assistant
  core's `apple_tv` / `philips_js`, and `after_dependencies: ["apple_tv"]` so it
  loads after it.

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

- The Apple TV manager lives on `entry.runtime_data` (HA 2024.6+; `hacs.json`
  requires 2025.1). It isn't a public API — guard every access (see `_resolve_atv`).
- pyatv touch requires the **Companion** protocol (tvOS 15+); MRP-only devices won't
  have `atv.touch`. Feature-detect with `atv.features.in_state(...)`.
- Keep `manifest.json` `version` in sync with the git tag on release.

## Releasing

Commit + tag `X.Y.Z` (a `vX.Y.Z` tag also works); the `Release` workflow cuts the GitHub release. HACS
installs the tagged `custom_components/fibbers_bridge/`. Bump `version` in
`manifest.json` and add a `CHANGELOG.md` entry (`## [X.Y.Z] — YYYY-MM-DD`).
