# Inky pHAT Weather Dashboard

A tiny weather dashboard for a **Pimoroni Inky pHAT 2.13" (212×104)** driven by a
**Raspberry Pi Zero W** running **Raspberry Pi OS "Trixie" (headless)**.

It shows three lines and refreshes **every hour at :15**, pausing overnight
**between 11:00 PM and 5:00 AM**:

1. Date and time
2. Current weather conditions for **Mt. Airy, Maryland**
3. Air Quality Index (US AQI)

Weather and air-quality data come from the free [Open-Meteo](https://open-meteo.com)
APIs — **no API key required**.

---

## Hardware / OS assumptions

- Raspberry Pi Zero W (v1.1) — ARMv6, 32-bit
- Pimoroni Inky pHAT 2.13" (212×104)
- Raspberry Pi OS "Trixie", **headless (Lite)**, with SSH enabled

> **Why the install script uses `apt` for numpy/Pillow:** On Trixie, `pip`
> tries to compile `numpy` from source, which fails or takes forever on a Pi
> Zero. Installing the prebuilt system packages first and creating the venv with
> `--system-site-packages` avoids that entirely.

---

## 1. Connect to the Pi over SSH

From your computer (replace the hostname/user if you changed them when flashing):

```bash
ssh pi@raspberrypi.local
```

If `.local` name resolution doesn't work, use the Pi's IP address instead
(find it in your router, or run `hostname -I` on the Pi if you have console access).

---

## 2. Clone this repo and run the installer

```bash
git clone https://github.com/RFNajera/inky-weather-dashboard.git
cd inky-weather-dashboard
chmod +x install.sh
./install.sh
```

The installer will:

- install system dependencies via `apt`
- enable **SPI** and **I2C**
- add `dtoverlay=spi0-0cs` to `/boot/firmware/config.txt`
- create a virtual environment at `~/.virtualenvs/inky`
- install the Python requirements
- install and enable a **systemd timer** that runs the update on schedule

If SPI/I2C were just enabled for the first time, reboot once:

```bash
sudo reboot
```

---

## 3. Test it

Trigger a one-off update immediately (ignores the schedule, but still respects
the overnight quiet window):

```bash
sudo systemctl start inky-dashboard.service
```

Watch the logs:

```bash
journalctl -u inky-dashboard.service -n 50 --no-pager
```

Confirm the timer is scheduled:

```bash
systemctl list-timers inky-dashboard.timer
```

---

## How the schedule works

- The **systemd timer** (`inky-dashboard.timer`) fires at **:15 past every hour
  from 05:00 through 22:00**, so nothing runs overnight.
- As a safety net, `dashboard.py` also checks the clock and **skips drawing**
  if it's ever run between 23:00 and 05:00.

To change the schedule, edit `OnCalendar=` in
`systemd/inky-dashboard.timer`, copy it to `/etc/systemd/system/`, then:

```bash
sudo systemctl daemon-reload
sudo systemctl restart inky-dashboard.timer
```

---

## Configuration

Edit the constants near the top of `dashboard.py`:

| Setting | Purpose |
|---|---|
| `LATITUDE` / `LONGITUDE` | Location (defaults to Mt. Airy, MD) |
| `TIMEZONE` | Local timezone for timestamps/data |
| `INKY_COLOUR` | `"black"`, `"red"`, or `"yellow"` — match your board |
| `QUIET_START_HOUR` / `QUIET_END_HOUR` | Overnight pause window |

After editing, apply changes with a test run:

```bash
sudo systemctl start inky-dashboard.service
```

---

## Uninstall

```bash
sudo systemctl disable --now inky-dashboard.timer
sudo rm /etc/systemd/system/inky-dashboard.service /etc/systemd/system/inky-dashboard.timer
sudo systemctl daemon-reload
```

---

## Troubleshooting

- **`Failed to detect an Inky board`** — auto-detection reads the board's EEPROM
  over I2C. Make sure I2C is enabled and rebooted. The script falls back to an
  explicit `InkyPHAT(INKY_COLOUR)`, so set `INKY_COLOUR` correctly.
- **`Woah there, some pins we need are in use!`** — the `dtoverlay=spi0-0cs`
  line wasn't applied; confirm it's in `/boot/firmware/config.txt` and reboot.
- **`externally-managed-environment`** — you're using system `pip` instead of
  the venv. Use `~/.virtualenvs/inky/bin/pip`.
- **numpy tries to build from source** — install `python3-numpy` via `apt`
  (the installer does this) and ensure the venv was created with
  `--system-site-packages`.
