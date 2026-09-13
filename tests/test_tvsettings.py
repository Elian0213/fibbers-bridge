"""build_controls merge logic and the read/write shape quirks — no TV needed."""

from __future__ import annotations

from custom_components.fibbers_bridge.tvsettings import (
    build_controls,
    control_value,
    write_payload,
)

# A cut-down 43PUS7608/12 tree: empty picture branch, a slider, an enum, a
# wall-colour node, a slider missing from `current`, a multi-slider, and a type
# we don't handle.
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
                                "data": {
                                    "enums": [
                                        {"enum_id": 1, "string_id": "s1"},
                                        {"enum_id": 2, "string_id": "s2"},
                                    ]
                                },
                            },
                            {
                                "node_id": 700,
                                "type": "PARENT_NODE",
                                "context": "ambilight_advanced",
                                "data": {
                                    "nodes": [
                                        {
                                            "node_id": 710,
                                            "type": "SLIDER_NODE",
                                            "context": "ambilight_brightness",
                                            "string_id": "BRI",
                                            "data": {"slider_data": {"min": 0, "max": 100, "step": 5}},
                                        },
                                        {
                                            "node_id": 720,
                                            "type": "SLIDER_NODE",
                                            "context": "ambilight_saturation",
                                            "data": {"slider_data": {"min": 0, "max": 100, "step": 1}},
                                        },
                                        {
                                            "node_id": 730,
                                            "type": "WALL_COLOR_NODE",
                                            "context": "ambilight_wall_color",
                                            "data": {"colors": [16711680, 65280]},
                                        },
                                        {
                                            "node_id": 800,
                                            "type": "MULTIPLE_SLIDER",
                                            "context": "ambisleep_curve",
                                            "data": {"sliders": [{"slider_id": "a"}]},
                                        },
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

CURRENT = {
    710: {"nodeid": 710, "controllable": True, "available": True, "value": {"data": {"slider_id": "br", "value": 40}}},
    320: {
        "nodeid": 320,
        "controllable": True,
        "available": True,
        "value": {
            "data": {
                "selected_item": 2,
                "enum_values": [
                    {"enum_id": 2, "controllable": True, "available": True},
                    {"enum_id": 3, "controllable": False, "available": True},
                ],
            }
        },
    },
    730: {"nodeid": 730, "controllable": True, "available": True, "value": {"data": {"selected_item": 65280}}},
    800: {"nodeid": 800, "controllable": True, "available": True, "value": {"data": {}}},
    # 720 deliberately absent
}


def _by_id(controls):
    return {c["node_id"]: c for c in controls}


def test_slider_merges_structure_bounds_with_current_value():
    controls, _ = build_controls(STRUCTURE, CURRENT)
    s = _by_id(controls)[710]
    assert s["kind"] == "slider"
    assert (s["min"], s["max"], s["step"]) == (0, 100, 5)
    assert s["value"] == 40
    assert s["available"] is True


def test_enum_merges_option_text_with_flags_and_keeps_one_sided_options():
    controls, _ = build_controls(STRUCTURE, CURRENT)
    e = _by_id(controls)[320]
    assert e["kind"] == "enum"
    assert e["value"] == 2
    opts = {o["enum_id"]: o for o in e["options"]}
    assert set(opts) == {1, 2, 3}  # 1 structure-only, 3 current-only both survive
    assert opts[1]["string_id"] == "s1"
    assert opts[2]["controllable"] is True
    assert opts[3]["controllable"] is False


def test_parent_nodes_become_groups_in_tree_order_not_controls():
    controls, groups = build_controls(STRUCTURE, CURRENT)
    assert groups == ["ambilight", "ambilight_advanced"]
    assert 3 not in _by_id(controls)  # PARENT_NODE isn't a control


def test_node_missing_from_current_ships_unavailable():
    controls, _ = build_controls(STRUCTURE, CURRENT)
    sat = _by_id(controls)[720]
    assert sat["value"] is None
    assert sat["available"] is False


def test_empty_picture_parent_yields_nothing():
    controls, groups = build_controls(STRUCTURE, CURRENT)
    assert "picture" not in groups
    assert all(c["context"] != "picture" for c in controls)


def test_multi_slider_is_listed_read_only():
    ms = _by_id(build_controls(STRUCTURE, CURRENT)[0])[800]
    assert ms["kind"] == "multi_slider"
    assert ms["read_only"] is True


def test_unknown_type_is_skipped():
    assert 999 not in _by_id(build_controls(STRUCTURE, CURRENT)[0])


def test_colors_node_exposes_palette_and_selection():
    c = _by_id(build_controls(STRUCTURE, CURRENT)[0])[730]
    assert c["kind"] == "colors"
    assert c["options"] == [16711680, 65280]
    assert c["value"] == 65280


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
