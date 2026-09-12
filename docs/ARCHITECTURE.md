# Architecture

## The idea

Home Assistant deliberately exposes devices through **stable, generic entity
services** (`media_player.media_seek`, `remote.send_command`, …). That's great until
you want a capability a device has but HA doesn't model — the classic example being
the Apple TV's **touch surface** (continuous swipe/scrub), which only exists over
pyatv's Companion protocol and has no HA service.

**Fibbers Bridge** is a place to put those capabilities. It's a backend integration
that publishes them as:

- **Services** — `fibbers_bridge.atv_swipe`, etc. Good for automations and any card's
  `tap_action: call-service`. Discoverable in Developer Tools → Actions.
- **Websocket commands** — `fibbers_bridge/atv_swipe`, etc. Good for custom cards that
  need to *stream* input at low latency (reusing the frontend's already-open socket),
  e.g. a touchpad card sending a swipe as the finger moves.

Both are plain, documented contracts (see [API.md](API.md)) — nothing is coupled to
the Fibbers cards. This is the "generic API" part: anyone's dashboard can use it.

```
          Lovelace card / automation
                    │  call-service          │  ws command
                    ▼                        ▼
        fibbers_bridge.atv_swipe     fibbers_bridge/atv_swipe
                    └───────────┬────────────┘
                                ▼
                    _resolve_atv(device_id)
                                ▼
        device_registry → apple_tv config entry
                                ▼
             hass.data["apple_tv"][entry_id].atv     ← live pyatv object
                                ▼
                 atv.touch.swipe / action / click     ← Companion protocol → Apple TV
```

## Borrowing the Apple TV connection

The core `apple_tv` integration already pairs and holds a live `pyatv` connection.
Rather than pair a second Companion session, Fibbers Bridge **borrows** it:
`device_id` → the device's `apple_tv` config entry → `hass.data["apple_tv"][entry_id].atv`.

That is **internal API** of another integration — the `hass.data` shape isn't a public
contract and can change between HA releases. So:

- every access goes through `_resolve_atv()` and is wrapped;
- capabilities are **feature-detected** (`atv.features.in_state(FeatureState.Available, FeatureName.Swipe)`);
- failures raise `ServiceValidationError` / send a ws error with a clear message —
  never an unhandled exception.

### Alternative considered (future)

Fibbers Bridge could pair its **own** Companion session via its config flow (host +
credentials), making it independent of the `apple_tv` integration's internals. That's
more robust but asks the user to pair twice and store credentials. For v0.1 the borrow
approach wins on simplicity; the own-session path is on the [roadmap](ROADMAP.md) if the
internal API proves fragile.

## Growing into a capability registry

Today there's one capability (Apple TV touch). The shape is meant to scale: each new
capability is a small module that registers its own service(s) + ws command(s) behind a
stable name, with its own resolver + feature detection. The bridge stays a thin host;
`docs/API.md` stays the single source of truth for the contract.
