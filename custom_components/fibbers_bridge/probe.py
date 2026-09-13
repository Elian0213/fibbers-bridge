"""The probe journal — record a stimulus and what a human saw, in one action.

Firing and recording are the same call (`probe_fire`), so an observation can never
be lost to a forgotten note. Notebooks persist via HA's Store; entries stream to
subscribed cards.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util, ulid as ulid_util

from . import journal, jointspace, remote
from .ambilight import get_source
from .const import (
    DOMAIN,
    PROBE_STORAGE_KEY,
    PROBE_STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

Subscriber = Callable[[dict[str, Any]], None]


# --- subscribers (per notebook) ------------------------------------------------


@callback
def add_probe_subscriber(
    hass: HomeAssistant, notebook_id: str, send: Subscriber
) -> Callable[[], None]:
    """Register a card for one notebook's entries; returns an unsubscribe callback."""
    subs: set[tuple[str, Subscriber]] = hass.data[DOMAIN].setdefault("probe_subscribers", set())
    item = (notebook_id, send)
    subs.add(item)

    @callback
    def _remove() -> None:
        subs.discard(item)

    return _remove


@callback
def _broadcast(hass: HomeAssistant, notebook_id: str, entry: dict[str, Any]) -> None:
    subs: set[tuple[str, Subscriber]] = hass.data.get(DOMAIN, {}).get("probe_subscribers", set())
    for nb_id, send in list(subs):
        if nb_id != notebook_id:
            continue
        try:
            send(entry)
        except Exception:  # noqa: BLE001 - a dead connection must not kill the rest
            subs.discard((nb_id, send))


# --- journal -------------------------------------------------------------------


class ProbeJournal:
    """Notebooks of probe entries, backed by HA Store."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store = Store(hass, PROBE_STORAGE_VERSION, PROBE_STORAGE_KEY)
        self._notebooks: dict[str, dict[str, Any]] = {}
        self._loaded = False

    async def ensure_loaded(self) -> None:
        if self._loaded:
            return
        data = await self._store.async_load()
        self._notebooks = (data or {}).get("notebooks", {})
        self._loaded = True

    def _save(self) -> None:
        self._store.async_delay_save(lambda: {"notebooks": self._notebooks}, 2.0)

    def _get(self, notebook_id: str) -> dict[str, Any]:
        notebook = self._notebooks.get(notebook_id)
        if notebook is None:
            raise ServiceValidationError(f"Unknown notebook: {notebook_id}")
        return notebook

    def create(self, name: str, target: str | None, device: dict[str, Any] | None) -> dict[str, Any]:
        notebook = {
            "id": ulid_util.ulid_now(),
            "name": name,
            "target": target,
            "device": device or {},
            "created": dt_util.utcnow().isoformat(),
            "entries": [],
        }
        self._notebooks[notebook["id"]] = notebook
        self._save()
        return {k: v for k, v in notebook.items() if k != "entries"}

    def list(self) -> list[dict[str, Any]]:
        return [
            {
                "id": nb["id"],
                "name": nb["name"],
                "target": nb.get("target"),
                "entries": len(nb.get("entries", [])),
            }
            for nb in self._notebooks.values()
        ]

    def delete(self, notebook_id: str) -> None:
        self._notebooks.pop(notebook_id, None)
        self._save()

    def entries(self, notebook_id: str) -> list[dict[str, Any]]:
        return list(self._get(notebook_id).get("entries", []))

    def _append(self, notebook_id: str, entry: dict[str, Any]) -> dict[str, Any]:
        self._get(notebook_id)["entries"].append(entry)
        self._save()
        _broadcast(self.hass, notebook_id, entry)
        return entry

    def note(self, notebook_id: str, text: str) -> dict[str, Any]:
        return self._append(notebook_id, _new_entry("note", None, {}, 0, observation=text))

    def annotate(
        self,
        notebook_id: str,
        entry_id: str | None,
        observation: str | None,
        outcome: str | None,
        tags: list[str] | None,
    ) -> dict[str, Any]:
        entries = self._get(notebook_id)["entries"]
        if not entries:
            raise ServiceValidationError("This notebook has no entries to annotate.")
        entry = next((e for e in reversed(entries) if e["id"] == entry_id), None) if entry_id else entries[-1]
        if entry is None:
            raise ServiceValidationError(f"Unknown entry: {entry_id}")
        if observation is not None:
            entry["observation"] = observation
        if outcome is not None:
            entry["outcome"] = outcome
        if tags is not None:
            entry["tags"] = tags
        self._save()
        _broadcast(self.hass, notebook_id, entry)
        return entry

    def export(self, notebook_id: str) -> str:
        return journal.to_markdown(self._get(notebook_id))

    async def promote(
        self, notebook_id: str, entry_ids: list[str], name: str, args: dict[str, Any] | None
    ) -> dict[str, Any]:
        entries = self._get(notebook_id)["entries"]
        chosen = [e for e in entries if e["id"] in set(entry_ids)] if entry_ids else entries
        steps = journal.macro_steps_from_entries(chosen)
        doc = {
            "meta": {"generated": dt_util.utcnow().isoformat(), "source_notebook": notebook_id},
            "macros": {
                name: {
                    "description": f"Promoted from notebook {self._get(notebook_id)['name']}.",
                    "verified": False,
                    "anchor": "home",
                    **({"args": args} if args else {}),
                    "steps": steps,
                }
            },
        }
        path = Path(self.hass.config.path(f"{DOMAIN}/macros/{name}.yaml"))
        text = await self.hass.async_add_executor_job(_write_yaml, path, doc)
        return {"path": str(path), "yaml": text}


def _write_yaml(path: Path, doc: dict[str, Any]) -> str:
    import yaml  # noqa: PLC0415 - PyYAML ships with Home Assistant

    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(doc, sort_keys=False, default_flow_style=False)
    path.write_text(text, encoding="utf-8")
    return text


def _new_entry(
    kind: str,
    target: str | None,
    stimulus: dict[str, Any],
    elapsed_ms: int,
    *,
    observation: str | None = None,
    outcome: str = "unknown",
) -> dict[str, Any]:
    return {
        "id": ulid_util.ulid_now(),
        "ts": dt_util.utcnow().isoformat(),
        "kind": kind,
        "target": target,
        "stimulus": stimulus,
        "elapsed_ms": elapsed_ms,
        "observation": observation,
        "outcome": outcome,
        "tags": [],
    }


def get_journal(hass: HomeAssistant) -> ProbeJournal:
    store = hass.data.setdefault(DOMAIN, {})
    if "probe_journal" not in store:
        store["probe_journal"] = ProbeJournal(hass)
    return store["probe_journal"]


# --- fire: execute a stimulus and record it ------------------------------------


async def fire(
    hass: HomeAssistant,
    notebook_id: str,
    *,
    kind: str,
    entry_id: str | None = None,
    target: str | None = None,
    stimulus: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send a stimulus and record the entry in one action."""
    journal_ = get_journal(hass)
    await journal_.ensure_loaded()
    stimulus = dict(stimulus or {})
    began = time.monotonic()

    if kind == "remote_key":
        source = get_source(hass, _require(entry_id, "entry_id"))
        keys = stimulus.get("keys")
        if not keys:
            single = stimulus.get("command") or stimulus.get("key")
            if single:
                keys = [single]
        if not keys:
            raise ServiceValidationError("remote_key needs keys or a command")
        result = await remote.send_keys(hass, source, list(keys))
        elapsed = result["elapsed_ms"]
        target = target or source.name
        stimulus = {"keys": list(keys)}
    elif kind == "service":
        await hass.services.async_call(
            stimulus["domain"], stimulus["service"], stimulus.get("data") or {}, blocking=True
        )
        elapsed = round((time.monotonic() - began) * 1000)
        target = target or f"{stimulus['domain']}.{stimulus['service']}"
    elif kind == "http":
        source = get_source(hass, _require(entry_id, "entry_id"))
        await jointspace.request_json(
            source, stimulus.get("method", "GET"), stimulus["path"], stimulus.get("body")
        )
        elapsed = round((time.monotonic() - began) * 1000)
        target = target or source.host
    else:
        raise ServiceValidationError(f"Unknown probe kind: {kind}")

    return journal_._append(notebook_id, _new_entry(kind, target, stimulus, elapsed))


def _require(value: str | None, name: str) -> str:
    if not value:
        raise ServiceValidationError(f"{name} is required")
    return value
