"""build_controls merge logic and the read/write envelope shapes — no TV needed."""

from __future__ import annotations

from custom_components.fibbers_bridge.tvsettings import (
    build_controls,
    control_value,
    parse_current,
    update_body,
    write_payload,
)

# A cut-down 43PUS7608/12 tree: empty picture branch, a slider, an enum, a
# wall-colour node, a slider missing from the read, a multi-slider, an unknown type.
STRUCTURE = {
    "version": 4,
    "node": {
        "node_id": 1,
        "type": "PARENT_NODE",
        "context": "Setup_Menu",
        "data": {
            "nodes": [
                {"node_id": 2, "type": "PARENT_NODE", "context": "picture", "data": {}},
                {
                    "node_id": 3,
                    "type": "PARENT_NODE",
                    "context": "ambilight",
                    "data": {
                        "nodes": [
                            {
                                "node_id": 320,
                                "type": "LIST_NODE",
                                "context": "ambilight_follow_video",
                                "data": {"enums": [{"enum_id": 1, "string_id": "s1"}, {"enum_id": 2, "string_id": "s2"}]},
                            },
                            {
                                "node_id": 700,
                                "type": "PARENT_NODE",
                                "context": "ambilight_advanced",
                                "data": {
                                    "nodes": [
                                        {"node_id": 710, "type": "SLIDER_NODE", "context": "ambilight_brightness", "string_id": "BRI", "data": {"slider_data": {"min": 0, "max": 100, "step": 5}}},
                                        {"node_id": 720, "type": "SLIDER_NODE", "context": "ambilight_saturation", "data": {"slider_data": {"min": 0, "max": 100, "step": 1}}},
                                        {"node_id": 730, "type": "WALL_COLOR_NODE", "context": "ambilight_wall_color", "data": {"colors": [16711680, 65280]}},
                                        {"node_id": 800, "type": "MULTIPLE_SLIDER", "context": "ambisleep_curve", "data": {"sliders": [{"slider_id": "a"}]}},
                                        {"node_id": 999, "type": "WEIRD_NODE", "context": "mystery", "data": {}},
                                    ]
                                },
                            },
                        ]
                    },
                },
            ]
        },
    },
}

# Normalised current entries, as parse_current produces them (720 absent).
CURRENT = {
    710: {"node_id": 710, "controllable": True, "available": True, "data": {"slider_id": "br", "value": 40}},
    320: {"node_id": 320, "controllable": True, "available": True, "data": {"selected_item": 2, "enum_values": [{"enum_id": 2, "controllable": True, "available": True}, {"enum_id": 3, "controllable": False, "available": True}]}},
    730: {"node_id": 730, "controllable": True, "available": True, "data": {"selected_item": 65280}},
    800: {"node_id": 800, "controllable": True, "available": True, "data": {}},
}


def _by_id(controls):
    return {c["node_id"]: c for c in controls}


# --- parse_current (the bug 0.5.1 fixes) ---------------------------------------


def test_parse_current_reads_the_values_envelope():
    resp = {
        "version": 4,
        "values": [
            {"value": {"Nodeid": 710, "Controllable": True, "Available": True, "string_id": "BRI", "data": {"slider_id": "br", "value": 40}}},
        ],
    }
    out = parse_current(resp)
    assert set(out) == {710}
    assert out[710]["controllable"] is True and out[710]["available"] is True
    assert out[710]["string_id"] == "BRI"
    assert out[710]["data"] == {"slider_id": "br", "value": 40}


def test_parse_current_empty_and_wrong_shape_return_empty():
    assert parse_current({"values": []}) == {}
    assert parse_current(None) == {}
    # the old wrong assumption must not silently come back
    assert parse_current({"nodes": [{"nodeid": 710, "value": {"data": {"value": 1}}}]}) == {}


def test_parse_current_recovers_data_beside_value():
    resp = {"values": [{"value": {"Nodeid": 9, "Controllable": True, "Available": True}, "data": {"value": 5}}]}
    assert parse_current(resp)[9]["data"] == {"value": 5}


def test_update_body_capitalises_nodeid():
    assert update_body(710, {"slider_id": "br", "value": 60}) == {
        "values": [{"value": {"Nodeid": 710, "data": {"slider_id": "br", "value": 60}}}]
    }


# --- build_controls ------------------------------------------------------------


def test_slider_merges_structure_bounds_with_current_value():
    s = _by_id(build_controls(STRUCTURE, CURRENT)[0])[710]
    assert (s["min"], s["max"], s["step"], s["value"]) == (0, 100, 5, 40)
    assert s["available"] is True and s["read_failed"] is False


def test_enum_merges_option_text_with_flags_and_keeps_one_sided_options():
    e = _by_id(build_controls(STRUCTURE, CURRENT)[0])[320]
    assert e["value"] == 2
    opts = {o["enum_id"]: o for o in e["options"]}
    assert set(opts) == {1, 2, 3}
    assert opts[1]["string_id"] == "s1" and opts[3]["controllable"] is False


def test_parent_nodes_become_groups_in_tree_order():
    controls, groups = build_controls(STRUCTURE, CURRENT)
    assert groups == ["ambilight", "ambilight_advanced"]
    assert 3 not in _by_id(controls)


def test_node_missing_from_read_is_read_failed():
    sat = _by_id(build_controls(STRUCTURE, CURRENT)[0])[720]
    assert sat["value"] is None
    assert sat["available"] is False
    assert sat["read_failed"] is True


def test_empty_picture_parent_yields_nothing():
    controls, groups = build_controls(STRUCTURE, CURRENT)
    assert "picture" not in groups
    assert all(c["context"] != "picture" for c in controls)


def test_multi_slider_read_only_and_unknown_skipped():
    by = _by_id(build_controls(STRUCTURE, CURRENT)[0])
    assert by[800]["read_only"] is True
    assert 999 not in by


def test_colors_node_exposes_palette_and_selection():
    c = _by_id(build_controls(STRUCTURE, CURRENT)[0])[730]
    assert c["options"] == [16711680, 65280] and c["value"] == 65280


def test_empty_structure_is_safe():
    assert build_controls(None, {}) == ([], [])
    assert build_controls({}, {}) == ([], [])


# --- write shape quirks --------------------------------------------------------


def test_write_payload_enum_renames_the_key():
    assert write_payload("enum", 320, {}) == {"select_item": 320}
    assert write_payload("colors", 65280, {}) == {"select_item": 65280}


def test_write_payload_slider_echoes_its_id():
    assert write_payload("slider", 60, {"slider_id": "br"}) == {"slider_id": "br", "value": 60}


def test_control_value_reads_the_right_field_per_kind():
    assert control_value("slider", {"value": 40}) == 40
    assert control_value("enum", {"selected_item": 2}) == 2
    assert control_value("colors", {"selected_item": 7}) == 7
