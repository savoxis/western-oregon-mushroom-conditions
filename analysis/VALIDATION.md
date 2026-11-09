# Score validation against public finds and sensors (updated 2026-11-09)

**Question:** do high scores line up with days when people actually report the mushroom, once we account for how many people were out looking?

**Data:** 1,621 public finds (GBIF: iNaturalist research grade, Mushroom Observer and a few small datasets; Creative Commons records with a public location good to 2 km). Effort background: 40,937 other mushroom-type (class Agaricomycetes) records in Oregon, 2016-2025, same filters, target genera removed. Scores: the site's daily in-season scores, 2016-2025 (complete ERA5 years). Finds are assigned to the nearest zone within 40 km (sensitivity at 20 and 70 km). Unique zone-days are counted.

**Tests:** A = share of find-days on 60+ days vs share of all in-season days on 60+. B = among days when other mushrooms were reported nearby, how much likelier the target is reported on 60+ days than <40 days (Mantel-Haenszel risk ratio across zones, 95% interval by resampling zone-years). C = year-swap: score on the find day vs the same calendar window in the other years (50 = adds nothing beyond the calendar).

## Result v3 (complete history: all 62 zone series have 2016-2025; 3 new zones included)

| Species | Find-days (zones) | A: 60+ share vs baseline | B: risk ratio, effort >= 1 (95%) | B at 20 km / 70 km | C: year-swap (95%) |
|---|---|---|---|---|---|
| Chanterelle | 377 (24) | 1.34x | 1.15 (0.89 to 1.59) | 1.39 (0.95 to 2.32) / 1.28 (1.01 to 1.76) | 52.3 (47.9 to 56.6) |
| Natural morel | 83 (16) | 1.08x | 1.26 (0.51 to 4.77) | 1.42 (0.17 to 2.62) / 1.42 (0.74 to 3.15) | 40.4 (32.5 to 49.2) |
| Spring king | 54 (8) | 1.38x | 1.25 (0.39 to 4.60) | n/a / 1.81 (0.59 to 6.89) | 49.4 (37.5 to 61.7) |
| Fall king | 208 (9) | 1.63x | 3.22 (2.21 to 5.78) | 2.10 (1.17 to 6.34) / 3.23 (2.19 to 5.18) | 51.6 (46.3 to 56.5) |

Reading: fall king is the one clear match (about 2 to 3 times; weaker with 3+ other mushrooms reported: 1.9, 1.27 to 3.5, and 1.1 at 20 km). Chanterelle is weak (1.15 to 1.4, mostly within chance; about 1.0 with 3+ other mushrooms reported). Spring king and natural morel: no match shown. No species shows a year-specific weather signal (year-swap about 50; morel 40, interval up to 49).

Earlier versions: v1 (11-year zones only, 74 chanterelle find-days) and v2 (west zones with 2020-2025) differed; v3 supersedes them.

**Correction to the first run (2026-11-08):** the first version used only zones with 11 years of history (7 chanterelle zones, 74 find-days) and reported chanterelle 2.1x (1.15 to 5.95). The larger sample does not support that; the public sources page was corrected the same day it was found.

## Natural morel diagnosis

Elevations of the 341 public morel finds (USGS 10 m elevation model) vs the skill's natural-morel elevation bands (March 500-2,500 ft, April 1,000-3,500, May 3,000-4,800, June 4,200-6,000, July 5,500-6,500):
- 196 of 341 (57%) are below 1,000 ft (median March-April elevation about 280 ft); 189 of those are on private/unmapped (136) or county, city, research land (53): parks, yards, orchards.
- Only 28% of finds fall inside the model's band for their month (March 12%, April 16%, May 42%, June 75%); on national forest and BLM land 65%.
- With complete history, in-band finds (39 find-days, 10 zones) still show nothing decisive (risk ratio 1.4, 0.3 to 5.5; east side only 0.7, 0.2 to 4.3).
- Valley morels vs measured soil temperature (AgriMet Aurora, 8 in; 78 find-days, 8 years): the 7-day mean soil temperature on find days had median 53.5 F (p10 49.8, p90 59.0), but the date soil first reaches a threshold predicts the first-quartile find date poorly year to year (best threshold 52 F, r 0.62, spread about 10 days, 8 years). Not enough to build lowland rules.
- Burn morels: 16 of 145 finds at or above 1,000 ft (11%; 5% of all) were inside a fire perimeter from the prior 2 years, mostly 2021-22 after the 2020 fires. Real but small; burn severity data was not added.

## Forest structure (LANDFIRE 2024) at finds vs surrounding land (finds near a zone)

| Species | In late-development closed forest | In stands 30 m+ | (surrounding land, same measures) |
|---|---|---|---|
| Chanterelle | 36% | 24% | 22% / 14% |
| Fall king | 27% | 21% | 21% / 13% |
| Spring king | 20% | 11% | 11% / 5% |
| Morel | 15% (only 53% in forest at all) | 10% | 16% / 10% (75% forest) |

Chanterelle and king finds lean toward older, taller forest (about 1.3 to 1.7 times); finds come from trails and roads, so it is a hint. Shown on the page as "Forest around this zone" with a strong/average/weak fit (tertiles of late-development + tall share across 32 zones).

## Soil temperature: model vs measured (AgriMet, 2022-2025, daily means; model minus station, deg F)

| Station | Depth | Bias | Correlation | Notes |
|---|---|---|---|---|
| Corvallis (valley) | 4 in vs 0-7 cm | -3.2 (Apr -6.2, May -5.5) | 0.975 | |
| Aurora (valley) | 8 in vs 7-28 cm | -5.5 (May -7.4) | 0.988 | |
| Medford | 4 in | -2.7 | 0.96 | |
| Klamath Falls | 4 in | -4.0 | 0.984 | |
| Brookings (coast) | 6 in | -2.1 | 0.944 | |
| Bandon (coast) | 4 in | +7.5 | 0.943 | model too warm |
| Beatty (east) | 4 in | +2.3 (June +6.0) | 0.974 | |

The model tracks the shape of soil temperature very well (r 0.94 to 0.99) but runs 2 to 7 F cold in the valleys and interior in spring and warm on the coast. Sensors sit in open, often irrigated fields, so forest soil is probably cooler than the station readings; the gap is therefore not a clean error estimate for forest. The skill's temperature windows (for example 48 to 56 F for morels) assume measured-like values, so a few degrees of bias can shift scores. Not adjusted: the skill is untouched. Forest-opening sensors (RAWS, SNOTEL) would be the right check.

## Soil temperature vs forest-clearing sensors (NRCS SNOTEL, 2022-2025; model minus sensor, deg F)

15 SNOTEL stations in western Oregon and the Cascades (420 to 6,020 ft) with soil sensors at 4 and 8 inches, compared with the ERA5-Land layers the history uses (0-7 cm and 7-28 cm). Snow-covered days (sensor under 36 F) excluded. SNOTEL values are midnight readings; model values are daily means.

- Pooled bias: -3.2 F (0-7 cm vs 4 in) below 4,000 ft, -3.3 F at 4,000 to 5,600 ft, -3.1 F above; deeper layer -2.4, -3.1, -4.5. Correlation 0.84 to 0.92 pooled (0.80 to 0.97 by station).
- By month (pooled): April -5.9, May -3.2, June -2.5, July +0.5, August -0.5, September -2.1, October -4.0, November -5.3. So the history runs coldest in the shoulder seasons that matter for morels and fall mushrooms, and is about right in midsummer.
- By station the bias runs from -8.9 (Holland Meadows, a wet meadow site) and -7.5 (Annie Springs) to +5.3 (Fifteenmile): local site effects such as cold-air pockets are large. Miller Woods (420 ft, the only low-elevation forest station) -2.1.
- The live forecast model (soil_temperature_6cm and 18cm, which the live and forecast-day scores use) vs the same sensors, Aug 8 to Nov 8 2026: pooled -1.4 F (6 cm vs 4 in) and -1.5 F (18 cm vs 8 in); better than the ERA5 history for those months.
- Meaning: the skill's temperature windows (for example morel 48 to 56 F) are being applied to history that is typically 3 to 6 F cold in April-May and October-November, so spring scores probably read late or low and fall scores probably read late in the history. Not adjusted: the skill is untouched. Open question: whether a seasonal correction applied before scoring would make scores line up better with finds. That can be tested by re-scoring history on a test copy and re-running `analysis/val2.py`.

## Test: seasonal soil-temperature correction (2026-11-09)

Pre-specified test: add the measured pooled SNOTEL bias by month to the history's soil temperature before the unchanged skill scorer runs (full: Mar +5, Apr +6, May +3.5, Jun +2.5, Jul and Aug 0, Sep +2, Oct +4, Nov +5; half: the same times 0.5), re-score 2016-2025 for all zones on an isolated copy (`analysis/run_offset_test.py`; control run reproduced production in all 226,920 scored cells), and re-run the finds validation. Pre-set bar for "worth adopting": year-swap above 55 with the interval excluding 50 for at least two mushrooms, or a clearly higher effort-controlled risk ratio with separated intervals.

- The correction barely moves scores: mean +1.0 points, share of days at 60+ from 46.9% to 48.5%. The scorer's other terms (moisture, trigger timing, season window) dominate.
- Year-swap: no mushroom reaches the bar (chanterelle 52.3 to 52.5; fall king 51.6 to 51.3; spring king 49.4 to 51.4; morel 40.4 to 46.0 with interval 37.6 to 54.4).
- Risk ratios (40 km, effort >= 1): chanterelle 1.15 to 1.10 (no change); fall king 3.2 to 4.6 (full) or 5.2 (half), but the share of finds on 60+ days relative to baseline slips (1.63 to 1.54), so the rise comes from fewer low-score days, not clearly better discrimination; morel 1.26 to 1.01 (full) or 1.79 (half), intervals all include 1; spring king undefined at 40 km, 1.8 to 5.4 (1.48 to 8.68) at 70 km. Half the correction does about as well as the full one.
- Verdict: not adopted. Only spring king and morel lean the right way and neither clears the bar with samples of 54 and 83 find-days. Revisit as finds accumulate; choosing only the spring months now would be tuning to this data.

## Caveats
Only Creative Commons records reach GBIF (about 60% of iNaturalist); effort is measured by other mushrooms, which also respond to rain (conservative); nearest-zone assignment is coarse; fall king rests on 9 zones; morel and spring king samples are small (re-run `analysis/val2.py` against `/opt/shrooms/data/series.json` as finds accumulate).

Files: `analysis/` (val2_fetch.py effort data, val2.py tests, val2m.py morel splits, hab_fetch.py and hab_build.py forest structure, valley_morel.py, am_validate.py).

## Live rain input vs gauges (2026-11-09)

Live scores (and the forecast-day bars) take the last 31 days of rain from the forecast service's "past days", while the 10-year history uses ERA5. Against AgriMet rain gauges for Oct 20-31 2026: Bandon gauge 1.55 in, forecast past days 0.06, ERA5 1.08; Brookings 1.58 / 2.34 / 1.37; Corvallis 0.75 / 0.46 / 1.48; Medford 0.52 / 0.40 / 0.75 (Aurora gauge data invalid). Mean absolute miss: forecast past days 0.67 in, ERA5 0.41 in (4 gauges, one 12-day window). Effect: on Nov 8 several coastal and foothill chanterelle scores read 42 live versus 93 to 100 in the history six days earlier, mainly because the forecast service saw almost none of the Oct 25-27 coastal rain. Changed 2026-11-09 (owner's decision): live and forecast-day scores now take past-day rain from ERA5 in the database wherever it exists (about 5 days behind) and the forecast service only for the newest days, plus the fall season-opener rain since Aug 1 from the database. After the switch, live scores on Nov 8 matched the history's last day within 15 points for 22 of 33 zone-mushroom pairs (14 of 33 before), for example Reedsport chanterelle 100 (was 42; history 100). The site's live scores can now differ from what the unmodified skill (and the daily alert script, which calls the skill directly) report for the same zone.

## Review of 2026-11-09: species against public knowledge, antecedent weather, data gaps

**Timing, model prime days vs public reports (10th / 50th / 90th percentile, 2016-2025; reports now include blurred-location records):**

| Species | Model prime days | Public reports | Published guidance |
|---|---|---|---|
| Natural morel | Apr 1 / May 11 / Jun 17 | Apr 3 / Apr 28 / May 30 | mid-April to early June, moving uphill with snowmelt; soil about 50 to 60 F at 2 to 4 in |
| Spring king | May 13 / Jun 9 / Jul 8 | May 17 / Jun 7 / Jun 30 | late spring after snowmelt, mid elevations |
| Chanterelle | Sep 27 / Oct 29 / Dec 2 | Aug 17 / Oct 17 / Nov 28 | mid-summer at higher elevations to first frost, usually through November; triggered by fall rains |
| Fall king | Sep 25 / Oct 30 / Dec 12 | Sep 2 / Oct 16 / Nov 12 | fall, September to November, coastal pine and spruce |

The live tracking of this table is on the Stats tab (c/metrics.json, rebuilt with every build).

**Antecedent weather (does the score look back far enough?).** The scorer already looks back: 7-day soil temperature, 7/14/30-day rain, days since the last rain event, days since snowmelt, days since the fall season opener (Aug 1 onward), frost in the last 3 and 5 nights, and a 14-day dry-gap penalty. `analysis/antecedent_check.py` compared longer windows on effort days (top vs bottom third within each zone): for chanterelles and fall kings, rain over the last 7 to 14 days goes with more reports (1.2 to 1.4x) while 60 to 90-day and since-August rain go with fewer (0.5 to 0.7x, because they mark the late season). The clearest antecedent signal was frost: no chanterelle reports on in-season days with a frost night in the previous 14 days (0 of 63 such days vs 9 of 150 frost-free days).

**Model changes tested (analysis/run_variant_test.py; control reproduced production exactly):**
- Adopted: chanterelle season opener at 1.0 in of rain in 7 days (was 1.5), a 14-day frost memory (any 28 F night halves the score) and the short-term frost penalty now applying to 1 or more nights (it fired only at exactly 1). Chanterelle effort-controlled ratio 1.15 to 1.44 (40 km, 0.89-1.59 to 1.09-2.01); with blurred records 1.33 (1.07-1.80) and 1.48 at 70 km; year-swap 52 to 54 (interval 50.8 to 57.6, the first sign of a year-specific signal). Fall-king and other species unchanged.
- Rejected: fall king coastal season ending in November (timing matched reports better, P90 Dec 13 to Nov 20, but the ratio fell from 3.2 to 2.7) and an August start for inland chanterelles (the ratio rose, but 66 of 67 August find-days still scored below 60, so the gain was mechanical: the score cannot see summer flushes, which need a different trigger). Both remain visible gaps in the timing table.

**Data gaps closed:**
- Blurred-location records: about half of all public mushroom records have locations blurred by their observers (2 to 30 km). They were dropped; they are now kept for zone counts, timing, tracking and validation (never mapped or land-tagged): 1,094 added to 1,621 mappable records.
- Measured soil temperature and rain: the nearest SNOTEL or AgriMet station (within 45 km and 2,000 ft) is now read nightly and shown in the zone panel for context (15 of 32 zones).
- Fixed along the way: the Stats card did not draw when opening the Stats tab from the map; the AI brief was dated in UTC.

**Free services checked and not added:** iNaturalist API directly (blocked for the server's IP; GBIF republishes research-grade records 1 to 2 weeks later), Mushroom Observer API (already in GBIF), NWS forecast API (no soil data; Open-Meteo covers it), NRCS SCAN (no west-side Oregon stations), NASA SMAP soil moisture (9 km cells), PRISM (overlaps ERA5), MTBS burn severity (11% of upland morel finds were in recent burns), USFS closure orders (no machine-readable feed).
