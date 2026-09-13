"""Constants for the Fibbers Bridge integration."""

from __future__ import annotations

DOMAIN = "fibbers_bridge"

# The Home Assistant core Apple TV integration whose connected pyatv object we
# borrow. We never depend on it being installed — every lookup degrades gracefully.
APPLE_TV_DOMAIN = "apple_tv"

# --- Philips Ambilight source --------------------------------------------------
#
# A config entry that carries CONF_HOST is a "Philips Ambilight TV" source: we
# talk to the TV's local JointSpace API (via ha-philipsjs) and read the colours
# the TV itself derives from whatever is on screen — including a games console or
# any other HDMI input, which artwork/metadata can never cover. Home Assistant's
# own philips_js integration deliberately refuses to expose these live colours
# ("would overload the event bus"), which is exactly the gap this bridge fills.

# Entry data keys (names kept identical to core philips_js so credentials paired
# there could be reused verbatim in the future).
CONF_API_VERSION = "api_version"
CONF_SECURED_TRANSPORT = "secured_transport"
CONF_SYSTEM = "system"

# Pairing identity presented to the TV (shown in its "paired apps" list).
PAIR_APP_ID = "fibbers.bridge"
PAIR_APP_NAME = "Fibbers Bridge"

# We prefer JointSpace v6 (v5+ TVs, incl. Titan OS); fall back to v1 for old sets.
API_VERSIONS = (6, 1)

# Ambilight read source: "processed" is the TV's post-processed colour (what the
# LEDs actually show); "measured" is the raw screen sample.
MODE_PROCESSED = "processed"
MODE_MEASURED = "measured"
AMBILIGHT_MODES = (MODE_PROCESSED, MODE_MEASURED)
DEFAULT_MODE = MODE_PROCESSED

# Relay tuning. Tuya (and most cheap Wi-Fi bulbs) drop packets when flooded, so
# we cap the poll/relay rate and skip near-identical colours (dead-band).
DEFAULT_RATE_HZ = 6
MIN_RATE_HZ = 1
MAX_RATE_HZ = 20
DEFAULT_DEADBAND = 8  # per-channel 0–255 delta below which we don't re-send

# Colour modes that can accept an rgb_color (HA converts as needed).
RGB_COLOR_MODES = frozenset({"hs", "rgb", "rgbw", "rgbww", "xy"})

# Dispatcher signal fired when a source reads a fresh colour (drives the sensor).
SIGNAL_SOURCE_UPDATE = f"{DOMAIN}_source_update"

# --- Remote key sequences ------------------------------------------------------
#
# Titan OS gives no feedback, so sequences run server-side with fixed timing
# (measured on a 43PUS7608/12) rather than one key per conversational round trip.

PHILIPS_JS_DOMAIN = "philips_js"

KEY_HOME = "Home"
KEY_BACK = "Back"
KEY_CONFIRM = "Confirm"

DEFAULT_KEY_DELAY_MS = 600  # pause after a cursor move
DEFAULT_SETTLE_MS = 1200  # pause after Confirm (screen changes)
HOME_SETTLE_MS = 3000  # pause after Home / the anchor reset

# Screen-changing keys wait longer than a plain cursor move.
PER_KEY_SETTLE_MS = {KEY_HOME: HOME_SETTLE_MS, KEY_CONFIRM: DEFAULT_SETTLE_MS}

DIRECTIONS = {
    "up": "CursorUp",
    "down": "CursorDown",
    "left": "CursorLeft",
    "right": "CursorRight",
}
_OPPOSITE = {
    "CursorUp": "CursorDown",
    "CursorDown": "CursorUp",
    "CursorLeft": "CursorRight",
    "CursorRight": "CursorLeft",
}

# --- Probe journal -------------------------------------------------------------

PROBE_STORAGE_KEY = f"{DOMAIN}.probes"
PROBE_STORAGE_VERSION = 1
PROBE_KINDS = ("remote_key", "service", "http", "note")
PROBE_OUTCOMES = ("works", "nothing", "error", "unknown")
