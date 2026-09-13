"""Pure probe-journal helpers — markdown export and macro extraction."""

from __future__ import annotations

from custom_components.fibbers_bridge.journal import macro_steps_from_entries, to_markdown


def _key(cmd: str) -> dict:
    return {"kind": "remote_key", "stimulus": {"command": cmd}}


def test_macro_steps_collapse_and_anchor():
    steps = macro_steps_from_entries([_key("CursorUp"), _key("CursorUp"), _key("Confirm")])
    # anchor prepended (Back x3 -> Home), then the collapsed run
    assert steps[:3] == [{"key": "Back"}, {"key": "Back"}, {"key": "Back"}]
    assert steps[-2:] == [{"key": "CursorUp", "repeat": 2}, "Confirm"]


def test_macro_steps_can_skip_anchor():
    steps = macro_steps_from_entries([_key("Home")], anchor=False)
    assert steps == ["Home"]


def test_to_markdown_zero_entries_does_not_raise():
    md = to_markdown({"name": "Empty", "entries": []})
    assert "# Empty" in md
    assert "| Time | Kind |" in md


def test_to_markdown_renders_device_and_entries():
    notebook = {
        "name": "N",
        "device": {"Model": "43PUS7608/12"},
        "entries": [
            {"ts": "t1", "kind": "remote_key", "stimulus": {"keys": ["Home"]}, "outcome": "works", "observation": "home"},
        ],
    }
    md = to_markdown(notebook)
    assert "| Model | 43PUS7608/12 |" in md
    assert "Home" in md and "works" in md
