# Centrik for Home Assistant

Centrik for Home Assistant helps you keep track of active medications and repeat dates in your calendar.

## What You Get

- One calendar per active medication
- Upcoming repeat dates shown as calendar events
- A final “prescription renewal planning” event when supply is expected to run out
- Optional reminders in Home Assistant before:
  - repeat due dates
  - prescription runout dates

## Who This Supports

Right now this supports:

- **Unichem & Life Pharmacy** (Centrik pharmacy portal)

## Setup

1. Copy `custom_components/centrik` into your Home Assistant config folder.
2. Restart Home Assistant.
3. Go to **Settings -> Devices & Services -> Add Integration**.
4. Search for **Centrik**.
5. Enter your login details and reminder preferences.

## Reminder Settings

- Repeat reminder lead time: **0 to 14 days** (default **3**)
- Prescription reminder lead time: **0 to 14 days** (default **7**)

## Refresh Frequency

- Medication data is refreshed **daily**.

# Disclaimer

This project is community-made.

- We are **not affiliated with Centrik**.
- This integration is **not provided, reviewed, or supported by Centrik**.
