"""Constants for the Fibbers Bridge integration."""

from __future__ import annotations

DOMAIN = "fibbers_bridge"

# The Home Assistant core Apple TV integration whose connected pyatv object we
# borrow. We never depend on it being installed — every lookup degrades gracefully.
APPLE_TV_DOMAIN = "apple_tv"
