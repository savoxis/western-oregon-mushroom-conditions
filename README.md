# Western Oregon Mushroom Conditions

Source for [shrooms.strong.beer](https://shrooms.strong.beer): a free, static map of how good the weather is for morels, golden chanterelles and king boletes across western Oregon, with ten years of modeled history, a week-ahead outlook, public past finds, land ownership and an honest check of the scores against real reports. A product of Yeyland Wutani LLC, built with the assistance of Claude.

Scores estimate fruiting conditions, not what is in a basket. Never eat a wild mushroom you have not positively identified yourself.

## How it works

```
                 nightly + hourly cron (VPS)
 Open-Meteo  ─┐
 GBIF finds  ─┤                      ┌─> site/data/*.json ──> Caddy (static, read-only) ──> visitors
 SNOTEL/WFIGS ─┼─> builder/shrooms_build.py ─┤
 PAD-US, ERA5 ─┘   (uses scout/ scorer)      └─> SQLite history (weather, snapshots, finds)

 Unraid at home: pulls the built site every ~10 min and takes over DNS if the VPS is down (deploy/failover).
```

* **Scorer** (`scout/`): the fruiting-conditions model. `scout/references/species_registry.json` holds every threshold (soil temperature windows, moisture ramps, triggers, elevation bands); `scout/scripts/score.py` applies them. `weather.py`, `snotel.py` and `fires.py` fetch inputs. Originally a standalone assistant skill; this repository is now its home.
* **Builder** (`builder/shrooms_build.py`): scores every zone and heat-map point for 2016 to now from ERA5-Land history, scores today and the next 6 days from the forecast (past-day rain from ERA5 wherever it exists), exports the compact JSON the page reads, and keeps a SQLite history. Modes: `auto` (hourly: nightly build once a day, otherwise history backfill or past-find tagging), `nightly`, `live` (rescore today plus a fresh brief), `fill`, `rebuild`, `zones`, `sightings`.
* **Past finds** (`builder/shrooms_sightings.py`): public GBIF records (iNaturalist research grade, Mushroom Observer and others) tagged with the land manager from USGS PAD-US.
* **Brief** (`builder/shrooms_brief.py`): an optional nightly two-paragraph summary written by Gemini from the public numbers only, with no edibility or identification advice.
* **Open-Meteo key** (`builder/om_key.py`, `builder/omshim/`): routes forecast calls to the commercial endpoint when a key is configured, with a free-host fallback; the key never reaches logs or the site.
* **Site** (`site/`): static HTML, CSS and JavaScript (Leaflet, D3). All page text is built with `textContent`; the server sends a strict Content-Security-Policy.
* **Analysis** (`analysis/`): the validation work behind the Stats tab's "Scores against real reports" card and the sources page: effort-controlled comparison with public finds, forest structure (LANDFIRE), soil-temperature sensors (SNOTEL, AgriMet) and a soil-correction experiment. Results and caveats: [analysis/VALIDATION.md](analysis/VALIDATION.md).

## Layout on the server

| Repository | Server path | Notes |
|---|---|---|
| `scout/` | `/opt/mushroom-scout/` | the builder imports `scripts/score.py` and `scripts/snotel.py` from here (`SHROOMS_SKILL`) |
| `builder/` | `/opt/shrooms/` | runs as an unprivileged user from cron; writes `data/`, `cache/` and `site/data/` |
| `site/` | `/opt/shrooms/site/` | served read-only; `site/data/` is generated except the three static analysis files kept here |
| `deploy/` | see [deploy/README.md](deploy/README.md) | cron, web server, failover and config templates |

Python 3.10+, standard library only (no pip installs). The page has no build step.

## Tests

```bash
cd /opt/shrooms && python3 -B -W ignore tests/test_shrooms.py           # unit checks, no network
cd /opt/shrooms && python3 -B -W ignore tests/test_shrooms.py --live    # adds: forecast day 0 equals the live score
```

## Data sources and licenses

Weather: [Open-Meteo](https://open-meteo.com/) (ERA5-Land reanalysis from Copernicus/ECMWF and forecast models, CC BY 4.0). Snow: NRCS SNOTEL. Fires: NIFC WFIGS. Past finds: [GBIF](https://www.gbif.org/) (CC0, CC BY, CC BY-NC records). Land: USGS PAD-US and BLM surface management tiles. Forest structure: LANDFIRE 2024. Soil sensors: NRCS SNOTEL and Bureau of Reclamation AgriMet. Base map: USGS The National Map. Vendored libraries: Leaflet (BSD-2-Clause) and D3 (ISC). The full credits page is `site/sources.html`.

No license has been chosen for this repository's own code yet; until one is added, all rights are reserved by the owner.
