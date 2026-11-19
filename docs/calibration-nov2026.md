# Season timing: the model against public reports (Nov 2026)

Purpose: give the owner the numbers to decide whether to retune. **Nothing was retuned in this pass.** The page now carries one
plain sentence about it on `sources.html`, next to the checks.

Sources: `site/data/c/metrics.json` (model prime days 2016 to 2025 against public reports in the same years, as shown on the Stats tab),
`site/data/c/live.json` (live scores on 2026-11-18), `site/data/c/history.json` (weekly zones in prime, the same sum the Stats chart
uses) and `site/data/c/sightings.json` (public reports including the blurred-location ones, which the chart also counts).
Dates are day-of-year read on the 2024 calendar, as the page does. "Prime" is a score of 60 or more.

## Early, middle and late dates

Early, middle and late are the 10th, 50th and 90th percentile dates. Positive "model minus reports" means the model is later.

| Mushroom | | Early | Middle | Late | Reports (n) |
|---|---|---|---|---|---|
| Natural morels | model prime | Apr 1 | May 11 | Jun 17 | |
| | reports | Apr 3 | Apr 28 | May 30 | 507 |
| | model minus reports | -2 d | +13 d | +18 d | |
| Spring kings | model prime | May 13 | Jun 9 | Jul 8 | |
| | reports | May 17 | Jun 7 | Jun 30 | 131 |
| | model minus reports | -4 d | +2 d | +8 d | |
| **Chanterelles** | model prime | **Sep 27** | Oct 29 | Dec 2 | |
| | reports | **Aug 17** | Oct 17 | Nov 28 | 1,039 |
| | model minus reports | **+41 d** | +12 d | +4 d | |
| **Fall kings** | model prime | Sep 25 | Oct 30 | **Dec 12** | |
| | reports | Sep 2 | Oct 16 | **Nov 12** | 635 |
| | model minus reports | +23 d | +14 d | **+30 d** | |

Spring kings agree within about a week. Morels run late in the middle and the end. The two autumn mushrooms are the problem:

- **Chanterelles start about six weeks late** (+41 days at the 10th percentile) and the middle is about 12 days late. The end of the season is close (+4 days).
- **Fall kings run about a month too long** (+30 days at the 90th percentile) and the whole window is shifted 2 to 3 weeks late.

### Week by week, the gap behind those percentiles

Chanterelles, August. Reports (all years 2010 on, including blurred-location records) against the model's average number of zones in prime that week (zones with at least 3 complete years):

| Week of | Reports | Model zones in prime |
|---|---|---|
| Aug 5 | 13 | 0.0 |
| Aug 12 | 22 | 0.1 |
| Aug 19 | 25 | 0.3 |
| Aug 26 | 32 | 0.4 |
| Sep 2 | 27 | 0.7 |
| Sep 9 | 40 | 4.6 |
| Sep 16 | 59 | 9.5 |

Reports run 13 to 32 a week through August while the model has 0.0 to 0.4 zones in prime. The model only wakes up in the second week of September.

Fall kings, November and December. Reports taper to nothing by mid-December; the model keeps about four to five zones in prime:

| Week of | Reports | Model zones in prime |
|---|---|---|
| Nov 11 | 33 | 7.1 |
| Nov 18 | 25 | 6.2 |
| Nov 25 | 8 | 4.8 |
| Dec 2 | 4 | 4.9 |
| Dec 9 | 0 | 4.1 |
| Dec 16 | 0 | 4.0 |

## Late-November score spread (live scores, 2026-11-18)

- **Chanterelles, 24 zones in season:** minimum 65, median 92, maximum 94. 22 of 24 score 85 or higher; the other two are 65 and 76 (Mt. Hood east side is the 65). **Nothing sits in the 20 to 59 bands.** In late November, with the season winding down in the reports (6 reports in the last 30 days), every live score still says "prime" or "go now".
- **Fall kings, 9 zones in season:** minimum 56, median 64, maximum 65. None reach 80. Eight are "prime" (60 or more), and the page counts 9 zones in season against 11 fall king reports in the last 30 days.

The scores are not wrong about the weeks that matter most (Sep to Nov for chanterelles, Oct for fall kings), but at the edges of the window they stay high when the reports have faded, and they are low when reports are already coming in.

## Likely causes (not confirmed; each is a thing to test before retuning)

1. **The chanterelle season opener, plus a built-in lag.** In `species_registry.json` the chanterelle trigger needs a "season opener" after Aug 1 (1.0 inch of rain in a rolling 7 days; before it the score is 0), and then ramps in over 10 to 20 days after the opener (`tri` 10, 20, 70, 100). So even a wet early August cannot score before roughly the end of August, and a first 1-inch week in mid-September scores from early October. August reports (13 to 32 a week) come from finds that start before that rain, for example high-elevation Cascade stands and fog-fed coastal forest. A softer first opener (for example half an inch in 7 days), a shorter ramp, or a fog and elevation term is the first thing to try.
2. **Soil temperature in the history runs cold in autumn.** The sensor check (`reality.json`, soil) puts the ERA5 shallow soil temperature 2.1 F cold in September, 4.0 F in October and 5.3 F in November (deep soil: -1.3, -2.9, -4.9). A soil that reads 4 to 5 F too cold stays inside the king bolete temperature window longer, which fits the long fall king tail. It cannot explain the August chanterelle miss, where the bias is small (-0.5 F), and the existing note says a seasonal correction did not improve the match with reports, so treat this as a partial cause.
3. **The fall king window is set to run through December on the coast.** The registry gives fall kings `months_coastal` 9 to 12 and `months_interior` 9 to 10, with soil temperature scored down to 42 to 45 F (`soil_temp_tri` 42, 45, 58, 64) and only frost penalties at the end (a single 28 F night multiplies the score by 0.7; three nights at 27 F or colder zeroes it). Coastal zones rarely see those frosts, so they keep scoring "prime" on cool, moist days well into December, which is where the Dec 12 late date comes from, while reports fade through November. Reports are also shaped by when people go out, which narrows the report window a little at both ends, so some of the gap is the reports, not the model. Check whether the coastal window should end in November, or whether the cold edge of the soil-temperature range (42 to 45 F) is too forgiving.

## What this note does not do

It does not change a threshold, a score or any number on the site. Retuning means editing `scout/references/species_registry.json`
and re-running the history; compare any change against the same percentiles above and against `analysis/VALIDATION.md`.
