#!/usr/bin/env python3
"""
Inky pHAT 2.13" weather dashboard for Mt. Airy, Maryland.

Renders three lines on the e-ink display:
  1. Date and time
  2. Current weather conditions
  3. Air Quality Index (US AQI)

Data comes from the Open-Meteo APIs (no API key required).

Designed to be run once per invocation (e.g. from a systemd timer).
The overnight quiet window (23:00-05:00) is enforced here as a safety net
so nothing is drawn if the script is ever triggered during that period.
"""

import sys
import time
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

# Inky pHAT colour: "black", "red", or "yellow". Match your board.
INKY_COLOUR = "black"

# Overnight quiet window (24h clock). During these hours nothing is drawn.
QUIET_START_HOUR = 23  # 11 PM
QUIET_END_HOUR = 5     # 5 AM

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
# WMO weather interpretation codes -> short human labels
# ----------------------------------------------------------------------------

WMO_CODES = {
    0: "Clear",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Rime fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Dense drizzle",
    56: "Frz drizzle",
    57: "Frz drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Frz rain",
    67: "Frz rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Light showers",
    81: "Showers",
    82: "Heavy showers",
    85: "Snow showers",
    86: "Snow showers",
    95: "Thunderstorm",
    96: "Storm + hail",
    99: "Storm + hail",
}


def wmo_label(code):
    return WMO_CODES.get(code, f"Code {code}")


def aqi_label(aqi):
    """US AQI category from numeric value."""
    if aqi is None:
        return "n/a"
    if aqi <= 50:
        return "Good"
    if aqi <= 100:
        return "Moderate"
    if aqi <= 150:
        return "Unhealthy(SG)"
    if aqi <= 200:
        return "Unhealthy"
    if aqi <= 300:
        return "V.Unhealthy"
    return "Hazardous"


# ----------------------------------------------------------------------------
# Data fetching
# ----------------------------------------------------------------------------

def fetch_weather():
    """Return (temp_f, weather_code) or (None, None) on failure."""
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LATITUDE}&longitude={LONGITUDE}"
        "&current=temperature_2m,weather_code"
        "&temperature_unit=fahrenheit"
        f"&timezone={TIMEZONE}"
    )
    try:
        r = requests.get(url, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        cur = r.json().get("current", {})
        return cur.get("temperature_2m"), cur.get("weather_code")
    except Exception as e:
        log.warning("Weather fetch failed: %s", e)
        return None, None


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
# Rendering
# ----------------------------------------------------------------------------

def build_lines():
    now = datetime.now()
    date_line = now.strftime("%a %b %-d  %-I:%M %p")

    temp_f, code = fetch_weather()
    if temp_f is not None:
        weather_line = f"{wmo_label(code)}  {round(temp_f)}\u00b0F"
    else:
        weather_line = "Weather unavailable"

    aqi = fetch_aqi()
    if aqi is not None:
        aqi_line = f"AQI {aqi}  {aqi_label(aqi)}"
    else:
        aqi_line = "AQI unavailable"

    return date_line, weather_line, aqi_line


def render(date_line, weather_line, aqi_line):
    """Draw the three lines to the Inky pHAT."""
    from inky.auto import auto
    from PIL import Image, ImageDraw, ImageFont

    try:
        inky = auto(ask_user=False, verbose=False)
    except Exception:
        # Fall back to an explicit pHAT if auto-detect (EEPROM) fails.
        from inky import InkyPHAT
        inky = InkyPHAT(INKY_COLOUR)

    width, height = inky.resolution  # pHAT 2.13" = (212, 104)

    img = Image.new("P", (width, height), inky.WHITE)
    draw = ImageDraw.Draw(img)

    # Fonts: prefer bundled Fredoka One, fall back to DejaVu, then default.
    def load_font(size):
        try:
            from font_fredoka_one import FredokaOne
            return ImageFont.truetype(FredokaOne, size)
        except Exception:
            pass
        for path in (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ):
            if Path(path).exists():
                return ImageFont.truetype(path, size)
        return ImageFont.load_default()

    font = load_font(20)

    def text_height(s):
        bbox = draw.textbbox((0, 0), s, font=font)
        return bbox[3] - bbox[1]

    lines = [date_line, weather_line, aqi_line]
    # Distribute three lines evenly across the height.
    margin = 4
    usable = height - 2 * margin
    slot = usable / len(lines)
    for i, line in enumerate(lines):
        h = text_height(line)
        y = int(margin + i * slot + (slot - h) / 2) - 2
        draw.text((6, y), line, inky.BLACK, font=font)

    inky.set_image(img)
    inky.show()


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def in_quiet_window(hour):
    # Window wraps past midnight (23:00 -> 05:00).
    return hour >= QUIET_START_HOUR or hour < QUIET_END_HOUR


def main():
    hour = datetime.now().hour
    if in_quiet_window(hour):
        log.info("Within overnight quiet window (%02d:00). Skipping update.", hour)
        return 0

    date_line, weather_line, aqi_line = build_lines()
    log.info("Rendering: %s | %s | %s", date_line, weather_line, aqi_line)

    try:
        render(date_line, weather_line, aqi_line)
    except Exception as e:
        log.error("Failed to render to display: %s", e)
        return 1

    log.info("Display updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
