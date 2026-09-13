"""Probe journal: annotate-most-recent, empty-notebook errors, export never raises."""

from __future__ import annotations

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.fibbers_bridge.probe import ProbeJournal


async def _journal(hass: HomeAssistant) -> ProbeJournal:
    journal = ProbeJournal(hass)
    await journal.ensure_loaded()
    journal._save = lambda: None  # no delayed-save timer in a unit test
    return journal


async def test_annotate_defaults_to_most_recent(hass: HomeAssistant) -> None:
    journal = await _journal(hass)
    nb = journal.create("n", None, None)["id"]
    journal.note(nb, "first")
    journal.note(nb, "second")
    journal.annotate(nb, None, "seen it", "works", ["tag"])
    last = journal.entries(nb)[-1]
    assert last["observation"] == "seen it"
    assert last["outcome"] == "works"
    assert last["tags"] == ["tag"]


async def test_annotate_empty_notebook_raises(hass: HomeAssistant) -> None:
    journal = await _journal(hass)
    nb = journal.create("n", None, None)["id"]
    with pytest.raises(ServiceValidationError):
        journal.annotate(nb, None, "x", None, None)


async def test_export_zero_entries_does_not_raise(hass: HomeAssistant) -> None:
    journal = await _journal(hass)
    nb = journal.create("empty", None, None)["id"]
    assert "# empty" in journal.export(nb)
