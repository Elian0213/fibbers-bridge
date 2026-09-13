"""Read/write the TV's menuitems/settings tree, and flatten it for a card.

Structure (labels, ranges, options) and current (values, availability) come from
two separate endpoints; build_controls merges them. Write shapes differ from read
shapes on this firmware — see write_payload — and the TV answers 200 to writes it
ignores, so a write is confirmed by reading the value back (changed).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from . import jointspace

if TYPE_CHECKING:
    from .ambilight import AmbilightSource

_LOGGER = logging.getLogger(__name__)

KIND_BY_TYPE = {
    "SLIDER_NODE": "slider",
    "LIST_NODE": "enum",
    "WALL_COLOR_NODE": "colors",
    "COLOR_PICKER_NODE": "colors",
    "MULTIPLE_SLIDER": "multi_slider",
}

_STRUCTURE = "menuitems/settings/structure"
_CURRENT = "menuitems/settings/current"
_UPDATE = "menuitems/settings/update"
_STRINGS = "menuitems/settings/strings"


# --- pure helpers --------------------------------------------------------------


def _node_id(node: Mapping[str, Any]) -> int | None:
    nid = node.get("node_id", node.get("nodeid"))
    return nid if isinstance(nid, int) else None


def _children(node: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    data = node.get("data")
    nodes = data.get("nodes") if isinstance(data, Mapping) else None
    return [n for n in nodes if isinstance(n, Mapping)] if isinstance(nodes, list) else []


def _cur_data(cur: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """The type-specific data dict of a parsed current entry."""
    data = cur.get("data") if isinstance(cur, Mapping) else None
    return data if isinstance(data, Mapping) else {}


def parse_current(resp: Mapping[str, Any] | None) -> dict[int, dict[str, Any]]:
    """{node_id: entry} from a menuitems/settings/current response.

    The TV replies `values:[{value:{Nodeid,Controllable,Available,string_id,data}}]`
    — capitalised, under `values` not `nodes`. Some firmwares put `data` beside
    `value` rather than inside it, so recover that too.
    """
    out: dict[int, dict[str, Any]] = {}
    for entry in (resp or {}).get("values", []):
        value = entry.get("value") if isinstance(entry, Mapping) else None
        if not isinstance(value, Mapping):
            continue
        nid = value.get("Nodeid")
        if not isinstance(nid, int):
            continue
        data = value.get("data")
        if not isinstance(data, Mapping) and isinstance(entry.get("data"), Mapping):
            data = entry["data"]
        out[nid] = {
            "node_id": nid,
            "controllable": bool(value.get("Controllable")),
            "available": bool(value.get("Available")),
            "string_id": value.get("string_id"),
            "data": data if isinstance(data, Mapping) else {},
        }
    return out


def update_body(node_id: int, payload: Mapping[str, Any]) -> dict[str, Any]:
    """menuitems/settings/update envelope — Nodeid is capitalised on write."""
    return {"values": [{"value": {"Nodeid": node_id, "data": payload}}]}


def control_value(kind: str, data: Mapping[str, Any]) -> Any:
    if kind == "enum":
        return data.get("selected_item")
    if kind == "colors":
        return data.get("selected_item", data.get("value"))
    return data.get("value")


def slider_bounds(struct_data: Mapping[str, Any]) -> dict[str, Any]:
    sd = struct_data.get("slider_data")
    sd = sd if isinstance(sd, Mapping) else {}
    return {"min": sd.get("min", 0), "max": sd.get("max", 100), "step": sd.get("step", 1)}


def enum_options(
    struct_data: Mapping[str, Any], cur_data: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Merge option text (structure) with per-option flags (current), keyed by id."""
    by_id: dict[int, dict[str, Any]] = {}
    for opt in struct_data.get("enums") or []:
        if isinstance(opt, Mapping) and isinstance(opt.get("enum_id"), int):
            by_id[opt["enum_id"]] = {
                "enum_id": opt["enum_id"],
                "string_id": opt.get("string_id"),
            }
    for opt in cur_data.get("enum_values") or []:
        if isinstance(opt, Mapping) and isinstance(opt.get("enum_id"), int):
            row = by_id.setdefault(opt["enum_id"], {"enum_id": opt["enum_id"]})
            row["controllable"] = opt.get("controllable", True)
            row["available"] = opt.get("available", True)
    return [by_id[k] for k in sorted(by_id)]


def _control(
    node: Mapping[str, Any], parent_context: str | None, current: Mapping[int, Any]
) -> dict[str, Any] | None:
    nid = _node_id(node)
    ntype = node.get("type")
    kind = KIND_BY_TYPE.get(ntype)
    if nid is None or kind is None:
        return None

    struct_data = node.get("data") if isinstance(node.get("data"), Mapping) else {}
    cur = current.get(nid)
    cur_data = _cur_data(cur)
    present = cur is not None

    ctrl: dict[str, Any] = {
        "node_id": nid,
        "type": ntype,
        "kind": kind,
        "context": node.get("context"),
        "string_id": node.get("string_id"),
        "parent_context": parent_context,
        "value": control_value(kind, cur_data) if present else None,
        "controllable": bool(cur.get("controllable")) if present else False,
        "available": bool(cur.get("available")) if present else False,
        "read_failed": not present,
        "options": None,
    }
    if kind == "slider":
        ctrl.update(slider_bounds(struct_data))
    elif kind == "enum":
        ctrl["options"] = enum_options(struct_data, cur_data)
    elif kind == "colors":
        ctrl["options"] = list(struct_data.get("colors") or [])
    elif kind == "multi_slider":
        ctrl["sliders"] = list(struct_data.get("sliders") or [])
        ctrl["read_only"] = True
    return ctrl


def build_controls(
    structure: Mapping[str, Any] | None, current: Mapping[int, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Flatten the tree into controls + the ordered list of section contexts."""
    controls: list[dict[str, Any]] = []
    groups: list[str] = []

    def walk(node: Mapping[str, Any], parent_context: str | None) -> None:
        if node.get("type") == "PARENT_NODE":
            context = node.get("context")
            kids = _children(node)
            if context and kids and context not in groups:
                groups.append(context)
            for kid in kids:
                walk(kid, context or parent_context)
            return
        ctrl = _control(node, parent_context, current)
        if ctrl is not None:
            controls.append(ctrl)

    root = None
    if isinstance(structure, Mapping):
        root = structure.get("node") or structure
    if isinstance(root, Mapping):
        if isinstance(root.get("nodes"), list):
            for n in root["nodes"]:
                if isinstance(n, Mapping):
                    walk(n, None)
        else:
            walk(root, None)

    # only keep sections that actually produced a control
    used = {c["parent_context"] for c in controls}
    groups = [g for g in groups if g in used]
    return controls, groups


def write_payload(kind: str, value: Any, cur_data: Mapping[str, Any]) -> dict[str, Any]:
    """The inner data dict for an update. Read/write keys differ on this firmware."""
    if kind == "enum" or kind == "colors":
        return {"select_item": value}  # NOT selected_item
    if kind == "slider":
        # the slider id read from current has to be echoed with the new value
        return {"slider_id": cur_data.get("slider_id"), "value": value}
    return {"value": value}


def _kind_from_current(cur_data: Mapping[str, Any]) -> str:
    if "slider_id" in cur_data:
        return "slider"
    if "selected_item" in cur_data or "enum_values" in cur_data:
        return "enum"
    return "value"


# --- I/O -----------------------------------------------------------------------


async def read_current(
    source: AmbilightSource, node_ids: list[int]
) -> dict[int, dict[str, Any]]:
    body = {"nodes": [{"nodeid": nid} for nid in node_ids]}
    resp = await jointspace.request_json(source, "POST", _CURRENT, body)
    return parse_current(resp)


# JointSpace rejects large `current` batches; ha-philipsjs chunks at the same size.
_SWEEP_CHUNK = 10


async def sweep_settings(
    source: AmbilightSource, start: int, end: int, step: int = 1
) -> dict[str, Any]:
    """Read every node id in [start, end] and report the ones that answered."""
    ids = list(range(start, end + 1, step if step > 0 else 1))
    found: list[dict[str, Any]] = []
    for i in range(0, len(ids), _SWEEP_CHUNK):
        for nid, entry in (await read_current(source, ids[i : i + _SWEEP_CHUNK])).items():
            data = entry.get("data") or {}
            found.append(
                {
                    "node_id": nid,
                    "string_id": entry.get("string_id"),
                    "controllable": entry.get("controllable"),
                    "value": data.get("value", data.get("selected_item")),
                }
            )
    found.sort(key=lambda f: f["node_id"])
    return {"scanned": len(ids), "found": found}


async def write_node(
    source: AmbilightSource,
    node_id: int,
    value: Any = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    before = await read_current(source, [node_id])
    cur = before.get(node_id)
    cur_data = _cur_data(cur)
    kind = _kind_from_current(cur_data)

    if cur is not None and not cur.get("controllable", True):
        return {
            "node_id": node_id,
            "changed": False,
            "note": "The TV reports this setting as not controllable right now.",
        }

    payload = data if data is not None else write_payload(kind, value, cur_data)
    await jointspace.request_json(source, "POST", _UPDATE, update_body(node_id, payload))

    after = await read_current(source, [node_id])
    before_v = control_value(kind, cur_data)
    after_v = control_value(kind, _cur_data(after.get(node_id)))
    changed = before_v != after_v
    return {
        "node_id": node_id,
        "changed": changed,
        "before": before_v,
        "after": after_v,
        "note": None if changed else "The TV accepted the change but didn't apply it.",
    }


async def get_strings(source: AmbilightSource, ids: list[str]) -> dict[str, str]:
    """Best-effort label lookup; Titan OS 403s here, which we treat as 'no labels'."""
    if not ids:
        return {}
    try:
        resp = await jointspace.request_json(
            source, "POST", _STRINGS, {"strings": [{"string_id": s} for s in ids]}
        )
    except jointspace.JointSpaceError:
        return {}
    out: dict[str, str] = {}
    for row in (resp or {}).get("strings", []):
        sid, text = row.get("string_id"), row.get("string_translation")
        if sid and text:
            out[sid] = text
    return out


async def _ambilight_info(source: AmbilightSource) -> dict[str, Any]:
    power = leds = None
    try:
        power = (await jointspace.request_json(source, "GET", "ambilight/power") or {}).get("power")
    except jointspace.JointSpaceError:
        pass
    try:
        topo = await jointspace.request_json(source, "GET", "ambilight/topology") or {}
        leds = sum(int(topo.get(side, 0)) for side in ("left", "top", "right", "bottom"))
    except (jointspace.JointSpaceError, TypeError, ValueError):
        pass
    return {"power": power, "leds": leds}


async def list_settings(
    source: AmbilightSource, *, refresh: bool = False
) -> dict[str, Any]:
    structure = await source.settings_structure(refresh=refresh)

    node_ids: list[int] = []

    def collect(node: Mapping[str, Any]) -> None:
        if node.get("type") in KIND_BY_TYPE:
            nid = _node_id(node)
            if nid is not None:
                node_ids.append(nid)
        for kid in _children(node):
            collect(kid)

    if isinstance(structure, Mapping):
        root = structure.get("node") or structure
        collect(root) if isinstance(root, Mapping) else None

    current = await read_current(source, node_ids) if node_ids else {}
    controls, groups = build_controls(structure, current)

    labels = await get_strings(source, [c["string_id"] for c in controls if c.get("string_id")])
    if labels:
        for c in controls:
            text = labels.get(c.get("string_id"))
            if text:
                c["label"] = text

    return {
        "host": source.host,
        "name": source.name,
        "version": (structure or {}).get("version") if isinstance(structure, Mapping) else None,
        "ambilight": await _ambilight_info(source),
        "controls": controls,
        "groups": groups,
    }
