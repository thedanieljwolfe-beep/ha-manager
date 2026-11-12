# HA Manager

A Home Assistant custom integration that gives your smart home an MOT.

It adds an **HA Manager** page to the sidebar that tells you, in plain English,
what is broken, what is left over, and what to fix first.

## What it does today (Phase 1, read-only)

Phase 1 only *looks*. It never renames, moves or deletes anything.

- **Health score.** One number out of 100, with every problem sorted into
  Critical, Warning or Tidy-up.
- **Broken reference finder.** Automations, scripts, scenes, groups and
  dashboards that point at entities, devices or rooms that no longer exist.
- **Leftovers.** Entities left behind by integrations you have removed,
  devices with no room, and things that have gone offline.
- **Life-safety tier.** Smoke, carbon monoxide, gas and leak sensors get their
  own page with battery level, last contact and a test log.
- **Flapping and zombie automations.** Automations firing far too often, and
  automations and scripts that have not run in 90 days.
- **Blast radius.** Pick any entity, device or room and see everything that
  uses it *before* you rename or delete it.
- **Works with your other tools.** Anything in Home Assistant's own Repairs
  list is pulled in, including warnings raised by
  [Spook](https://spook.boo). If [Watchman](https://github.com/dummylabs/thewatchman)
  is installed its counts are shown too.

It also creates `sensor.ha_manager_health_score` so you can put the score on a
dashboard or use it in an automation.

## Install

### With HACS (easiest)

1. In HACS, open the three-dot menu and choose **Custom repositories**.
2. Add this repository's URL and pick **Integration** as the type.
3. Find **HA Manager** in HACS and download it.
4. Restart Home Assistant.
5. Go to **Settings > Devices & services > Add integration** and search for
   **HA Manager**.

### By hand

1. Copy the `custom_components/ha_manager` folder into the
   `custom_components` folder of your Home Assistant config.
2. Restart Home Assistant.
3. Add the **HA Manager** integration as in step 5 above.

**HA Manager** then appears in the sidebar for admin users.

## How the score works

Start at 100 and take points off:

| Level    | Points each | Most it can cost |
| -------- | ----------- | ---------------- |
| Critical | 10          | 60               |
| Warning  | 3           | 30               |
| Tidy-up  | 0.5         | 10               |

Anything you mark as "Ignore" stops counting. Warnings that come from Spook or
Watchman are shown for cross-checking but are not counted twice.

## A note on the life-safety page

This page is a reminder and a log. It is **not** a substitute for pressing the
test button on your alarms, and it cannot tell you that an alarm will sound.
UK fire and rescue services recommend testing smoke alarms at least monthly.

## Roadmap

- **Phase 2:** change log with undo, drag-and-drop room mover, naming checker.
- **Phase 3:** plain-English explainer, battery forecaster, weekly report,
  live floor plan.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
pytest
```
