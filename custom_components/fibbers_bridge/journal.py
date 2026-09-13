"""Pure probe-journal helpers — markdown export and macro extraction.

Kept free of Home Assistant so the rendering and promotion rules can be tested
without a running instance.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .keyseq import collapse_repeats, with_anchor


def _command(entry: Mapping[str, Any]) -> str | None:
    stimulus = entry.get("stimulus") or {}
    return stimulus.get("command") or stimulus.get("key")


def macro_steps_from_entries(
    entries: Sequence[Mapping[str, Any]], *, anchor: bool = True
) -> list[Any]:
    """Collapse a run of remote-key entries into macro steps, anchored by default."""
    keys = [cmd for e in entries if e.get("kind") == "remote_key" and (cmd := _command(e))]
    steps: list[Any] = [
        {"key": c["key"], "repeat": c["repeat"]} if c["repeat"] > 1 else c["key"]
        for c in collapse_repeats(keys)
    ]
    return with_anchor(steps) if anchor else steps


def _stimulus_text(entry: Mapping[str, Any]) -> str:
    stimulus = entry.get("stimulus") or {}
    if entry.get("kind") == "remote_key":
        keys = stimulus.get("keys") or ([stimulus["command"]] if stimulus.get("command") else [])
        return " ".join(str(k) for k in keys) or "—"
    if entry.get("kind") == "service":
        return f"{stimulus.get('domain', '?')}.{stimulus.get('service', '?')}"
    if entry.get("kind") == "http":
        return f"{stimulus.get('method', 'GET')} {stimulus.get('path', '')}".strip()
    return "—"


def to_markdown(notebook: Mapping[str, Any]) -> str:
    """Render a notebook as a markdown document: device table, then the entries."""
    lines = [f"# {notebook.get('name', 'Probe notebook')}", ""]

    device = notebook.get("device") or {}
    if device:
        lines.append("| | |")
        lines.append("| --- | --- |")
        for key, value in device.items():
            lines.append(f"| {key} | {value} |")
        lines.append("")

    lines.append("| Time | Kind | Stimulus | Outcome | Observation |")
    lines.append("| --- | --- | --- | --- | --- |")
    for entry in notebook.get("entries") or []:
        lines.append(
            "| {ts} | {kind} | {stimulus} | {outcome} | {observation} |".format(
                ts=str(entry.get("ts", "")).replace("|", "\\|"),
                kind=entry.get("kind", ""),
                stimulus=_stimulus_text(entry).replace("|", "\\|"),
                outcome=entry.get("outcome", "") or "",
                observation=str(entry.get("observation") or "").replace("|", "\\|"),
            )
        )
    return "\n".join(lines) + "\n"
