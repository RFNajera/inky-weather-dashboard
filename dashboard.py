#!/usr/bin/env python3
"""
Inky pHAT weather dashboard for Mt. Airy, Maryland.

Layout:
  * Left ~2/3 of the display: three text lines
      1. Date and time
      2. Current weather conditions + temperature
      3. Air Quality Index (US AQI)
  * Right ~1/3 of the display: a weather-state icon
      - Sun (day) or Moon (night) as the base, plus cloud / rain / snow /
        lightning / fog overlays depending on conditions.

Data comes from the Open-Meteo APIs (no API key required).

Works with the 4-colour Inky pHAT (red/yellow/black/white, 250x122) as well as
the older 3-colour boards; the layout is driven by the detected resolution.

Designed to be run once per invocation (e.g. from a systemd timer).
The overnight quiet window (23:00-05:00) is enforced here as a safety net.
"""

import sys
import logging
from datetime import datetime
from pathlib import Path

import requests

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------

# Mt. Airy, Maryland
LATITUDE = 39.3762
LONGITUDE = -77.1547
TIMEZONE = "America/New_York"

# Fallback colour if EEPROM auto-detect fails. For the 4-colour board use
# "red" (the library treats red/yellow as palette index 2 either way).
INKY_COLOUR = "red"

# Overnight quiet window (24h clock). During these hours nothing is drawn.
QUIET_START_HOUR = 23  # 11 PM
QUIET_END_HOUR = 5     # 5 AM

# Fraction of the width reserved for the text column (left side).
TEXT_FRACTION = 2 / 3

# Network timeout (seconds) for API calls.
HTTP_TIMEOUT = 20

# ----------------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("inky-dashboard")

# ----------------------------------------------------------------------------
# WMO weather interpretation codes -> short labels + icon category
# ----------------------------------------------------------------------------

# icon categories: clear, cloudy, partly, fog, rain, snow, storm
WMO = {
    0:  ("Clear",         "clear"),
    1:  ("Mainly clear",  "partly"),
    2:  ("Partly cloudy", "partly"),
    3:  ("Overcast",      "cloudy"),
    45: ("Fog",           "fog"),
    48: ("Rime fog",      "fog"),
    51: ("Lt drizzle",    "rain"),
    53: ("Drizzle",       "rain"),
    55: ("Drizzle",       "rain"),
    56: ("Frz drizzle",   "rain"),
    57: ("Frz drizzle",   "rain"),
    61: ("Light rain",    "rain"),
    63: ("Rain",          "rain"),
    65: ("Heavy rain",    "rain"),
    66: ("Frz rain",      "rain"),
    67: ("Frz rain",      "rain"),
    71: ("Light snow",    "snow"),
    73: ("Snow",          "snow"),
    75: ("Heavy snow",    "snow"),
    77: ("Snow grains",   "snow"),
    80: ("Lt showers",    "rain"),
    81: ("Showers",       "rain"),
    82: ("Hvy showers",   "rain"),
    85: ("Snow showers",  "snow"),
    86: ("Snow showers",  "snow"),
    95: ("T-storm",       "storm"),
    96: ("Storm+hail",    "storm"),
    99: ("Storm+hail",    "storm"),
}


def wmo_label(code):
    return WMO.get(code, (f"Code {code}", "cloudy"))[0]


def wmo_icon(code):
    return WMO.get(code, ("", "cloudy"))[1]


def aqi_label(aqi):
    if aqi is None:
        return "n/a"
    if aqi <= 50:
        return "Good"
    if aqi <= 100:
        return "Moderate"
    if aqi <= 150:
        return "Unhlthy SG"
    if aqi <= 200:
        return "Unhealthy"
    if aqi <= 300:
        return "V.Unhlthy"
    return "Hazardous"


# ----------------------------------------------------------------------------
# Data fetching
# ----------------------------------------------------------------------------

def fetch_weather():
    """Return (temp_f, weather_code, is_day) or (None, None, 1) on failure."""
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LATITUDE}&longitude={LONGITUDE}"
        "&current=temperature_2m,weather_code,is_day"
        "&temperature_unit=fahrenheit"
        f"&timezone={TIMEZONE}"
    )
    try:
        r = requests.get(url, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        cur = r.json().get("current", {})
        return (
            cur.get("temperature_2m"),
            cur.get("weather_code"),
            cur.get("is_day", 1),
        )
    except Exception as e:
        log.warning("Weather fetch failed: %s", e)
        return None, None, 1


def fetch_aqi():
    """Return US AQI (int) or None on failure."""
    url = (
        "https://air-quality-api.open-meteo.com/v1/air-quality"
        f"?latitude={LATITUDE}&longitude={LONGITUDE}"
        "&current=us_aqi"
        f"&timezone={TIMEZONE}"
    )
    try:
        r = requests.get(url, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        aqi = r.json().get("current", {}).get("us_aqi")
        return int(round(aqi)) if aqi is not None else None
    except Exception as e:
        log.warning("AQI fetch failed: %s", e)
        return None


# ----------------------------------------------------------------------------
# Content
# ----------------------------------------------------------------------------

def build_content():
    now = datetime.now()
    date_line = now.strftime("%a %b %-d")
    # 24-hour time keeps the top line narrow (no AM/PM).
    time_line = now.strftime("%H:%M")

    temp_f, code, is_day = fetch_weather()
    if temp_f is not None:
        weather_line = f"{wmo_label(code)} {round(temp_f)}\u00b0F"
        icon = wmo_icon(code)
    else:
        weather_line = "Weather n/a"
        icon = "cloudy"

    aqi = fetch_aqi()
    if aqi is not None:
        aqi_line = f"AQI {aqi} {aqi_label(aqi)}"
    else:
        aqi_line = "AQI n/a"

    # Combine date + time into one compact top line.
    line1 = f"{date_line} {time_line}"
    return {
        "lines": [line1, weather_line, aqi_line],
        "icon": icon,
        "is_day": bool(is_day),
    }


# ----------------------------------------------------------------------------
# Icon drawing (programmatic, no image files needed)
# ----------------------------------------------------------------------------

def _draw_sun(draw, cx, cy, r, colour):
    import math
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=colour)
    # rays
    for a in range(0, 360, 45):
        rad = math.radians(a)
        x1 = cx + int((r + 3) * math.cos(rad))
        y1 = cy + int((r + 3) * math.sin(rad))
        x2 = cx + int((r + 9) * math.cos(rad))
        y2 = cy + int((r + 9) * math.sin(rad))
        draw.line((x1, y1, x2, y2), fill=colour, width=2)


def _draw_moon(draw, cx, cy, r, colour):
    # Crescent: full disc, then punch out an offset disc in white.
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=colour)
    off = int(r * 0.6)
    draw.ellipse(
        (cx - r + off, cy - r - 2, cx + r + off, cy + r - 2),
        fill=0,  # WHITE
    )


def _draw_cloud(draw, cx, cy, w, black, white):
    """Draw a cloud centred roughly at (cx, cy) with overall width w."""
    r = w // 4
    # white halo so the cloud reads over the sun/moon
    draw.ellipse((cx - w // 2 - 2, cy - r - 2, cx + w // 2 + 2, cy + r + 6), fill=white)
    draw.ellipse((cx - w // 2, cy - r, cx - w // 6, cy + r), fill=black)
    draw.ellipse((cx - w // 4, cy - r - 6, cx + w // 4, cy + r), fill=black)
    draw.ellipse((cx + w // 6, cy - r, cx + w // 2, cy + r), fill=black)
    draw.rectangle((cx - w // 2, cy, cx + w // 2, cy + r), fill=black)


def draw_icon(draw, region, category, is_day, black, white, accent):
    """
    Draw a weather icon inside `region` = (x0, y0, x1, y1).
    accent is the board's red/yellow index (2) or falls back to black.
    """
    x0, y0, x1, y1 = region
    cx = (x0 + x1) // 2
    cy = (y0 + y1) // 2
    box = min(x1 - x0, y1 - y0)
    r = max(8, box // 4)

    body = accent if is_day else black  # sun uses accent, moon uses black

    def base():
        if is_day:
            _draw_sun(draw, cx, cy - 4, r, body)
        else:
            _draw_moon(draw, cx, cy - 4, r, black)

    if category == "clear":
        base()
    elif category in ("partly",):
        base()
        _draw_cloud(draw, cx + 2, cy + 8, box // 2, black, white)
    elif category == "cloudy":
        _draw_cloud(draw, cx, cy, int(box * 0.7), black, white)
    elif category == "fog":
        _draw_cloud(draw, cx, cy - 4, int(box * 0.7), black, white)
        for i in range(3):
            yy = cy + 8 + i * 6
            draw.line((x0 + 6, yy, x1 - 6, yy), fill=black, width=2)
    elif category == "rain":
        _draw_cloud(draw, cx, cy - 6, int(box * 0.7), black, white)
        for i in range(3):
            xx = cx - 12 + i * 12
            draw.line((xx, cy + 10, xx - 4, cy + 20), fill=accent, width=2)
    elif category == "snow":
        _draw_cloud(draw, cx, cy - 6, int(box * 0.7), black, white)
        for i in range(3):
            xx = cx - 12 + i * 12
            draw.text((xx - 3, cy + 8), "*", fill=black)
            draw.ellipse((xx - 2, cy + 14, xx + 2, cy + 18), fill=black)
    elif category == "storm":
        _draw_cloud(draw, cx, cy - 6, int(box * 0.7), black, white)
        draw.line((cx, cy + 8, cx - 6, cy + 16), fill=accent, width=2)
        draw.line((cx - 6, cy + 16, cx + 2, cy + 16), fill=accent, width=2)
        draw.line((cx + 2, cy + 16, cx - 4, cy + 24), fill=accent, width=2)
    else:
        base()


# ----------------------------------------------------------------------------
# Rendering
# ----------------------------------------------------------------------------

def render(content):
    from PIL import Image, ImageDraw, ImageFont

    try:
        from inky.auto import auto
        inky = auto(ask_user=False, verbose=False)
    except Exception:
        from inky import InkyPHAT
        inky = InkyPHAT(INKY_COLOUR)

    width, height = inky.resolution
    WHITE = inky.WHITE
    BLACK = inky.BLACK
    # Accent colour = red/yellow on colour boards (index 2); fall back to black.
    ACCENT = getattr(inky, "RED", None)
    if ACCENT is None:
        ACCENT = getattr(inky, "YELLOW", BLACK)

    img = Image.new("P", (width, height), WHITE)
    draw = ImageDraw.Draw(img)

    # ---- Fonts -------------------------------------------------------------
    def load_font(size, bold=True):
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
        for path in candidates:
            if Path(path).exists():
                return ImageFont.truetype(path, size)
        try:
            from font_fredoka_one import FredokaOne
            return ImageFont.truetype(FredokaOne, size)
        except Exception:
            return ImageFont.load_default()

    # Smaller fonts than before so three lines fit the left 2/3 comfortably.
    font = load_font(16)

    # ---- Columns -----------------------------------------------------------
    text_w = int(width * TEXT_FRACTION)
    icon_region = (text_w, 0, width, height)

    def text_height(s):
        bbox = draw.textbbox((0, 0), s, font=font)
        return bbox[3] - bbox[1]

    lines = content["lines"]
    margin = 3
    usable = height - 2 * margin
    slot = usable / len(lines)
    for i, line in enumerate(lines):
        h = text_height(line)
        y = int(margin + i * slot + (slot - h) / 2) - 2
        draw.text((5, y), line, BLACK, font=font)

    # Thin divider between text and icon columns.
    draw.line((text_w - 2, 6, text_w - 2, height - 6), fill=BLACK, width=1)

    # ---- Icon --------------------------------------------------------------
    draw_icon(
        draw,
        (icon_region[0] + 4, icon_region[1] + 4,
         icon_region[2] - 4, icon_region[3] - 4),
        content["icon"],
        content["is_day"],
        BLACK, WHITE, ACCENT,
    )

    inky.set_image(img)
    inky.set_border(WHITE)
    inky.show()


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def in_quiet_window(hour):
    return hour >= QUIET_START_HOUR or hour < QUIET_END_HOUR


def main():
    hour = datetime.now().hour
    if in_quiet_window(hour):
        log.info("Within overnight quiet window (%02d:00). Skipping update.", hour)
        return 0

    content = build_content()
    log.info("Rendering: %s | icon=%s day=%s",
             " / ".join(content["lines"]), content["icon"], content["is_day"])

    try:
        render(content)
    except Exception as e:
        log.error("Failed to render to display: %s", e)
        return 1

    log.info("Display updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
