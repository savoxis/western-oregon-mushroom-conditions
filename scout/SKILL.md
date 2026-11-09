---
name: oregon-mushroom-scout
description: Location-aware wild mushroom foraging advisor for southern and central Oregon. Scores current fruiting-condition likelihood for morels (natural and burn), Pacific golden chanterelles, spring king boletes, and fall king boletes against live weather, snowmelt, and wildfire-perimeter data, then ranks nearby zones with reasons, elevation/aspect guidance, and permit rules. Use when the user asks what's fruiting nearby, where to forage in Oregon, whether it's morel/chanterelle/bolete season in an area, or gives an Oregon place name plus a mushroom-hunting question.
---

# Oregon Mushroom Scout

Example queries this skill handles:
- "What's fruiting near [location]?"
- "I'm in [place], what should I harvest?"
- "Is it [species] season in [area]?"
- "Heading to [zone] this weekend, anything good?"
- "Recommend foraging spots in [Oregon location]"

---

## Workflow (steps the model follows)

1. **Parse user input** to extract:
   - Location (zone name, place name, or lat/lon)
   - Search radius (default 120 km crow-flies)
   - Target species (optional)
   - Query date/timeframe (default today, or "this weekend" for forecast)

2. **Geocode location** -> geo.py
   - If zone gazetteer match (e.g., "Santiam Pass"), use that directly
   - Otherwise, geocode via Open-Meteo, get lat/lon/elevation

3. **Select candidate zones**
   - Load zones.json gazetteer
   - Filter by distance from parsed location (default 120 km radius)
   - Sort by distance

4. **Fetch weather** -> weather.py (one call per zone)
   - Open-Meteo forecast API: 31-day history + 10-day forecast
   - Derived features: soil temp 7d mean, precip 14d, frost nights, snow-free date
   - For chanterelle/fall-king (Aug+), also archive API Aug 1->today for season-opener detection

5. **Fetch SNOTEL melt-out** -> snotel.py (for zones >= 3500 ft in spring)
   - Discover nearest SNOTEL station
   - Fetch WTEQ daily series for this year
   - Compute melt-out date (first zero after peak SWE)
   - Adjust for elevation difference

6. **Fetch fire perimeters** -> fires.py (morel season only, Apr-Jun)
   - Query WFIGS for previous + current year fires >= 500 acres
   - Filter to radius, sort by distance
   - Get centroid elevation

7. **Score each candidate zone x species** -> score.py
   - Load species_registry.json (all thresholds)
   - Per zone: score each species listed in zone.species
   - Inputs: zone, month, weather, SNOTEL, fires
   - Outputs: score 0-100, label, reasons, negatives, confidence
   - Gates: month window, elevation band, side (east/west/crest), hard freeze
   - Components: soil temp tri, moisture ramp, trigger tri, air temp
   - Penalties: frost kill, heat kill, dry gap
   - Burn bonus: morel_burn x1.25 if eligible fire nearby

8. **Rank zones** by score, distance

9. **Compose answer** using template:
   - Data age + bounding
   - TOP CALL: best zone, distance, species, score label, key numbers, habitat, aspect, permit
   - ALSO IN RANGE: 2-4 more zones (short blocks)
   - BURNS: (morel season) eligible fires, names, acres, distance, elevation band
   - WATCH: 10-day forecast impact
   - FINE PRINT: ID disclaimer, permit reminder

---

## Answer Template

```
[DATA TIMESTAMP] "Data as of [date] [time], [timezone]"

[TOP CALL]
Zone name, ~[distance] [direction]. [Species] [score label] because [2-3 key reasons with numbers]. Work [elevation ft], [aspect/habitat], [NF/agency + permit rule].

[ALSO IN RANGE]
Zone A - [species] ([label]) - [one key reason]
Zone B - [species] ([label]) - [one key reason]

[BURNS] (morel season only)
[Fire name], [year], [acres] acres, ~[distance] km [direction]. Try [elev band], [habitat type]. WARNING: burned snags kill in wind; check [forest name] closure orders before driving.

[WATCH]
[Next 10 days: rain/freeze/warm forecast and impact on scores]

[FINE PRINT]
Never eat any wild mushroom you have not positively identified yourself - scores predict fruiting conditions, not what is actually in your basket. When in doubt, throw it out, or run finds past the Cascade Mycological Society (Eugene) or Central Oregon Mushroom Club (Bend). Check permit rules for the land unit before picking; rules change.
```

---

## Worked Example

**User:** "I'm in Bend, it's May 24, anything close?"

**Model answer:**

> Working from Bend, 120 km radius, data as of May 24 7am.
>
> Top call: Metolius / Green Ridge, ~40 min NW. Natural morels are peaking - soil hit 51 F this week, 1.4 in of rain in the last 14 days, and the 3100-3500 ft benches went snow-free around May 8, which puts you 16 days post-melt, dead center of the window. Work mixed conifer north of Camp Sherman, 3100-3800 ft, north aspects now that the season is mid-late at this elevation. Deschutes NF: free-use permit required (free at the Sisters RD), 2 gal/day, cut them in half lengthwise in the field.
>
> Also in range: Santiam Pass (morels "worth a look" - crest is only 9 days post-melt, early but south aspects will have the first flush); Cascade Lakes ("marginal" - still snow above 4800 ft, give it 2 weeks); spring kings at Green Ridge are "worth a look" and will improve behind the morels.
>
> No qualifying burns from last season inside your radius.
>
> Watch: dry and 80 F forecast next week - that cooks the sub-3500 ft morels. If you can only go once, go before Thursday.
>
> Never eat any wild mushroom you have not positively identified yourself - scores predict fruiting conditions, not what is actually in your basket. When in doubt, throw it out, or run finds past the Cascade Mycological Society (Eugene) or Central Oregon Mushroom Club (Bend). Check permit rules for the land unit before picking; rules change.

---

## Guardrails and Fine Print

**These rules are non-negotiable and appear in every foraging answer:**

1. **No invented geography.** Only sources:
   - Zone gazetteer (references/zones.json, 15 zones)
   - Discovered SNOTEL stations (via AWDB API)
   - WFIGS fire perimeters (current + previous year, public service)
   - Do NOT name specific trailheads, road numbers, or "secret patches" unless they come from zone habitat descriptions.

2. **Every foraging answer ends with:**
   > Never eat any wild mushroom you have not positively identified yourself - scores predict fruiting conditions, not what is actually in your basket. When in doubt, throw it out, or run finds past the Cascade Mycological Society (Eugene) or Central Oregon Mushroom Club (Bend). Check permit rules for the land unit before picking; rules change.

3. **Data age and fallbacks are explicit.** A score computed without SNOTEL says so. A fallback to modeled snow depth (not SNOTEL) is noted in reasons.

4. **Scores are likelihoods.** The skill must never promise mushrooms. "Nothing is worth the drive" is a valid answer when true, with conditions that would change it.

5. **Burn answers always include warnings:**
   - Burned snags kill people in wind
   - Check the forest's closure orders before driving
   - (from zone data, not invented)

6. **Crater Lake NP:**  answers for diamond_lemolo zone must say "stay outside the park boundary".

7. **Permit lines come only from references/permits.md.** If last_verified > 12 months, append "verify before you go".

8. **No runtime scraping.** JSON/GeoJSON APIs in section 6 are the complete runtime data surface. No blogs, forums, or third-party sites.

---

## Notes for deployment

- Python 3, standard library only (urllib, json, math, datetime, os, time, zipfile, csv)
- ASCII only, no smart quotes or unicode
- All species thresholds in references/species_registry.json (JSON-driven, no hardcoding)
- Network calls: 15s timeout, one retry, graceful fallback
- Cache: weather 6h, fires 24h, SNOTEL 12h, geocoding permanent
- Runs in Cowork cloud container (network available)
- No external dependencies, no pip installs

---

## FAQ / Common overrides

- **"I only want X species"** -> model filters zone results to that species before answering
- **"Show me all zones in range"** -> model runs full ranking but only shows top 3-5
- **"This weekend"** -> model uses forecast API day-by-day values, labels as forecast
- **"Within 30 km"** -> model passes radius_km=30 to geo/fires scripts
