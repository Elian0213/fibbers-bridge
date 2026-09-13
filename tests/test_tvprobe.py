"""Tests for the TV capability probe's pure logic.

The probe exists to keep three outcomes apart that `getReq` flattens into `None`:
an endpoint that isn't implemented, one that's refused, and one that's there but
unadvertised. That distinction is the whole product of this module, so it's
pinned here — along with the node walker, which has to survive firmware payloads
we can't see from a test.
"""

from __future__ import annotations

import json

import pytest

from custom_components.fibbers_bridge.tvprobe import (
    PROBE_ENDPOINTS,
    SETTINGS_PATH,
    collect_nodes,
    endpoint_url,
    probe_capabilities,
    summarise,
    verdict_for,
)


# --- verdict_for ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (200, "available"),
        (401, "forbidden"),
        (403, "forbidden"),
        (404, "not_implemented"),
        (500, "unexpected"),
        (None, "unreachable"),
    ],
)
def test_verdict_for(status: int | None, expected: str) -> None:
    assert verdict_for(status) == expected


# --- collect_nodes -------------------------------------------------------------


def test_collect_nodes_finds_nested_ids() -> None:
    structure = {
        "version": 3,
        "node": {
            "node_id": 1,
            "type": "menu",
            "data": {
                "nodes": [
                    {"node_id": 2000, "type": "int", "string_id": "brightness"},
                    {"node_id": 2001, "type": "enum", "string_id": "picture_style"},
                ]
            },
        },
    }
    nodes = collect_nodes(structure)
    assert [n["node_id"] for n in nodes] == [1, 2000, 2001]
    assert nodes[1]["string_id"] == "brightness"


def test_collect_nodes_accepts_the_nodeid_spelling() -> None:
    """Some firmwares return `nodeid`, others `node_id`; both must be found."""
    assert collect_nodes({"nodeid": 42})[0]["node_id"] == 42


def test_collect_nodes_ignores_non_integer_ids() -> None:
    assert collect_nodes({"node_id": "brightness"}) == []


def test_collect_nodes_handles_empty_and_unexpected_payloads() -> None:
    for payload in (None, {}, [], "text", 7):
        assert collect_nodes(payload) == []


def test_collect_nodes_stops_on_runaway_nesting() -> None:
    """A pathological payload must not blow the stack."""
    payload: dict = {"node_id": 0}
    for _ in range(50):
        payload = {"child": payload}
    assert collect_nodes(payload) == []


# --- summarise -----------------------------------------------------------------


def test_summarise_reports_available_when_nodes_are_found() -> None:
    available, summary = summarise({SETTINGS_PATH: {"verdict": "available"}}, 217)
    assert available is True
    assert "217" in summary


def test_summarise_flags_a_200_with_no_nodes_as_a_stub() -> None:
    available, summary = summarise({SETTINGS_PATH: {"verdict": "available"}}, 0)
    assert available is True
    assert "stub" in summary


def test_summarise_distinguishes_missing_from_refused() -> None:
    _, missing = summarise({SETTINGS_PATH: {"verdict": "not_implemented"}}, 0)
    _, refused = summarise({SETTINGS_PATH: {"verdict": "forbidden"}}, 0)
    assert "key macros" in missing
    assert "re-pair" in refused
    assert missing != refused


def test_summarise_handles_an_unreachable_tv() -> None:
    available, summary = summarise({SETTINGS_PATH: {"verdict": "unreachable"}}, 0)
    assert available is False
    assert "powered on" in summary


def test_summarise_survives_a_missing_result() -> None:
    available, summary = summarise({}, 0)
    assert available is False
    assert summary


# --- endpoint_url --------------------------------------------------------------


class _Client:
    """Stand-in for the ha-philipsjs client's URL-relevant surface."""

    def __init__(self, url=None, protocol="https", api_version=6):
        self.protocol = protocol
        self.api_version = api_version
        if url is not None:
            self._url = url


def test_endpoint_url_prefers_the_library_builder() -> None:
    client = _Client(url=lambda path: f"https://tv:1926/6/{path}")
    assert endpoint_url(client, "10.0.0.1", "system") == "https://tv:1926/6/system"


def test_endpoint_url_falls_back_when_the_builder_raises() -> None:
    def _boom(path):
        raise RuntimeError("gone")

    client = _Client(url=_boom)
    assert endpoint_url(client, "10.0.0.1", "system") == "https://10.0.0.1:1926/6/system"


def test_endpoint_url_uses_the_unsecured_port_for_http() -> None:
    client = _Client(protocol="http")
    assert endpoint_url(client, "10.0.0.1", "system") == "http://10.0.0.1:1925/6/system"


# --- probe_capabilities (end to end, with a stub TV) ---------------------------


class _Response:
    def __init__(self, status, payload=None, content_type="application/json"):
        self.status_code = status
        self._payload = payload
        self.content = b"" if payload is None else json.dumps(payload).encode()
        self.headers = {"content-type": content_type}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _Session:
    """Answers per-path from a map; anything unmapped 404s, like a real TV."""

    def __init__(self, responses):
        self._responses = responses
        self.seen: list[str] = []

    async def request(self, method, url, timeout=None):
        path = url.split("/6/", 1)[1]
        self.seen.append(path)
        result = self._responses.get(path, _Response(404))
        if isinstance(result, Exception):
            raise result
        return result


class _StubClient:
    def __init__(self, responses, menuitems=False):
        self.session = _Session(responses)
        self.protocol = "https"
        self.api_version = 6
        self.os_type = "Linux"
        self.system = {
            "featuring": {
                "jsonfeatures": {"inputkey": ["key"]},
                "systemfeatures": {"os_type": "Linux"},
            }
        }
        self._menuitems = menuitems

    def json_feature_supported(self, type_, value=None):
        return self._menuitems if type_ == "menuitems" else False


class _StubSource:
    def __init__(self, client):
        self.client = client
        self.host = "10.0.0.1"
        self.name = "43PUS7608/12"
        self.model = "43PUS7608/12"
        self.transport_calls = 0

    async def ensure_transport(self):
        self.transport_calls += 1


async def test_probe_reports_a_titan_os_tv_without_the_settings_tree() -> None:
    source = _StubSource(_StubClient({}))
    report = await probe_capabilities(source)

    assert report["host"] == "10.0.0.1"
    assert report["menuitems_advertised"] is False
    assert report["settings_available"] is False
    assert report["endpoints"][SETTINGS_PATH]["verdict"] == "not_implemented"
    assert "key macros" in report["summary"]
    assert source.transport_calls == 1
    # Every endpoint is probed, not just the first failure.
    assert len(report["endpoints"]) == len(PROBE_ENDPOINTS)


async def test_probe_finds_an_unadvertised_settings_tree() -> None:
    structure = {"node": {"node_id": 2000, "string_id": "brightness"}}
    source = _StubSource(_StubClient({SETTINGS_PATH: _Response(200, structure)}))
    report = await probe_capabilities(source)

    assert report["settings_available"] is True
    assert report["settings_nodes"] == 1
    assert report["settings_nodes_sample"][0]["string_id"] == "brightness"
    # Unadvertised but present is exactly the case worth catching.
    assert report["menuitems_advertised"] is False


async def test_probe_omits_the_raw_tree_unless_asked() -> None:
    structure = {"node": {"node_id": 1}}
    responses = {SETTINGS_PATH: _Response(200, structure)}

    lean = await probe_capabilities(_StubSource(_StubClient(responses)))
    assert "raw" not in lean

    full = await probe_capabilities(_StubSource(_StubClient(responses)), include_raw=True)
    assert full["raw"] == structure


async def test_probe_keeps_a_large_body_out_of_the_response() -> None:
    """A screenshot is a JPEG; a service response is no place for it."""
    big = _Response(200, {"blob": "x" * 5000}, content_type="image/jpeg")
    source = _StubSource(_StubClient({"screenshot": big}))
    report = await probe_capabilities(source)

    shot = report["endpoints"]["screenshot"]
    assert shot["verdict"] == "available"
    assert shot["bytes"] > 4096
    assert "json" not in shot


async def test_probe_survives_an_unreachable_endpoint() -> None:
    source = _StubSource(_StubClient({SETTINGS_PATH: OSError("no route to host")}))
    report = await probe_capabilities(source)

    assert report["endpoints"][SETTINGS_PATH]["verdict"] == "unreachable"
    assert report["endpoints"][SETTINGS_PATH]["error"] == "no route to host"
    assert "powered on" in report["summary"]
