# Home Assistant agent handoff — Mustart MT EVSE

A new device is on the network: a **Mustart MT portable EV charger** that now reports to Home Assistant
via an **ESPHome** node soldered inside it. This note tells a home-automation agent what it is, what the
entities mean, and — importantly — **what not to do with it.**

## The one rule: it is READ-ONLY. Do not try to control charging.

This integration **monitors** the charger. It exposes **no charge-control entity**, and there is no safe
way to add one here: the ESP firmware only ever sends the charger's read-only `cmd 0x01` ("report values")
frame, and the MCU patch only answers reads. The charger's own buttons set the current (12 A / 16 A);
charging start/stop is governed by the car + the J1772 pilot, not by this integration.

**Never** attempt to send other commands, write config, or "set the amps" through this device. Treat it
like a power meter, not a switch. If you want to *gate* charging, do it upstream (e.g. the smart plug
below), never by trying to command the charger.

## Connection

- **ESPHome device:** `mustart-evse` (ESP8266 / ESP-12F), native HA API, local push (no cloud).
- **Current IP:** `192.168.x.x` (DHCP — prefer the HA device/entity registry over the raw IP).
- **Upstream smart plug** (separate ESPHome device, controllable): `mustart-evse-plug` at
  `192.168.x.x`, switch entity "Mustart EVSE Plug". This is the real power cutoff if you ever need to
  hard power-cycle the charger (e.g. the telemetry link goes stale). **Do not** cut it mid-charge unless
  intended — the car may not resume on its own.

## Entities and what they mean

| Entity | Meaning | Normal / notes |
|---|---|---|
| **Voltage** | Mains voltage at the charger | ~120 V or ~240 V depending on the outlet |
| **Current** | Measured charge current | 0 A with no car; rises during a charge |
| **Power** | volts × amps | 0 kW idle; up to ~3.8 kW at 16 A / 240 V |
| **Energy** | Integrated session energy (kWh) | accumulates across a charge (total_increasing) |
| **Pilot Voltage** | J1772 control-pilot level | ~12 V not-connected · ~9 V connected · ~6 V charging |
| **Temperature** | Internal temp | ~room temp idle; rises under load |
| **State** | Derived J1772 state text | "Not connected" / "Connected" / "Charging" |
| **Link OK** (binary) | Telemetry link health | **ON** = fresh data within ~30 s. If it flips OFF, see below. |
| **Good/Bad Frames, RX Bytes** | Link diagnostics | Good climbs, Bad should stay 0 |

## Behavioral quirks (so automations don't misfire)

- **Boots at 12 A.** A safe default; the owner taps the unit's button for 16 A. So "offered current" may
  be 12 A even on a 240 V circuit until bumped — this is intentional, not a fault.
- **Charging schedule:** the car is set to **charge at midnight on weekdays**, so expect Current/Power/
  Energy to sit at 0 most of the day and spike overnight. Don't alert on "no charging" during the day.
- **Poll rate:** the ESP polls every ~3 s (diagnostic). May be relaxed to ~15 s later; don't assume a
  fixed cadence — key off entity `last_changed`/freshness, and off **Link OK** for health.
- **Link OK = OFF** usually means the ESP rebooted/lost WiFi or (rarely) the charger's UART stalled.
  First response: wait a minute; if still off, a power-cycle of the upstream smart plug clears it.

## Good automation ideas

- **Energy accounting:** feed `Energy` into the HA Energy dashboard as an individual device.
- **Charge-session notifications:** on `State` → "Charging", announce start; on return to "Connected",
  summarize kWh added this session.
- **Health alert:** if `Link OK` stays OFF > ~10 min, notify (and optionally power-cycle the plug once).
- **Over-temp watch:** alert if `Temperature` climbs unusually high during a charge.

## Maintenance notes (for the human, surfaced by the agent if asked)

- ESP firmware updates: **OTA via ESPHome** (config `esphome/mustart-evse-usart1.yaml`).
- MCU firmware: patched via ST-Link; SWD is kept available at runtime. Do not reflash without the
  backups and the procedure in the project repo.
- Do not add or send write/control commands to the charger over this link under any circumstances.
