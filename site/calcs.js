/* Stats models for Oregon Mushroom Conditions.
   Each calc works only from its inputs (dataset or calc rows) and constants inside it. */

/* One ranking for the whole page: the headline, "Best days this week" and the "Right now" list all use cmp(), so a tie
   gives the same zone first everywhere. Higher score before rounding wins; then the shorter drive from Portland; then name.
   Plain functions with no DOM, so tests can load this file with a stub `dash` and call them. */
window.ShroomRank = (function () {
  const driveH = (z) => (z && typeof z.pdx_drive_h === 'number' ? z.pdx_drive_h : 99);
  const nameOf = (z) => (z && (z.short || z.name)) || '';
  // a, b: { raw, z }. raw is the score before rounding (or the shown value when there is no unrounded one).
  function cmp(a, b) {
    return (b.raw - a.raw) || (driveH(a.z) - driveH(b.z)) || nameOf(a.z).localeCompare(nameOf(b.z));
  }
  // today's score before rounding; the rounded score when the build has no unrounded one
  function rawScore(row) {
    if (!row) return null;
    return typeof row.score_raw === 'number' ? row.score_raw : row.score;
  }
  // forecast day i of a live row, before rounding when available
  function rawDay(row, i) {
    const f = row && row.fc_raw ? String(row.fc_raw).split(',')[i] : undefined;
    if (f !== undefined && f !== '' && !isNaN(+f)) return +f;
    const g = row && row.fc ? String(row.fc).split(',')[i] : undefined;
    return g === undefined || g === '' ? null : +g;
  }
  function list(names) {
    return names.length < 2 ? names.join('') : names.slice(0, -1).join(', ') + ' and ' + names[names.length - 1];
  }
  // zones: [{ short, pdx_drive_h, best: live row with species, score, score_raw }]. speciesWord(key) gives "chanterelle".
  function headline(zones, speciesWord) {
    const lead = zones.filter((z) => z.best && z.best.score >= 60).map((z) => ({ z, row: z.best, raw: rawScore(z.best) })).sort(cmp);
    if (!lead.length) return 'No zone is in prime shape right now.';
    const top = lead[0].row.score;
    const tied = lead.filter((x) => x.row.score === top);
    const sp = (x) => speciesWord(x.row.species);
    let txt = lead.length + (lead.length === 1 ? ' zone is' : ' zones are') + ' in prime shape right now. ';
    if (tied.length === 1) return txt + nameOf(tied[0].z) + ' leads: ' + sp(tied[0]) + ' at ' + top + '.';
    if (tied.length >= 4) return txt + tied.length + ' zones tie at ' + top + ', led by ' + nameOf(tied[0].z) + ' (' + sp(tied[0]) + ').';
    const names = tied.map((x) => nameOf(x.z));
    if (tied.every((x) => sp(x) === sp(tied[0]))) return txt + list(names) + ' lead: ' + sp(tied[0]) + ' at ' + top + '.';
    return txt + list(tied.map((x) => nameOf(x.z) + ' (' + sp(x) + ')')) + ' lead at ' + top + '.';
  }
  // items: [{ z, key, row }], getWeek(item) -> [{ t, v, raw }] forecast days or null. Returns the pairs that reach prime
  // (60+) this week, each at its best day, best first.
  function bestDays(items, getWeek) {
    const picks = [];
    items.forEach((it) => {
      const wk = getWeek(it);
      if (!wk) return;
      const bd = wk.reduce((a, d) => (d.v !== null && (a === null || (d.raw === undefined ? d.v : d.raw) > (a.raw === undefined ? a.v : a.raw)) ? d : a), null);
      if (bd && bd.v >= 60) picks.push({ it, d: bd, i: wk.indexOf(bd), raw: bd.raw === undefined ? bd.v : bd.raw });
    });
    return picks.sort((a, b) => cmp({ raw: a.raw, z: a.it.z }, { raw: b.raw, z: b.it.z }));
  }
  // items: [{ z, v }] for the "Right now" list (v is null for an off-season zone, which goes last); rawOf(item) is the value to compare.
  function rankItems(items, rawOf) {
    return items.slice().sort((a, b) => {
      if ((a.v === null) !== (b.v === null)) return a.v === null ? 1 : -1;
      return cmp({ raw: rawOf(a), z: a.z }, { raw: rawOf(b), z: b.z });
    });
  }
  return { cmp, rawScore, rawDay, headline, bestDays, rankItems, driveH };
})();

dash.calc('series_year', {
  title: 'Season stats by zone, mushroom and year',
  description: 'For each zone and mushroom in each year: days at prime (score 60+) and go-now (80+), first and last prime day, the peak day, and the best score in each week of the year.',
  inputs: ['history', 'zones', 'live'],
  fn: (history, zones, live) => {
    const zoneById = {};
    zones.forEach((z) => { zoneById[z.id] = z; });
    const speciesName = {};
    live.forEach((r) => { speciesName[r.species] = r.display; });
    const lastYear = Math.max.apply(null, history.map((r) => r.year));
    return history.map((r) => {
      const v = r.scores.split(',');
      const wk = [];
      for (let w = 0; w < 53; w++) wk.push('');
      let prime = 0, go = 0, first = null, last = null, peak = null, pf = 0, pl = 0, scored = 0;
      for (let i = 0; i < v.length; i++) {
        if (v[i] === '') continue;
        const s = +v[i];
        scored++;
        const w = Math.floor(i / 7);
        if (wk[w] === '' || s > +wk[w]) wk[w] = s;
        if (s >= 60) { prime++; if (first === null) first = i + 1; last = i + 1; }
        if (s >= 80) go++;
        if (peak === null || s > peak) { peak = s; pf = i + 1; pl = i + 1; }
        else if (s === peak) pl = i + 1;
      }
      const z = zoneById[r.zone];
      return {
        series: r.series, zone: r.zone, zone_name: z ? z.name.split(' / ')[0] : r.zone,
        species: r.species, species_name: speciesName[r.species] || r.species,
        family: r.species.indexOf('morel') === 0 ? 'morel' : r.species,
        elev_ft: z ? z.elev_ft : null, year: r.year, partial: r.year === lastYear,
        scored_days: scored, prime_days: prime, go_days: go,
        first_prime: first, last_prime: last,
        peak_score: peak, peak_doy: peak === null ? null : Math.round((pf + pl) / 2),
        weekly: wk.join(',')
      };
    });
  }
});

dash.calc('season_windows', {
  title: 'Typical season window per zone and mushroom',
  description: 'Median first and last day a zone reached prime (60+), the earliest start and latest end across years, and the typical best day. Only complete years that reached prime count, and at least 3 are needed.',
  inputs: ['series_year'],
  fn: (series_year) => {
    const by = {};
    series_year.forEach((r) => { if (!r.partial) (by[r.series] = by[r.series] || []).push(r); });
    const med = (a) => {
      const s = a.slice().sort((x, y) => x - y);
      const n = s.length;
      return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
    };
    const out = [];
    Object.keys(by).forEach((k) => {
      const rows = by[k];
      const pr = rows.filter((r) => r.first_prime !== null);
      if (rows.length < 3 || pr.length < 3) return;
      const r0 = rows[0];
      out.push({
        series: k, zone: r0.zone, zone_name: r0.zone_name, species: r0.species, species_name: r0.species_name,
        family: r0.family, elev_ft: r0.elev_ft,
        years_total: rows.length, years_prime: pr.length,
        start_med: Math.round(med(pr.map((r) => r.first_prime))),
        end_med: Math.round(med(pr.map((r) => r.last_prime))),
        start_min: Math.min.apply(null, pr.map((r) => r.first_prime)),
        end_max: Math.max.apply(null, pr.map((r) => r.last_prime)),
        peak_med: Math.round(med(pr.map((r) => r.peak_doy))),
        prime_days_avg: Math.round(rows.reduce((a, r) => a + r.prime_days, 0) / rows.length * 10) / 10
      });
    });
    return out;
  }
});

dash.calc('weekly_busy', {
  title: 'Zones in prime by week of year',
  description: 'For each week of the year and mushroom type, the expected number of zones in prime shape: for each zone with at least 3 complete years, the share of its years in which a day that week reached prime (60+), added up.',
  inputs: ['series_year'],
  fn: (series_year) => {
    const by = {};
    series_year.forEach((r) => { if (!r.partial) (by[r.series] = by[r.series] || []).push(r); });
    const tot = {};
    Object.keys(by).forEach((k) => {
      const rows = by[k];
      if (rows.length < 3) return;
      const wk = rows.map((r) => r.weekly.split(','));
      for (let w = 0; w < 53; w++) {
        let kp = 0;
        wk.forEach((a) => { if (a[w] !== '' && +a[w] >= 60) kp++; });
        const key = rows[0].family + '|' + w;
        tot[key] = (tot[key] || 0) + kp / rows.length;
      }
    });
    const out = [];
    ['morel', 'king_spring', 'chanterelle', 'king_fall'].forEach((f) => {
      for (let w = 0; w < 53; w++) {
        out.push({ week: w + 1, week_start_doy: w * 7 + 1, family: f, avg_zones: Math.round((tot[f + '|' + w] || 0) * 100) / 100 });
      }
    });
    return out;
  }
});

dash.calc('prime_by_week', {
  title: 'Odds of prime conditions by week',
  description: 'For each zone and mushroom and each week of the year: the share of complete years in which a day that week reached prime (60+) and go-now (80+), with an 80% Wilson confidence interval on the prime share.',
  inputs: ['series_year'],
  fn: (series_year) => {
    const by = {};
    series_year.forEach((r) => { if (!r.partial) (by[r.series] = by[r.series] || []).push(r); });
    const z = 1.2816;
    const wilson = (k, n) => {
      const p = k / n, d = 1 + z * z / n, c = p + z * z / (2 * n);
      const m = z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n));
      return [Math.max(0, (c - m) / d), Math.min(1, (c + m) / d)];
    };
    const r3 = (x) => Math.round(x * 1000) / 1000;
    const out = [];
    Object.keys(by).forEach((k) => {
      const rows = by[k];
      if (rows.length < 3) return;
      const n = rows.length;
      const wk = rows.map((r) => r.weekly.split(','));
      for (let w = 0; w < 53; w++) {
        let kp = 0, kg = 0, sum = 0, m = 0;
        wk.forEach((a) => {
          if (a[w] !== '') { const s = +a[w]; sum += s; m++; if (s >= 60) kp++; if (s >= 80) kg++; }
        });
        const ci = wilson(kp, n);
        out.push({
          series: k, zone: rows[0].zone, species: rows[0].species, family: rows[0].family,
          week: w + 1, week_start_doy: w * 7 + 1, years: n, years_prime: kp,
          p_prime: r3(kp / n), p_lo: r3(ci[0]), p_hi: r3(ci[1]), p_go: r3(kg / n),
          mean_score: m ? Math.round(sum / m) : null
        });
      }
    });
    return out;
  }
});

dash.calc('year_totals', {
  title: 'Prime zone-days per year',
  description: 'For each year, the total number of prime (60+) and go-now (80+) days summed over the zones and mushrooms that have the full record (every complete year), so years compare fairly. The latest year is partial.',
  inputs: ['series_year'],
  fn: (series_year) => {
    const count = {};
    series_year.forEach((r) => { if (!r.partial) count[r.series] = (count[r.series] || 0) + 1; });
    const most = Math.max.apply(null, Object.keys(count).map((k) => count[k]));
    const by = {};
    series_year.forEach((r) => {
      if (count[r.series] !== most) return;
      const b = by[r.year] || (by[r.year] = { year: r.year, prime_days: 0, go_days: 0, series: 0, partial: r.partial });
      b.prime_days += r.prime_days;
      b.go_days += r.go_days;
      b.series++;
    });
    return Object.keys(by).sort().map((y) => by[y]);
  }
});

dash.calc('timing_fit', {
  title: 'Elevation and timing fit',
  description: 'For each mushroom type, a least-squares line of the typical best day of the season against zone elevation: how many days later the season peaks per 1,000 ft of elevation, and how much of the spread that explains (r squared).',
  inputs: ['season_windows'],
  fn: (season_windows) => {
    const by = {};
    season_windows.forEach((r) => { (by[r.family] = by[r.family] || []).push(r); });
    const out = [];
    Object.keys(by).forEach((f) => {
      const a = by[f], n = a.length;
      if (n < 3) return;
      const mx = a.reduce((s, r) => s + r.elev_ft, 0) / n;
      const my = a.reduce((s, r) => s + r.peak_med, 0) / n;
      let sxx = 0, sxy = 0, syy = 0;
      a.forEach((r) => {
        sxx += (r.elev_ft - mx) * (r.elev_ft - mx);
        sxy += (r.elev_ft - mx) * (r.peak_med - my);
        syy += (r.peak_med - my) * (r.peak_med - my);
      });
      if (sxx === 0) return;
      const slope = sxy / sxx;
      out.push({
        family: f, n: n,
        slope_days_per_1000ft: Math.round(slope * 10000) / 10,
        intercept: Math.round((my - slope * mx) * 100) / 100,
        r2: syy === 0 ? 0 : Math.round(sxy * sxy / (sxx * syy) * 100) / 100
      });
    });
    return out;
  }
});

dash.calc('now_vs_typical', {
  title: 'Today against past years',
  description: 'For each zone and mushroom scoring today, how the live score ranks against the modeled scores for the same date (3 days either side) in earlier years, and the typical score for that date.',
  inputs: ['history', 'live', 'about'],
  fn: (history, live, about) => {
    const day = about[0].generated_at.slice(0, 10);
    const t = Date.parse(day + 'T00:00:00Z');
    const yr = new Date(t).getUTCFullYear();
    const doy = Math.round((t - Date.UTC(yr, 0, 1)) / 86400000) + 1;
    const by = {};
    history.forEach((r) => { if (r.year < yr) (by[r.series] = by[r.series] || []).push(r); });
    const out = [];
    live.forEach((l) => {
      if (l.score === null) return;
      const key = l.zone + '|' + l.species;
      const rows = by[key];
      if (!rows || rows.length < 3) return;
      const vals = [];
      rows.forEach((r) => {
        const a = r.scores.split(',');
        for (let d = doy - 3; d <= doy + 3; d++) {
          const v = a[d - 1];
          if (v !== undefined && v !== '') vals.push(+v);
        }
      });
      if (vals.length < 10) return;
      vals.sort((x, y) => x - y);
      let below = 0, equal = 0;
      vals.forEach((v) => { if (v < l.score) below++; else if (v === l.score) equal++; });
      const n = vals.length;
      const median = n % 2 ? vals[(n - 1) / 2] : (vals[n / 2 - 1] + vals[n / 2]) / 2;
      out.push({
        series: key, zone: l.zone, species: l.species, score_now: l.score,
        typical_median: Math.round(median), percentile: Math.round((below + equal / 2) / n * 100) / 100,
        samples: n, years: rows.length
      });
    });
    return out;
  }
});

dash.calc('kpis', {
  title: 'Headline figures',
  description: 'Zone count, series with at least 3 complete years, series with the full record, years covered, the best past year by prime zone-days, the busiest typical week, and how many zones are in prime or go-now shape today.',
  inputs: ['zones', 'live', 'series_year', 'year_totals', 'weekly_busy'],
  fn: (zones, live, series_year, year_totals, weekly_busy) => {
    const count = {};
    series_year.forEach((r) => { if (!r.partial) count[r.series] = (count[r.series] || 0) + 1; });
    const nSeries = Object.keys(count).filter((k) => count[k] >= 3).length;
    const most = Math.max.apply(null, Object.keys(count).map((k) => count[k]));
    const nCore = Object.keys(count).filter((k) => count[k] === most).length;
    const done = year_totals.filter((y) => !y.partial);
    let best = done[0];
    done.forEach((y) => { if (y.prime_days > best.prime_days) best = y; });
    const tot = {};
    weekly_busy.forEach((r) => { tot[r.week] = (tot[r.week] || 0) + r.avg_zones; });
    let bw = 1;
    Object.keys(tot).forEach((w) => { if (tot[w] > tot[bw]) bw = +w; });
    const zbest = {};
    live.forEach((l) => { if (l.score !== null) zbest[l.zone] = Math.max(zbest[l.zone] || 0, l.score); });
    const vals = Object.keys(zbest).map((k) => zbest[k]);
    return [{
      zones: zones.length, series_with_history: nSeries, series_core: nCore,
      year_first: done[0].year, year_last: done[done.length - 1].year,
      best_year: best.year, best_year_days: best.prime_days,
      busy_week_doy: (bw - 1) * 7 + 1, busy_week_zones: Math.round(tot[bw]),
      prime_now: vals.filter((v) => v >= 60).length, go_now: vals.filter((v) => v >= 80).length
    }];
  }
});

/* Field evidence: how many public reports (GBIF, mostly iNaturalist) of one mushroom lie near a place, so the page can say
   plainly when a score has nothing but the weather model behind it. Same circle the "Past finds nearby" section uses:
   40 km, widened to 80 km when fewer than 15 reports fall inside it. Plain functions with no DOM, so tests can load this
   file with a stub `dash` and call them.
   sight: { rows: [{ sp, lat, lon }], blur: [{ sp, lat, lon }] } (blurred-location reports count: they are real finds)
   level: 'none' (no reports in the circle), 'thin' (1 to 4) or 'ok' (5 or more). */
window.ShroomEvidence = (function () {
  const NEAR_KM = 40, FAR_KM = 80, SPARSE_BELOW = 15, THIN_BELOW = 5;
  const distKm = (lat, lon, r) => Math.hypot((r.lon - lon) * Math.cos(lat * Math.PI / 180) * 111.32, (r.lat - lat) * 111.2);
  const within = (set, key, lat, lon, km) => (set || []).filter((r) => r.sp === key && distKm(lat, lon, r) <= km);
  function check(sight, lat, lon, key) {
    let km = NEAR_KM;
    let rows = within(sight && sight.rows, key, lat, lon, km), blur = within(sight && sight.blur, key, lat, lon, km);
    if (rows.length + blur.length < SPARSE_BELOW) {
      km = FAR_KM;
      rows = within(sight && sight.rows, key, lat, lon, km);
      blur = within(sight && sight.blur, key, lat, lon, km);
    }
    const n = rows.length + blur.length;
    return { km: km, mi: Math.round(km / 1.609), n: n, rows: rows, blur: blur, level: n === 0 ? 'none' : (n < THIN_BELOW ? 'thin' : 'ok') };
  }
  // { title, body } for a place with little or no evidence; null when there is enough. name: the mushroom, lower case.
  function message(ev, name) {
    if (!ev || ev.level === 'ok') return null;
    if (ev.level === 'none') {
      return { title: 'No field evidence',
        body: 'No public reports of ' + name + ' on file within ' + ev.mi + ' miles since 2010. Scores here come from the weather model alone and have never been checked against a real find nearby. Treat them as unverified.' };
    }
    return { title: 'Thin field evidence',
      body: 'Only ' + ev.n + (ev.n === 1 ? ' public report' : ' public reports') + ' of ' + name + ' within ' + ev.mi + ' miles since 2010. Scores here are mostly the weather model: treat them with caution.' };
  }
  return { check: check, message: message, NEAR_KM: NEAR_KM, FAR_KM: FAR_KM, SPARSE_BELOW: SPARSE_BELOW, THIN_BELOW: THIN_BELOW };
})();
