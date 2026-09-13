"""Raw JointSpace calls that bypass ha-philipsjs's feature gating.

Titan OS serves menuitems/ambilight endpoints it doesn't advertise, and the
library returns None for anything unadvertised (and folds every error into None).
We reuse its authenticated session but talk to the TV directly and keep the status.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .ambilight import AmbilightSource

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = 8.0
_HTTP_PORT = 1925
_HTTPS_PORT = 1926


class JointSpaceError(Exception):
    """A non-2xx JointSpace response, or an unreachable TV (status None)."""

    def __init__(self, status: int | None, path: str, detail: str = "") -> None:
        self.status = status
        self.path = path
        msg = f"{path} -> {status if status is not None else 'unreachable'}"
        super().__init__(f"{msg}: {detail}" if detail else msg)


def _url(client: Any, path: str) -> str:
    builder = getattr(client, "_url", None)
    if callable(builder):
        try:
            return builder(path)
        except Exception:  # noqa: BLE001 - construct it ourselves instead
            pass
    protocol = getattr(client, "protocol", "https") or "https"
    port = _HTTPS_PORT if protocol == "https" else _HTTP_PORT
    return f"{protocol}://{getattr(client, '_host', '')}:{port}/{getattr(client, 'api_version', 6)}/{path}"


async def request_json(
    source: AmbilightSource, method: str, path: str, body: Any | None = None
) -> Any:
    """Call the TV and return parsed JSON (None on empty body). Raises JointSpaceError."""
    await source.ensure_transport()
    client = source.client
    try:
        resp = await client.session.request(
            method, _url(client, path), json=body, timeout=_TIMEOUT
        )
    except Exception as err:  # noqa: BLE001 - httpx errors vary by failure mode
        raise JointSpaceError(None, path, str(err)) from err

    if resp.status_code // 100 != 2:
        raise JointSpaceError(resp.status_code, path)
    if not resp.content:
        return None
    try:
        return resp.json()
    except ValueError:
        return None
