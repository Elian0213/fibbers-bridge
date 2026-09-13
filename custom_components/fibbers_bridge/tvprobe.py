"""Capability probe for a paired Philips TV.

Philips advertises what its JointSpace API offers in `system.featuring.jsonfeatures`,
and `ha-philipsjs` gates most calls on that advertisement. Titan OS sets (os_type
`Linux`, 2023+) publish a far thinner list than the Android ones — typically with
no `menuitems` (the feature carrying the settings tree: picture style, brightness,
contrast) and no `ambilight`.

Philips has previous form for serving endpoints it never advertises, so a missing
feature flag is evidence rather than proof. This module ignores the advertisement
and asks the TV directly, recording the HTTP status of each endpoint so the three
outcomes stay distinguishable:

* **200** — present but unadvertised; the library's `force=True` path can use it.
* **404** — genuinely not implemented on this firmware. Nothing to build on.
* **401/403** — implemented but refused: a pairing/permission problem, not a
  missing capability.

`getReq` collapses all three to `None` (and caches the path as dead), which is
correct for normal operation and useless for a diagnostic — so we issue the
requests through the client's already-authenticated session ourselves and read
the status code before anything can swallow it.

Nothing here mutates the TV. Every probe is a read.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .ambilight import AmbilightSource

_LOGGER = logging.getLogger(__name__)

# Philips serves the unsecured API on 1925 and the digest-authenticated one on
# 1926. Only used if the library stops exposing its own URL builder.
_HTTP_PORT = 1925
_HTTPS_PORT = 1926

# Endpoint bodies we never want in a service response (a screenshot is a JPEG).
_MAX_PREVIEW_BYTES = 4096

# How long to wait on a single probe. A TV that is awake answers in well under a
# second; one that is asleep never answers at all, and we would rather report a
# timeout per endpoint than hang the whole service call.
_TIMEOUT = 8.0


@dataclass(frozen=True)
class Endpoint:
    """One endpoint to probe, and what a 200 from it would buy us."""

    path: str
    method: str
    purpose: str


# Ordered most- to least-interesting; the summary reads the first hit.
PROBE_ENDPOINTS: tuple[Endpoint, ...] = (
    Endpoint(
        "menuitems/settings/structure",
        "GET",
        "Settings tree — picture style/profile, brightness, contrast, colour",
    ),
    Endpoint("ambilight/supportedstyles", "GET", "Ambilight preset list"),
    Endpoint("ambilight/currentconfiguration", "GET", "Current Ambilight preset"),
    Endpoint("ambilight/power", "GET", "Ambilight on/off"),
    Endpoint("ambilight/topology", "GET", "Ambilight LED layout"),
    Endpoint("screenshot", "GET", "Still frame of what is on screen"),
    Endpoint("applications", "GET", "Installed app list"),
)

# The endpoint whose presence answers the question this probe exists to settle.
SETTINGS_PATH = PROBE_ENDPOINTS[0].path


# --- pure helpers (no I/O) -----------------------------------------------------


def verdict_for(status: int | None) -> str:
    """Classify an HTTP status into what it means for building on the endpoint."""
    if status is None:
        return "unreachable"
    if status == 200:
        return "available"
    if status in (401, 403):
        return "forbidden"
    if status == 404:
        return "not_implemented"
    return "unexpected"


def collect_nodes(structure: Any, _depth: int = 0) -> list[dict[str, Any]]:
    """Flatten a `menuitems/settings/structure` tree into its addressable nodes.

    The tree nests differently across firmwares, so rather than assume a shape we
    walk every mapping and list and keep anything carrying a node id. Each node is
    what `menuitems/settings/current` reads and `.../update` writes, so this list
    is the actual menu of what could be controlled.
    """
    # Deep enough for any real menu; a guard against a self-referential payload.
    if _depth > 12:
        return []
    found: list[dict[str, Any]] = []
    if isinstance(structure, dict):
        node_id = structure.get("node_id", structure.get("nodeid"))
        if isinstance(node_id, int):
            found.append(
                {
                    "node_id": node_id,
                    "type": structure.get("type"),
                    "context": structure.get("context"),
                    "string_id": structure.get("string_id"),
                }
            )
        for value in structure.values():
            found.extend(collect_nodes(value, _depth + 1))
    elif isinstance(structure, list):
        for value in structure:
            found.extend(collect_nodes(value, _depth + 1))
    return found


def summarise(
    results: dict[str, dict[str, Any]], node_count: int
) -> tuple[bool, str]:
    """Reduce the raw probe into (settings_available, one-sentence verdict)."""
    settings = results.get(SETTINGS_PATH, {})
    verdict = settings.get("verdict")

    if verdict == "available":
        if node_count:
            return True, (
                f"The settings tree is there (unadvertised) with {node_count} "
                "addressable nodes — brightness and picture profiles can be read "
                "and set over the API."
            )
        return True, (
            "The settings endpoint answered 200 but returned no addressable "
            "nodes — likely a stub. Check the raw payload."
        )

    if verdict == "not_implemented":
        return False, (
            "This firmware does not implement the settings tree (404). Brightness "
            "and picture profiles cannot be set over the API — remote key macros "
            "are the only route."
        )
    if verdict == "forbidden":
        return False, (
            "The settings endpoint exists but refused the request (401/403). That "
            "is a pairing/permission problem, not a missing feature — re-pair the "
            "TV and probe again."
        )
    if verdict == "unreachable":
        return False, (
            "Could not reach the TV. Make sure it is powered on and on the same "
            "network, then probe again."
        )
    return False, "The settings endpoint returned an unexpected status."


# --- I/O -----------------------------------------------------------------------


def endpoint_url(client: Any, host: str, path: str) -> str:
    """Build the absolute URL for an endpoint on this TV.

    Prefers the library's own builder so scheme/port/api-version stay in step with
    whatever pairing negotiated; falls back to constructing it if that private
    helper ever disappears.
    """
    builder = getattr(client, "_url", None)
    if callable(builder):
        try:
            return builder(path)
        except Exception:  # noqa: BLE001 - fall back rather than fail the probe
            _LOGGER.debug("Library URL builder unavailable; constructing manually")
    protocol = getattr(client, "protocol", "https") or "https"
    port = _HTTPS_PORT if protocol == "https" else _HTTP_PORT
    version = getattr(client, "api_version", 6)
    return f"{protocol}://{host}:{port}/{version}/{path}"


async def _probe_one(client: Any, host: str, endpoint: Endpoint) -> dict[str, Any]:
    """Issue one request and report what came back, never raising."""
    result: dict[str, Any] = {
        "purpose": endpoint.purpose,
        "method": endpoint.method,
    }
    try:
        response = await client.session.request(
            endpoint.method, endpoint_url(client, host, endpoint.path), timeout=_TIMEOUT
        )
    except Exception as err:  # noqa: BLE001 - httpx errors vary by failure mode
        result["status"] = None
        result["verdict"] = verdict_for(None)
        result["error"] = str(err)
        return result

    body = response.content or b""
    result["status"] = response.status_code
    result["verdict"] = verdict_for(response.status_code)
    result["content_type"] = response.headers.get("content-type")
    result["bytes"] = len(body)

    # Only JSON small enough to be readable comes back in the response; a
    # screenshot is a JPEG and belongs nowhere near a service result.
    if response.status_code == 200 and len(body) <= _MAX_PREVIEW_BYTES:
        try:
            result["json"] = response.json()
        except ValueError:
            result["json"] = None
    return result


async def probe_capabilities(
    source: AmbilightSource, *, include_raw: bool = False
) -> dict[str, Any]:
    """Ask a paired TV what it actually serves, regardless of what it advertises.

    Returns a plain dict suitable for a service response: what the TV advertises,
    what each probed endpoint really answered, the addressable settings nodes if
    any, and a one-line verdict.
    """
    client = source.client
    report: dict[str, Any] = {
        "host": source.host,
        "name": source.name,
        "model": source.model,
    }

    try:
        await source.ensure_transport()
    except Exception as err:  # noqa: BLE001 - probe anyway; the statuses will tell
        report["transport_error"] = str(err)

    system = getattr(client, "system", None) or {}
    featuring = system.get("featuring", {}) if isinstance(system, dict) else {}
    report["os_type"] = getattr(client, "os_type", None)
    report["advertised"] = {
        "jsonfeatures": featuring.get("jsonfeatures"),
        "systemfeatures": featuring.get("systemfeatures"),
    }
    report["menuitems_advertised"] = bool(
        client.json_feature_supported("menuitems", "Setup_Menu")
    )

    results: dict[str, dict[str, Any]] = {}
    for endpoint in PROBE_ENDPOINTS:
        results[endpoint.path] = await _probe_one(client, source.host, endpoint)
    report["endpoints"] = results

    structure = results.get(SETTINGS_PATH, {}).get("json")
    nodes = collect_nodes(structure)
    report["settings_nodes"] = len(nodes)
    # A full menu runs to hundreds of nodes; a sample is enough to act on and
    # keeps the service response readable. `include_raw` gets the lot.
    report["settings_nodes_sample"] = nodes[:25]
    if include_raw:
        report["raw"] = structure

    available, summary = summarise(results, len(nodes))
    report["settings_available"] = available
    report["summary"] = summary
    return report
