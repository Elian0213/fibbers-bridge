"""Named, per-model key macros — shipped with the integration, overridable by the user.

A macro is a reliable key sequence for one thing (e.g. set the picture style). It
says what it *sent*; it can never report what the TV now *is* — Titan OS gives no
feedback.
"""

from __future__ import annotations

import fnmatch
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from . import remote
from .const import DOMAIN

if TYPE_CHECKING:
    from .ambilight import AmbilightSource

_LOGGER = logging.getLogger(__name__)

_TEMPLATE = re.compile(r"^\{\{\s*(\w+)\s*\}\}$")


def _os_type(source: AmbilightSource) -> str | None:
    featuring = (source.system or {}).get("featuring") or {}
    return (featuring.get("systemfeatures") or {}).get("os_type")


def _matches(meta: dict[str, Any], source: AmbilightSource) -> bool:
    model = meta.get("model")
    os_type = meta.get("os_type")
    if model and not fnmatch.fnmatch(source.model or "", model):
        return False
    if os_type and (_os_type(source) or "").lower() != str(os_type).lower():
        return False
    return True


def _load_dir(path: Path) -> list[dict[str, Any]]:
    from homeassistant.util.yaml import load_yaml  # noqa: PLC0415

    files: list[dict[str, Any]] = []
    if not path.is_dir():
        return files
    for yaml_file in sorted(path.glob("*.yaml")):
        try:
            data = load_yaml(str(yaml_file))
        except Exception as err:  # noqa: BLE001 - a broken user file must not kill the rest
            _LOGGER.warning("Skipping macro file %s: %s", yaml_file, err)
            continue
        if isinstance(data, dict):
            files.append(data)
    return files


def _collect(hass: HomeAssistant, source: AmbilightSource) -> dict[str, dict[str, Any]]:
    """Macros matching this TV; user files (loaded last) win on name collision."""
    shipped = Path(__file__).parent / "macros"
    user = Path(hass.config.path(f"{DOMAIN}/macros"))
    macros: dict[str, dict[str, Any]] = {}
    for root in (shipped, user):
        for doc in _load_dir_recursive(root):
            if not _matches(doc.get("meta") or {}, source):
                continue
            for name, macro in (doc.get("macros") or {}).items():
                macros[name] = macro
    return macros


def _load_dir_recursive(root: Path) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if child.is_dir():
                docs.extend(_load_dir(child))
        docs.extend(_load_dir(root))
    return docs


async def list_macros(hass: HomeAssistant, source: AmbilightSource) -> list[dict[str, Any]]:
    macros = await hass.async_add_executor_job(_collect, hass, source)
    return [
        {
            "name": name,
            "description": macro.get("description"),
            "args": macro.get("args") or {},
            "verified": bool(macro.get("verified", False)),
        }
        for name, macro in sorted(macros.items())
    ]


def _validate_args(spec: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    """Range-check args before a single key is sent — half-run navigation is worse than none."""
    resolved: dict[str, Any] = {}
    for name, rule in (spec or {}).items():
        if name not in args:
            raise ServiceValidationError(f"macro needs argument '{name}'")
        value = args[name]
        if rule.get("type") == "int":
            value = int(value)
            low, high = rule.get("min"), rule.get("max")
            if (low is not None and value < low) or (high is not None and value > high):
                raise ServiceValidationError(
                    f"argument '{name}' must be {low}..{high}, got {value}"
                )
        resolved[name] = value
    return resolved


def _resolve(value: Any, args: dict[str, Any]) -> Any:
    if isinstance(value, str) and (m := _TEMPLATE.match(value)):
        return args[m.group(1)]
    if isinstance(value, dict):
        return {k: _resolve(v, args) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, args) for v in value]
    return value


async def run_macro(
    hass: HomeAssistant, source: AmbilightSource, name: str, args: dict[str, Any] | None
) -> dict[str, Any]:
    macros = await hass.async_add_executor_job(_collect, hass, source)
    macro = macros.get(name)
    if macro is None:
        raise ServiceValidationError(f"No macro '{name}' for this TV.")
    resolved = _validate_args(macro.get("args") or {}, args or {})
    steps = _resolve(macro.get("steps") or [], resolved)
    result = await remote.send_keys(
        hass, source, steps, anchor=macro.get("anchor") == "home"
    )
    result["macro"] = name
    result["note"] = "Sent — the TV cannot report whether it took effect."
    return result
