/* Western Oregon Mushroom Conditions - page logic (Leaflet + USGS topo map).
   Text lives in the HTML. This file listens, sets class/hidden/aria, and draws inside [data-draw] elements. */
(function () {
'use strict';

/* ---------- constants ---------- */
const FAMS = ['morel', 'king_spring', 'chanterelle', 'king_fall'];
const FAM = {
  morel: { name: 'Morels', short: 'Morel', color: '#c4562b' },
  king_spring: { name: 'Spring king bolete', short: 'Spring king', color: '#3f9d5b' },
  chanterelle: { name: 'Pacific golden chanterelle', short: 'Chanterelle', color: '#e4a40f' },
  king_fall: { name: 'Fall king bolete', short: 'Fall king', color: '#3b73c8' }
};
const BANDS = [
  { max: 19, name: 'Dead', range: '0-19', color: '#7d8695' },
  { max: 39, name: 'Marginal', range: '20-39', color: '#b99d63' },
  { max: 59, name: 'Worth a look', range: '40-59', color: '#e0b535' },
  { max: 79, name: 'Good', range: '60-79', color: '#7bc05a' },
  { max: 100, name: 'Go now', range: '80-100', color: '#1e9e5f' }
];
const bandIdx = (s) => (s < 20 ? 0 : s < 40 ? 1 : s < 60 ? 2 : s < 80 ? 3 : 4);
const scoreColor = (s) => BANDS[bandIdx(s)].color;
const scoreRamp = d3.scaleLinear().domain([10, 30, 50, 70, 90]).range(BANDS.map((b) => b.color)).interpolate(d3.interpolateRgb).clamp(true);
const METRICS = {
  score: { label: 'Score', unit: '' },
  o7: { label: 'Expected in ~7 days', unit: '', outlook: 7 },
  o14: { label: 'Expected in ~14 days', unit: '', outlook: 14 },
  soil_t: { label: 'Soil temperature', col: 'soil_t_f', unit: ' F', dom: [30, 70], dec: 0, ramp: d3.interpolateYlOrRd },
  soil_m: { label: 'Soil moisture', col: 'soil_m_pct', unit: '%', dom: [10, 50], dec: 0, ramp: d3.interpolateYlGnBu },
  rh: { label: 'Humidity (daily mean)', col: 'rh_pct', unit: '%', dom: [40, 100], dec: 0, ramp: d3.interpolateYlGnBu },
  vpd: { label: 'Dryness of the air (VPD)', col: 'vpd_kpa', unit: ' kPa', dom: [0, 1.2], dec: 2, ramp: d3.interpolateYlOrRd },
  rain14: { label: 'Rain, last 14 days', col: 'rain14_in', unit: ' in', dom: [0, 6], dec: 1, ramp: d3.interpolateYlGnBu },
  tmax: { label: 'Air high', col: 'tmax_f', unit: ' F', dom: [30, 95], dec: 0, ramp: d3.interpolateYlOrRd }
};
const isWx = () => S.mode === 'live' && !!METRICS[S.metric].col;
const isOutlook = () => S.mode === 'live' && !!METRICS[S.metric].outlook;
const fInt = d3.format(',');
const fPct = d3.format('.0%');
const fMD = d3.utcFormat('%b %-d');
const fDow = d3.utcFormat('%a');
/* Forecast-scored days for one live row: [{t: Date, v: score or null}, ...] (today first), or null when the build has none. */
function fcWeek(row) {
  if (!row || !row.fc || !row.fc_start) return null;
  const vals = String(row.fc).split(',').map((x) => (x === '' ? null : +x));
  if (vals.length < 2) return null;
  const t0 = Date.parse(row.fc_start + 'T00:00:00Z');
  if (!isFinite(t0)) return null;
  return vals.map((v, i) => ({ t: new Date(t0 + i * 864e5), v: v }));
}
const fMon = d3.utcFormat('%b');
const dDate = (doy, y) => new Date(Date.UTC(y || 2024, 0, doy));
const doyStr = (doy, y) => fMD(dDate(doy, y));
const MONTH_DOY = d3.range(12).map((m) => Math.round((Date.UTC(2024, m, 1) - Date.UTC(2024, 0, 1)) / 864e5) + 1);
const famOf = (k) => (k.indexOf('morel') === 0 ? 'morel' : k);
const $ = (s, r) => (r || document).querySelector(s);
const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
function h(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = text;
  return e;
}
function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }
function hours(x) {
  if (x === null || x === undefined || x === '') return null;
  const m = Math.round(+x * 60), hh = Math.floor(m / 60), mm = m % 60;
  return (hh ? hh + ' h' : '') + (hh && mm ? ' ' : '') + (mm ? mm + ' min' : '');
}
function inkOn(color) { return d3.lab(color).l > 64 ? '#14181f' : '#ffffff'; }

/* ---------- state ---------- */
const S = {
  tab: 'map', sp: 'all', region: 'all', land: 'all', elev: 'any', minScore: 0, q: '', sort: 'metric', seasonOnly: false, mode: 'live', year: null, doy: null,
  playing: false, metric: 'score', heat: true, markers: true, layers: false, landMap: true, sight: true, sightWhen: 'season', sightPub: false,
  zone: null, zsp: null,
  fam: 'all', showAll: false, series: null, syear: null, week: null
};
let MAP = null;
let playTimer = null;

/* ---------- model ---------- */
let MODEL = null;
function model() {
  const ids = ['zones', 'live', 'history', 'weather', 'about', 'grid', 'grid_hist'];
  const d = {};
  for (const id of ids) {
    const r = dash.data(id);
    if (r.status !== 'ok' || !r.data) return null;
    d[id] = r.data;
  }
  if (MODEL && ids.every((id) => MODEL.src[id] === d[id])) return MODEL;
  const about = d.about[0];
  const zones = d.zones.map((z) => {
    const parts = z.name.split(' / ');
    return Object.assign({}, z, {
      short: parts[0], sub: parts.slice(1).join(' / '), spKeys: z.species.split(','),
      regionList: z.regions.split(','), rows: [], w: null, best: null
    });
  });
  const zById = {};
  zones.forEach((z) => { zById[z.id] = z; });
  d.live.forEach((r) => { if (zById[r.zone]) zById[r.zone].rows.push(r); });
  d.weather.forEach((r) => { if (zById[r.zone]) zById[r.zone].w = r; });
  zones.forEach((z) => {
    z.best = z.rows.filter((r) => r.score !== null).sort((a, b) => b.score - a.score)[0] || null;
  });
  const hist = new Map();
  d.history.forEach((r) => {
    let m = hist.get(r.series);
    if (!m) { m = new Map(); hist.set(r.series, m); }
    m.set(r.year, r.scores.split(',').map((s) => (s === '' ? null : +s)));
  });
  const years = Array.from(new Set(d.history.map((r) => r.year))).sort();
  const asOf = new Date(about.generated_at);
  const dayStr = about.generated_at.slice(0, 10);
  const t = Date.parse(dayStr + 'T00:00:00Z');
  const todayYear = new Date(t).getUTCFullYear();
  const todayDoy = Math.round((t - Date.UTC(todayYear, 0, 1)) / 864e5) + 1;
  const gridPts = new Map();
  d.grid.forEach((r) => {
    let g = gridPts.get(r.id);
    if (!g) { g = { id: r.id, lat: r.lat, lon: r.lon, elev_ft: r.elev_ft, live: {}, o7: {}, o14: {} }; gridPts.set(r.id, g); }
    if (r.species) { g.live[r.species] = r.score; g.o7[r.species] = r.o7; g.o14[r.species] = r.o14; }
  });
  const gridHist = new Map();
  d.grid_hist.forEach((r) => {
    const k = r.id + '|' + r.species;
    let m = gridHist.get(k);
    if (!m) { m = new Map(); gridHist.set(k, m); }
    m.set(r.year, r.scores.split(',').map((x) => (x === '' ? null : +x)));
  });
  const fullSeries = Array.from(hist.entries()).filter((e) => e[1].size >= 3).map((e) => e[0]);
  MODEL = {
    src: d, about, zones, zById, hist, years, asOf, todayYear, todayDoy, fullSeries,
    completeYears: years.filter((y) => y < todayYear),
    gridPts: Array.from(gridPts.values()), gridHist, gridStep: +about.grid_step || 3
  };
  return MODEL;
}
function seriesInfo(M, key) {
  const parts = key.split('|');
  const z = M.zById[parts[0]];
  const fam = famOf(parts[1]);
  return { key, z, sp: parts[1], fam, label: (z ? z.short : parts[0]) + ' - ' + FAM[fam].short };
}
const memo = new WeakMap();
function indexRows(arr, keyFn) {
  let m = memo.get(arr);
  if (!m) { m = new Map(); arr.forEach((r) => { const k = keyFn(r); (m.get(k) || m.set(k, []).get(k)).push(r); }); memo.set(arr, m); }
  return m;
}
function calcRows(id) {
  const r = dash.data(id);
  return r.status === 'ok' && Array.isArray(r.data) ? r.data : null;
}
const bySeries = (rows) => indexRows(rows, (r) => r.series);
function firstRow(id, key) {
  const rows = calcRows(id);
  if (!rows) return null;
  const a = bySeries(rows).get(key);
  return a ? a[0] : null;
}

/* ---------- zone values for the map ---------- */
function zoneValue(M, z) {
  if (isOutlook()) {
    const f = 'd' + METRICS[S.metric].outlook + '_med';
    let best = null;
    z.rows.forEach((r) => {
      if (r[f] === null || r[f] === undefined) return;
      if (S.sp !== 'all' && r.species !== S.sp) return;
      if (!best || r[f] > best[f]) best = r;
    });
    return best ? { v: best[f], key: best.species, row: best } : { v: null };
  }
  if (isWx()) {
    const m = METRICS[S.metric];
    const v = z.w ? z.w[m.col] : null;
    return { v: v === undefined ? null : v };
  }
  if (S.mode === 'live') {
    let best = null;
    z.rows.forEach((r) => {
      if (r.score === null) return;
      if (S.sp !== 'all' && r.species !== S.sp) return;
      if (!best || r.score > best.score) best = r;
    });
    return best ? { v: best.score, key: best.species, row: best } : { v: null };
  }
  let bv = null, bk = null;
  z.spKeys.forEach((k) => {
    if (S.sp !== 'all' && k !== S.sp) return;
    const m = M.hist.get(z.id + '|' + k);
    const a = m && m.get(S.year);
    const v = a ? a[S.doy - 1] : null;
    if (v !== null && v !== undefined && (bv === null || v > bv)) { bv = v; bk = k; }
  });
  return { v: bv, key: bk };
}
function mapItems(M) {
  const items = [];
  const q = S.q.trim().toLowerCase();
  M.zones.forEach((z) => {
    if (S.region !== 'all' && z.regionList.indexOf(S.region) < 0) return;
    if (S.land !== 'all' && z.land.indexOf(S.land) < 0) return;
    if (S.elev === 'low' && z.elev_ft >= 1500) return;
    if (S.elev === 'mid' && (z.elev_ft < 1500 || z.elev_ft > 3500)) return;
    if (S.elev === 'high' && z.elev_ft <= 3500) return;
    if (q && z.name.toLowerCase().indexOf(q) < 0) return;
    if (S.sp !== 'all' && z.spKeys.indexOf(S.sp) < 0) return;
    const zv = zoneValue(M, z);
    if (S.seasonOnly && zv.v === null) return;
    if (S.minScore > 0 && !isWx() && (zv.v === null || zv.v < S.minScore)) return;
    items.push({ z, v: zv.v, key: zv.key, row: zv.row });
  });
  return items;
}
function gridItems(M) {
  if (isWx()) return [];
  if (S.region !== 'all' || S.land !== 'all' || S.elev !== 'any' || S.q.trim()) return [];
  const keys = S.sp === 'all' ? ['morel_natural', 'king_spring', 'chanterelle', 'king_fall'] : [S.sp];
  const out = [];
  M.gridPts.forEach((p) => {
    let best = null;
    keys.forEach((k) => {
      let v = null;
      if (isOutlook()) v = (p['o' + METRICS[S.metric].outlook] || {})[k];
      else if (S.mode === 'live') v = p.live[k];
      else {
        const m = M.gridHist.get(p.id + '|' + k);
        const a = m && m.get(S.year);
        v = a ? a[Math.floor((S.doy - 1) / M.gridStep)] : null;
      }
      if (v === undefined) v = null;
      if (v !== null && (best === null || v > best)) best = v;
    });
    if (best !== null && (S.minScore <= 0 || best >= S.minScore)) out.push({ lon: p.lon, lat: p.lat, v: best });
  });
  return out;
}
function valueColor(v) {
  if (v === null || v === undefined) return null;
  if (isWx()) {
    const m = METRICS[S.metric];
    return m.ramp(clamp((v - m.dom[0]) / (m.dom[1] - m.dom[0]), 0, 1));
  }
  return scoreRamp(v);
}
function valueText(v) {
  if (v === null || v === undefined) return '';
  if (isWx()) return v.toFixed(METRICS[S.metric].dec);
  return String(Math.round(v));
}

/* ---------- small ui helpers ---------- */
function makeTip(el) {
  const t = h('div', 'tip');
  t.hidden = true;
  el.appendChild(t);
  return {
    show(ev, lines) {
      t.replaceChildren();
      lines.forEach((ln) => {
        const row = h('div', ln.cls || 'tip-l');
        if (ln.sw) { const sw = h('i', 'tip-sw'); sw.style.background = ln.sw; row.appendChild(sw); }
        row.appendChild(document.createTextNode(ln.t));
        t.appendChild(row);
      });
      t.hidden = false;
      const p = d3.pointer(ev, el);
      const tw = t.offsetWidth, th = t.offsetHeight, W = el.clientWidth;
      let x = p[0] + 14;
      if (x + tw > W - 4) x = p[0] - tw - 14;
      t.style.left = Math.max(4, x) + 'px';
      t.style.top = Math.max(4, p[1] - th - 10 < 4 ? p[1] + 14 : p[1] - th - 10) + 'px';
    },
    hide() { t.hidden = true; }
  };
}
function svgIn(el, height) {
  el.replaceChildren();
  const w = Math.max(260, el.clientWidth || 600);
  const s = d3.select(el).append('svg').attr('width', '100%').attr('viewBox', '0 0 ' + w + ' ' + height).attr('role', 'img');
  return { s, w, h: height };
}
function measure(s, texts, cls) {
  const probe = s.append('text').attr('class', cls || 'ax');
  let m = 0;
  texts.forEach((t) => { m = Math.max(m, probe.text(t).node().getComputedTextLength()); });
  probe.remove();
  return m;
}
function placeholder(el, msg) {
  el.replaceChildren();
  el.appendChild(h('p', 'muted pad', msg || '-'));
}
function monthAxis(g, x, y0, y1, doyMin, doyMax, height, labelY) {
  MONTH_DOY.forEach((d, m) => {
    if (d < doyMin || d > doyMax) return;
    g.append('line').attr('class', 'grid').attr('x1', x(d)).attr('x2', x(d)).attr('y1', y0).attr('y2', y1);
    g.append('text').attr('class', 'ax').attr('x', x(d) + 3).attr('y', labelY).text(fMon(dDate(d)));
  });
}

/* ---------- state sync (class / hidden / aria only) ---------- */
function sync() {
  $$('[data-tab]').forEach((b) => {
    const on = b.dataset.tab === S.tab;
    b.classList.toggle('is-on', on);
    b.setAttribute('aria-selected', on ? 'true' : 'false');
  });
  $('#map').hidden = S.tab !== 'map';
  $('#stats').hidden = S.tab !== 'stats';
  $('#zpanel').hidden = !S.zone;
  $('#mapwrap').classList.toggle('has-panel', !!S.zone);
  $('#tm').hidden = S.mode !== 'time';
  $('#layers').hidden = !S.layers;
  $('#layers-btn').classList.toggle('is-on', S.layers);
  $('#layers-btn').setAttribute('aria-expanded', S.layers ? 'true' : 'false');
  $$('[data-sp]').forEach((b) => b.classList.toggle('is-on', b.dataset.sp === S.sp));
  $$('[data-mode]').forEach((b) => b.classList.toggle('is-on', b.dataset.mode === S.mode));
  $$('[data-fam]').forEach((b) => b.classList.toggle('is-on', b.dataset.fam === S.fam));
  $('#metric').disabled = S.mode !== 'live';
  if (S.mode !== 'live') { S.metric = 'score'; }
  $('#metric').value = S.metric;
  $('#region').value = S.region;
  $('#land').value = S.land;
  $('#elev').value = S.elev;
  $('#sort').value = S.sort;
  $('#minscore').value = String(S.minScore);
  $('#q').value = S.q;
  const M0 = model();
  $('#brief-card').hidden = !(M0 && M0.about.brief_text) || S.mode !== 'live';
  $('#seasons-more').classList.toggle('is-on', S.showAll);
  $('#seasons-more').setAttribute('aria-pressed', S.showAll ? 'true' : 'false');
  $('#opt-heat').checked = S.heat;
  $('#opt-markers').checked = S.markers;
  $('#opt-season').checked = S.seasonOnly;
  $('#opt-landmap').checked = S.landMap;
  $('#land-key').hidden = !S.landMap;
  $('#opt-sight').checked = S.sight;
  $('#sight-opts').hidden = !S.sight;
  $('#sight-when').value = S.sightWhen;
  $('#opt-sightpub').checked = S.sightPub;
  const sl = $('#tm-slider');
  if (S.doy !== null) sl.value = String(S.doy);
  $('#tm-play').classList.toggle('is-on', S.playing);
  $('#tm-play').setAttribute('aria-pressed', S.playing ? 'true' : 'false');
}
function redraw(names) { names.forEach((n) => dash.draw(n)); }
const MAPSET = ['map', 'ranklist', 'legend', 'zpanel', 'timeread', 'takeaway'];
const EXSET = ['series-select', 'exhead', 'odds', 'years', 'calendar', 'yeartrace'];

/* ---------- actions ---------- */
function showTab(name, link) {
  S.tab = name;
  sync();
  if (link !== false) dash.setLink(name);
  if (name === 'map') redraw(MAPSET);
  else redraw(['kpi', 'seasons', 'weekly', 'weeklens', 'elev'].concat(EXSET));
}
function setDefaultsFromModel(M) {
  if (S.year === null) S.year = M.completeYears[M.completeYears.length - 1];
  if (S.doy === null) S.doy = M.todayDoy;
  if (S.series === null) {
    let best = null;
    const most = d3.max(M.fullSeries, (k) => M.hist.get(k).size);
    M.zones.forEach((z) => {
      z.rows.forEach((r) => {
        const k = z.id + '|' + r.species;
        if (r.score === null || M.fullSeries.indexOf(k) < 0 || M.hist.get(k).size < most) return;
        if (!best || r.score > best.score) best = { k, score: r.score };
      });
    });
    S.series = best ? best.k : M.fullSeries[0];
  }
  if (S.syear === null && S.series) S.syear = defaultYear(M, S.series);
}
function defaultYear(M, key) {
  const m = key ? M.hist.get(key) : null;
  return m ? Math.max.apply(null, Array.from(m.keys())) : null;
}
function selectZone(id, fly) {
  const M = model();
  if (!M) return;
  const z = M.zById[id];
  if (!z) return;
  S.zone = id;
  const zv = zoneValue(M, z);
  S.zsp = zv.key || (z.best ? z.best.species : (S.sp !== 'all' && z.spKeys.indexOf(S.sp) >= 0 ? S.sp : z.spKeys[0]));
  sync();
  redraw(['map', 'zpanel', 'ranklist']);
  if (fly) flyTo(z);
}
function clearZone() {
  S.zone = null;
  sync();
  redraw(['map', 'ranklist']);
}
function selectSeries(key, scroll) {
  const M = model();
  S.series = key;
  S.syear = M ? defaultYear(M, key) : null;
  redraw(EXSET);
  if (scroll) {
    const el = $('#explorer');
    if (el && el.scrollIntoView) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}
function openStats(key) {
  const M = model();
  S.series = key;
  S.syear = M ? defaultYear(M, key) : null;
  showTab('stats');
  const el = $('#explorer');
  if (el && el.scrollIntoView) el.scrollIntoView({ block: 'start' });
}
function stopPlay() {
  S.playing = false;
  if (playTimer) { clearInterval(playTimer); playTimer = null; }
}
function startPlay() {
  stopPlay();
  S.playing = true;
  playTimer = setInterval(() => {
    S.doy = S.doy >= 366 ? 1 : S.doy + 2;
    sync();
    redraw(['map', 'timeread', 'ranklist', 'zpanel']);
  }, 110);
}

/* ---------- map (Leaflet + USGS topo; the heat layer is a canvas drawn between the tiles and the markers) ---------- */
const TOPO = 'https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}';
let OREGON_RING = null;
fetch('oregon.json').then((r) => r.json()).then((f) => { OREGON_RING = f.geometry.coordinates[0][0]; if (MAP) dash.draw('map'); }).catch(() => { OREGON_RING = null; });

function panelShift() {
  const wide = window.matchMedia('(min-width: 920px)').matches;
  return wide ? [192, 0] : [0, Math.round((MAP && MAP.el.clientHeight ? MAP.el.clientHeight : 500) * 0.3)];
}
function flyTo(z) {
  if (!MAP || !MAP.lmap) return;
  const m = MAP.lmap;
  const zoom = Math.max(m.getZoom(), 9);
  const sh = panelShift();
  const c = m.unproject(m.project([z.lat, z.lon], zoom).add(sh), zoom);
  m.flyTo(c, zoom, { duration: 0.6 });
}
function resetView() {
  const M = model();
  if (!MAP || !MAP.lmap || !M) return;
  const pts = M.zones.map((z) => [z.lat, z.lon]).concat(M.gridPts.map((p) => [p.lat, p.lon]));
  MAP.progUntil = Date.now() + 700;            // marks the next move as ours, not the visitor's
  MAP.lmap.fitBounds(pts, { padding: [28, 28], maxZoom: 11, animate: false });
}
function iconFor(it, selected, hiZoom) {
  const col = valueColor(it.v);
  const rgb = col ? d3.color(col) : null;
  const wrap = document.createElement('div');
  const dot = h('div', 'mkd' + (it.v === null ? ' off' : '') + (selected ? ' sel' : ''), valueText(it.v) || '-');
  if (col) { dot.style.background = col; dot.style.color = inkOn(col); }
  wrap.appendChild(dot);
  wrap.appendChild(h('div', 'mkn', it.z.short));
  void rgb; void hiZoom;
  return L.divIcon({ html: wrap.innerHTML, className: 'mkicon', iconSize: [34, 34], iconAnchor: [17, 17] });
}
function tipFor(it) {
  const box = document.createElement('div');
  box.appendChild(h('div', 'tip-t', it.z.short));
  if (it.v === null) box.appendChild(h('div', 'tip-m', S.mode === 'live' ? 'Off-season / not scored' : 'No score on this date'));
  else if (isWx()) box.appendChild(h('div', 'tip-l', METRICS[S.metric].label + ': ' + valueText(it.v) + METRICS[S.metric].unit));
  else box.appendChild(h('div', 'tip-l', (it.key ? FAM[famOf(it.key)].short + ' - ' : '') + BANDS[bandIdx(it.v)].name + ' (' + Math.round(it.v) + ')' + (isOutlook() ? ' in ~' + METRICS[S.metric].outlook + ' days' : '')));
  return box;
}
function bindMarkers(made, M, items) {
  made.items = items;
  made.gMark.clearLayers();
  if (!S.markers) return;
  const ordered = items.slice().sort((a, b) => (a.v === null) - (b.v === null) || (a.v || 0) - (b.v || 0));
  ordered.forEach((it) => {
    const mk = L.marker([it.z.lat, it.z.lon], { icon: iconFor(it, it.z.id === S.zone), title: it.z.short + (it.v === null ? ', off-season' : ', ' + valueText(it.v)), keyboard: true, riseOnHover: true, zIndexOffset: it.z.id === S.zone ? 1000 : Math.round((it.v || 0) * 5) });
    mk.bindTooltip(tipFor(it), { direction: 'top', offset: [0, -16], className: 'mtip' });
    mk.on('click', () => selectZone(it.z.id, true));
    mk.addTo(made.gMark);
  });
}
function ringClip(ctx, m) {
  if (!OREGON_RING) return false;
  ctx.beginPath();
  OREGON_RING.forEach((p, i) => { const q = m.latLngToContainerPoint([p[1], p[0]]); if (i) ctx.lineTo(q.x, q.y); else ctx.moveTo(q.x, q.y); });
  ctx.closePath();
  ctx.clip();
  return true;
}
function drawHeat(made) {
  const m = made.lmap, cv = made.canvas;
  if (!m || !cv) return;
  const sz = m.getSize(), w = sz.x, hgt = sz.y;
  if (!w || !hgt) return;
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  cv.width = Math.round(w * dpr); cv.height = Math.round(hgt * dpr);
  cv.style.width = w + 'px'; cv.style.height = hgt + 'px';
  L.DomUtil.setPosition(cv, m.containerPointToLayerPoint([0, 0]));
  const ctx = cv.getContext('2d');
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, cv.width, cv.height);
  const pts = (made.items || []).filter((it) => it.v !== null).map((it) => ({ lat: it.z.lat, lon: it.z.lon, v: it.v })).concat(made.grid || []);
  if (!S.heat || !pts.length) return;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const scr = pts.map((it) => { const q = m.latLngToContainerPoint([it.lat, it.lon]); return { x: q.x, y: q.y, v: it.v }; });
  const mpp = 156543.03392 * Math.cos(44 * Math.PI / 180) / Math.pow(2, m.getZoom());
  const pxPerKm = 1000 / mpp;
  const hasGrid = !!(made.grid && made.grid.length);
  const sigma = (hasGrid ? 25 : 40) * pxPerKm;
  const reach = sigma * 3.2;
  const cell = 6;
  const gw = Math.ceil(w / cell), gh = Math.ceil(hgt / cell);
  const off = document.createElement('canvas');
  off.width = gw; off.height = gh;
  const octx = off.getContext('2d');
  const img = octx.createImageData(gw, gh);
  const inv2s2 = 1 / (2 * sigma * sigma);
  for (let j = 0; j < gh; j++) {
    for (let i = 0; i < gw; i++) {
      const x = i * cell + cell / 2, y = j * cell + cell / 2;
      let sw = 0, sv = 0;
      for (let n = 0; n < scr.length; n++) {
        const dx = x - scr[n].x, dy = y - scr[n].y;
        const d2 = dx * dx + dy * dy;
        if (d2 > reach * reach) continue;
        const wgt = Math.exp(-d2 * inv2s2);
        sw += wgt; sv += wgt * scr[n].v;
      }
      if (sw < 0.02) continue;
      const c = d3.rgb(valueColor(sv / sw));
      const a = Math.min(1, sw / 0.55) * 0.62;
      const o = (j * gw + i) * 4;
      img.data[o] = c.r; img.data[o + 1] = c.g; img.data[o + 2] = c.b; img.data[o + 3] = Math.round(a * 255);
    }
  }
  octx.putImageData(img, 0, 0);
  ctx.save();
  ringClip(ctx, m);
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(off, 0, 0, gw, gh, 0, 0, gw * cell, gh * cell);
  ctx.restore();
}
function scheduleHeat(made) {
  if (made.raf) cancelAnimationFrame(made.raf);
  made.raf = requestAnimationFrame(() => { made.raf = 0; drawHeat(made); });
}
function spotEstimate(ev) {
  const M = model();
  if (!M || S.mode !== 'live' || !MAP) return;
  let best = null, bd = 1e9;
  const kx = Math.cos(ev.latlng.lat * Math.PI / 180) * 111.32;
  M.gridPts.forEach((p) => {
    const dx = (ev.latlng.lng - p.lon) * kx, dy = (ev.latlng.lat - p.lat) * 111.2, d = Math.sqrt(dx * dx + dy * dy);
    if (d < bd) { bd = d; best = p; }
  });
  if (!best || bd > 45) return;
  const box = h('div', 'spot');
  box.appendChild(h('b', null, 'Regional estimate, not the exact spot'));
  box.appendChild(h('div', 'muted small', 'Nearest sample point is ' + Math.round(bd) + ' km away at about ' + fInt(best.elev_ft) + ' ft. Local elevation and aspect change a lot.'));
  const keys = Object.keys(best.live).filter((k) => best.live[k] !== null && best.live[k] !== undefined).sort((a, b) => best.live[b] - best.live[a]);
  if (!keys.length) box.appendChild(h('div', null, 'Nothing is in season here right now.'));
  keys.forEach((k) => {
    let t = FAM[famOf(k)].short + ': ' + best.live[k] + ' (' + BANDS[bandIdx(best.live[k])].name.toLowerCase() + ')';
    if (best.o7[k] !== null && best.o7[k] !== undefined) t += ', in ~7 days usually ' + best.o7[k];
    if (best.o14[k] !== null && best.o14[k] !== undefined) t += ', ~14 days ' + best.o14[k];
    box.appendChild(h('div', null, t));
  });
  L.popup({ className: 'spotpop' }).setLatLng(ev.latlng).setContent(box).openOn(MAP.lmap);
}

dash.draw('map', {
  mount(el) {
    el.replaceChildren();
    const lmap = L.map(el, { zoomControl: false, zoomAnimation: false, attributionControl: false, minZoom: 5, maxZoom: 15, zoomSnap: 0.25, worldCopyJump: false });
    L.tileLayer(TOPO, { maxZoom: 15, attribution: 'Tiles: U.S. Geological Survey' }).addTo(lmap);
    L.control.attribution({ position: 'bottomright', prefix: false }).addTo(lmap);
    lmap.createPane('heat');
    const hp = lmap.getPane('heat');
    hp.style.zIndex = 350; hp.style.pointerEvents = 'none';
    const canvas = document.createElement('canvas');
    canvas.className = 'heatc';
    hp.appendChild(canvas);
    lmap.createPane('land');
    const lp = lmap.getPane('land');
    lp.style.zIndex = 360; lp.style.pointerEvents = 'none';
    const landLayer = L.tileLayer(LANDTILE, { pane: 'land', maxZoom: 15, opacity: 0.62, attribution: 'Land ownership: BLM Surface Management Agency' });
    const gSight = L.layerGroup().addTo(lmap);
    const gMark = L.layerGroup().addTo(lmap);
    const made = { el, lmap, canvas, gMark, gSight, landLayer, rend: L.canvas({ padding: 0.5 }), items: [], grid: [], raf: 0, fitted: false };
    lmap.on('moveend zoomend resize', () => scheduleHeat(made));
    lmap.on('zoomend', () => { el.classList.toggle('z-hi', lmap.getZoom() >= 9); if (S.sight && SIGHT) drawSightings(made); });
    lmap.on('click', spotEstimate);
    lmap.setView([44.2, -122.3], 7);
    // the zoom follows the screen size until the visitor moves the map themselves
    const mine = () => Date.now() < (made.progUntil || 0);
    lmap.on('movestart zoomstart', () => { if (!mine()) made.userMoved = true; });
    if (window.ResizeObserver) {
      new ResizeObserver(() => {
        if (!el.clientWidth || !el.clientHeight) return;
        lmap.invalidateSize({ animate: false });
        if (!made.userMoved && made.fitted) resetView();
        scheduleHeat(made);
      }).observe(el);
    }
    MAP = made;
    return made;
  },
  update(el, made) {
    const M = model();
    if (!M) return;
    setDefaultsFromModel(M);
    if (!el.clientWidth || !el.clientHeight) {
      if ((made.retries = (made.retries || 0) + 1) < 12) requestAnimationFrame(() => dash.draw('map'));
      return;
    }
    made.retries = 0;
    made.lmap.invalidateSize({ animate: false });
    if (!made.fitted) { made.fitted = true; resetView(); }
    bindMarkers(made, M, mapItems(M));
    made.grid = gridItems(M);
    syncLandLayer(made);
    drawSightings(made);
    el.classList.toggle('z-hi', made.lmap.getZoom() >= 9);
    scheduleHeat(made);
  },
  unmount() { MAP = null; }
});

/* ---------- past finds (iNaturalist reports), land ownership overlay and the zone-panel "Past finds nearby" section ---------- */
const SIGHT_KEY = { morel: 'morel_natural', morel_natural: 'morel_natural', morel_burn: 'morel_natural', king_spring: 'king_spring', chanterelle: 'chanterelle', king_fall: 'king_fall' };
const OPEN_LAND = { f: 1, b: 1, s: 1 };            // national forest, BLM, state land: usually open to personal-use picking, subject to the rules
const LANDTILE = 'https://gis.blm.gov/arcgis/rest/services/lands/BLM_Natl_SMA_Cached_without_PriUnk/MapServer/tile/{z}/{y}/{x}';
const MONTHS1 = ['J', 'F', 'M', 'A', 'M', 'J', 'J', 'A', 'S', 'O', 'N', 'D'];
let SIGHT = null;
let sightReq = null;
function loadSightings() {
  if (sightReq) return sightReq;
  sightReq = fetch('data/c/sightings.json').then((r) => (r.ok ? r.json() : null)).then((d) => {
    if (!d) { sightReq = null; return null; }
    SIGHT = {
      meta: d, land: d.land,
      rows: d.rows.map((r) => {
        const t = Date.parse(r[2] + 'T00:00:00Z'), y = new Date(t).getUTCFullYear();
        return { id: r[0], sp: d.species[r[1]], date: r[2], t, y, doy: Math.round((t - Date.UTC(y, 0, 1)) / 864e5) + 1, lat: r[3], lon: r[4], land: r[5] };
      })
    };
    redraw(['map', 'reality']);
    if (S.zone) redraw(['zpanel']);
    return SIGHT;
  }).catch(() => { sightReq = null; return null; });
  return sightReq;
}
function sightRef() {
  const M = model();
  if (S.mode === 'live' || !S.year || !S.doy) return M ? Date.parse(M.about.generated_at.slice(0, 10) + 'T00:00:00Z') : Date.now();
  return Date.UTC(S.year, 0, S.doy);
}
function sightPredicate(spKey) {
  const ref = sightRef(), refDoy = Math.round((ref - Date.UTC(new Date(ref).getUTCFullYear(), 0, 1)) / 864e5) + 1;
  const sp = spKey === undefined ? (S.sp === 'all' ? null : SIGHT_KEY[S.sp]) : spKey;
  return (r) => {
    if (sp && r.sp !== sp) return false;
    if (S.sightPub && !OPEN_LAND[r.land]) return false;
    if (S.sightWhen === 'recent') return r.t <= ref && ref - r.t <= 30 * 864e5;
    if (S.sightWhen === 'season') { const d = Math.abs(r.doy - refDoy); return Math.min(d, 365 - d) <= 21; }
    return true;
  };
}
/* Photo of a past find: fetched from GBIF only when a dot is opened (nothing is loaded from third parties until then).
   Only photos hosted by iNaturalist's open-data bucket are shown; any other host stays a plain link. */
const PHOTO_HOST = 'https://inaturalist-open-data.s3.amazonaws.com/photos/';
const photoCache = new Map();
function loadPhoto(id) {
  if (!photoCache.has(id)) {
    photoCache.set(id, fetch('https://api.gbif.org/v1/occurrence/' + id).then((x) => (x.ok ? x.json() : null)).then((d) => {
      const imgs = ((d && d.media) || []).filter((m) => m.type === 'StillImage' && typeof m.identifier === 'string' && m.identifier.indexOf(PHOTO_HOST) === 0 && /^https?:\/\/creativecommons\.org\//.test(m.license || ''));
      if (!imgs.length) return null;
      const lic = (imgs[0].license.match(/licenses\/([a-z-]+)\/([\d.]+)/) || []);
      return {
        src: imgs[0].identifier.replace(/\/(original|large|medium|small|square)\.(\w+)$/, '/medium.$2'),
        by: imgs[0].creator || imgs[0].rightsHolder || '',
        lic: lic[1] ? 'CC ' + lic[1].toUpperCase() + ' ' + lic[2] : /publicdomain\/zero/.test(imgs[0].license) ? 'CC0' : 'CC',
        more: imgs.length - 1
      };
    }).catch(() => { photoCache.delete(id); return null; }));
  }
  return photoCache.get(id);
}
/* Forest structure around each zone (LANDFIRE 2024), precomputed into data/c/habitat.json. */
let HAB = null;
let habReq = null;
function loadHab() {
  if (habReq) return habReq;
  habReq = fetch('data/c/habitat.json').then((r) => (r.ok ? r.json() : null)).then((d) => {
    HAB = d || { zones: {}, species: {} };
    redraw(['reality']);
    if (S.zone) redraw(['zpanel']);
    return HAB;
  }).catch(() => { HAB = { zones: {}, species: {} }; return HAB; });
  return habReq;
}
function habitatSection(host, z, sp) {
  if (!HAB) { loadHab(); return; }
  const zh = HAB.zones[z.id];
  if (!zh) return;
  const sec = h('div', 'zp-sec');
  sec.appendChild(h('h4', null, 'Forest around this zone'));
  sec.appendChild(h('p', 'zp-note', zh.forest + '% of the land within about 4 miles is forest; ' + zh.late + '% is late-development closed forest (the oldest, densest class) and ' + zh.tall + '% is stands 100 ft (30 m) or taller.'));
  const key = SIGHT_KEY[sp], s = HAB.species[key];
  if (key === 'morel_natural') {
    if (s) sec.appendChild(h('p', 'zp-note', 'Morels often come up on open or disturbed ground (burns, river bottoms, orchards): only ' + s.finds_pct.forest + '% of public morel reports are in mapped forest, so forest structure is not used as a clue for morels.'));
  } else if (s) {
    const nm = FAM[famOf(sp)].short.toLowerCase() + 's';
    const fit = { strong: 'Strong: this zone has some of the oldest, tallest forest of our zones.', average: 'Average: forest age and height are in the middle of our zones.', weak: 'Weak: younger or shorter forest than most of our zones.' }[zh.tier];
    if (fit) { const p = h('p', 'zp-note'); p.appendChild(h('b', null, 'Habitat fit. ')); p.appendChild(document.createTextNode(fit)); sec.appendChild(p); }
    sec.appendChild(h('p', 'zp-note', 'Public reports of ' + nm + ' lean toward older, taller forest: ' + s.finds_pct.late + '% were in late-development closed forest (' + s.background_pct.late + '% of the land around our zones is) and ' + s.finds_pct.tall + '% in stands 100 ft or taller (' + s.background_pct.tall + '%). Reports often come from trails and roads, so this is a hint, not a rule.'));
  }
  sec.appendChild(h('p', 'zp-note', 'Source: LANDFIRE 2024 (USGS and U.S. Forest Service), 30 m pixels. Forest age and height are mapped estimates and do not show logging or fire since 2024.'));
  host.appendChild(sec);
}

/* "Report your own find" links to the two sources the finds come from (via GBIF). */
function reportLinks(cls, lead, tag) {
  const s = h(tag || 'span', cls, lead);
  [['iNaturalist', 'https://www.inaturalist.org/observations/upload'], ['Mushroom Observer', 'https://mushroomobserver.org/observations/new']].forEach((l, i) => {
    if (i) s.appendChild(document.createTextNode(' or '));
    const a = h('a', null, l[0]);
    a.href = l[1]; a.target = '_blank'; a.rel = 'noopener noreferrer';
    s.appendChild(a);
  });
  s.appendChild(document.createTextNode('. Finds with a photo license and a public location show up here in a week or two.'));
  return s;
}
function sightPopup(r, popup) {
  const box = h('div', 'spot');
  box.appendChild(h('b', null, FAM[famOf(r.sp)].short + ', ' + fMD(new Date(r.t)) + ', ' + r.y));
  const ph = h('div', 'spot-photo muted small', 'Loading photo...');
  box.appendChild(ph);
  box.appendChild(h('div', 'muted small', SIGHT.land[r.land] ? 'Land: ' + SIGHT.land[r.land].toLowerCase() : 'Land type not checked yet'));
  const rec = 'https://www.gbif.org/occurrence/' + r.id;
  const a = h('a', null, 'Open this report (GBIF)');
  a.href = rec;
  a.target = '_blank'; a.rel = 'noopener noreferrer';
  box.appendChild(a);
  box.appendChild(h('div', 'muted small', 'A photo report is not proof the spot is open to picking.'));
  loadPhoto(r.id).then((p) => {
    if (!p) { ph.remove(); if (popup) popup.update(); return; }
    const img = h('img');
    img.alt = FAM[famOf(r.sp)].short + ' reported near here, ' + r.y;
    img.referrerPolicy = 'no-referrer';
    img.addEventListener('load', () => { ph.textContent = ''; ph.className = 'spot-photo'; const l = h('a'); l.href = rec; l.target = '_blank'; l.rel = 'noopener noreferrer'; l.appendChild(img); ph.appendChild(l); ph.appendChild(h('div', 'muted small', 'Photo' + (p.by ? ' by ' + p.by : '') + ', ' + p.lic + (p.more > 0 ? ' (+' + p.more + ' more on the report)' : ''))); if (popup) popup.update(); });
    img.addEventListener('error', () => { ph.remove(); if (popup) popup.update(); });
    img.src = p.src;
  });
  return box;
}
function drawSightings(made) {
  made.gSight.clearLayers();
  const note = $('#sight-note');
  if (!S.sight) { note.hidden = true; return; }
  note.hidden = false;
  if (!SIGHT) { note.textContent = 'Loading past finds...'; loadSightings(); return; }
  const keep = sightPredicate(), ref = sightRef(), hi = made.lmap.getZoom() >= 10;
  let n = 0, rec = 0;
  SIGHT.rows.forEach((r) => {
    if (!keep(r)) return;
    n++;
    const fresh = r.t <= ref && ref - r.t <= 30 * 864e5;
    if (fresh) rec++;
    const col = FAM[famOf(r.sp)].color;
    const m = L.circleMarker([r.lat, r.lon], { renderer: made.rend, radius: hi ? 6 : 4.5, weight: fresh ? 2 : 1, color: fresh ? '#111' : '#fff', fillColor: col, fillOpacity: 0.88, bubblingMouseEvents: false });
    m.on('click', (ev) => { const pop = L.popup({ className: 'spotpop', maxWidth: 270, autoPanPaddingTopLeft: [20, 64], autoPanPaddingBottomRight: [20, 20] }).setLatLng(ev.latlng); pop.setContent(sightPopup(r, pop)).openOn(made.lmap); });
    m.addTo(made.gSight);
  });
  const when = S.sightWhen === 'recent' ? 'in the 30 days before ' + fMD(new Date(ref)) : S.sightWhen === 'season' ? 'within 3 weeks of ' + fMD(new Date(ref)) + ' in any year since 2010' : 'since 2010';
  note.textContent = fInt(n) + ' past finds ' + when + (S.sightPub ? ', on land open to picking' : '') + (rec && S.sightWhen !== 'recent' ? ' (' + rec + ' in the last 30 days, dark ring)' : '') + '.';
  note.appendChild(h('span', 'sub', ' These public reports show where people look, not where mushrooms are likeliest.'));
  const rep = h('div', 'rep');
  rep.appendChild(reportLinks(null, 'Found something? Report it on '));
  note.appendChild(rep);
}
function syncLandLayer(made) {
  const has = made.lmap.hasLayer(made.landLayer);
  if (S.landMap && !has) made.landLayer.addTo(made.lmap);
  if (!S.landMap && has) made.lmap.removeLayer(made.landLayer);
}
function nearbyFinds(host, z, sp) {
  const sec = h('div', 'zp-sec');
  host.appendChild(sec);
  const head = () => { sec.replaceChildren(h('h4', null, 'Past finds nearby')); };
  head();
  if (!SIGHT) { sec.appendChild(h('p', 'zp-note', 'Loading reports...')); loadSightings(); return; }
  const key = SIGHT_KEY[sp], R = 40, kx = Math.cos(z.lat * Math.PI / 180) * 111.32;
  const rows = SIGHT.rows.filter((r) => r.sp === key && Math.hypot((r.lon - z.lon) * kx, (r.lat - z.lat) * 111.2) <= R);
  const nm = FAM[famOf(sp)].short.toLowerCase();
  if (!rows.length) {
    sec.appendChild(h('p', 'zp-note', 'No public reports of ' + nm + ' on file within 25 miles. Scores here come from the weather model alone.'));
    sec.appendChild(reportLinks('zp-note', 'Been here? Be the first to report on ', 'p'));
    return;
  }
  const ref = sightRef();
  const recent = rows.filter((r) => r.t <= ref && ref - r.t <= 30 * 864e5);
  const before = rows.filter((r) => r.t <= ref);
  const last = before.length ? before[before.length - 1] : null;
  sec.appendChild(h('p', 'zp-note', fInt(rows.length) + ' reports of ' + nm + ' within 25 miles since 2010; ' + recent.length + ' in the 30 days before ' + fMD(new Date(ref)) + (last ? ' (latest ' + fMD(new Date(last.t)) + ', ' + last.y + ')' : '') + '.'));
  const cnt = d3.range(12).map(() => 0);
  rows.forEach((r) => { cnt[new Date(r.t).getUTCMonth()]++; });
  const mx = Math.max.apply(null, cnt), cur = new Date(ref).getUTCMonth();
  const bars = h('div', 'zp-bars');
  cnt.forEach((c, i) => {
    const col = h('div', 'zp-bar' + (i === cur ? ' now' : ''));
    const fill = h('i');
    fill.style.height = Math.max(c ? 4 : 0, Math.round(c / mx * 40)) + 'px';
    fill.title = fMon(new Date(Date.UTC(2024, i, 1))) + ': ' + c + ' reports';
    col.appendChild(fill);
    col.appendChild(h('span', null, MONTHS1[i]));
    bars.appendChild(col);
  });
  sec.appendChild(bars);
  const order = cnt.map((c, i) => [c, i]).sort((a, b) => b[0] - a[0]);
  const top = order[1][0] >= mx * 0.5 ? [order[0][1], order[1][1]].sort((a, b) => a - b) : [order[0][1]];
  sec.appendChild(h('p', 'zp-note', 'Most reports come in ' + top.map((m) => fMon(new Date(Date.UTC(2024, m, 1)))).join(' and ') + '. Bars: reports by month, all years; the current month is outlined.'));
  const tally = {};
  rows.forEach((r) => { tally[r.land] = (tally[r.land] || 0) + 1; });
  const checked = rows.length - (tally['?'] || 0), open = (tally.f || 0) + (tally.b || 0) + (tally.s || 0);
  if (checked > 0) {
    const parts = [];
    [['f', 'national forest'], ['b', 'BLM'], ['s', 'state land'], ['l', 'county, city or research land'], ['r', 'no-picking or restricted areas'], ['p', 'private or not mapped']].forEach((p) => { if (tally[p[0]]) parts.push(tally[p[0]] + ' ' + p[1]); });
    sec.appendChild(h('p', 'zp-note', 'Land at these spots: ' + parts.join(', ') + '. About ' + fPct(open / checked) + ' were on land that is usually open to personal-use picking.' + (tally['?'] ? ' (' + tally['?'] + ' not checked yet.)' : '')));
  }
  sec.appendChild(h('p', 'zp-note', 'These are public observation reports (mostly iNaturalist photos), usually from trails, roads and parks. They show where people look, not where mushrooms are likeliest, and a report does not mean the spot is open to picking: check the permit rules and the land owner.'));
  sec.appendChild(reportLinks('zp-note', 'Found some here? Add your report on ', 'p'));
  const go = h('button', 'btn sm alt', 'Show these finds on the map');
  go.type = 'button';
  go.addEventListener('click', () => { S.sight = true; S.sightWhen = 'all'; S.sightPub = false; sync(); redraw(['map', 'legend', 'ranklist']); });
  sec.appendChild(go);
}

/* ---------- legend, ranked list, readouts ---------- */
dash.draw('legend', (el) => {
  el.replaceChildren();
  if (isWx()) {
    const m = METRICS[S.metric];
    el.appendChild(h('span', 'lg-t', m.label));
    const bar = h('span', 'lg-bar');
    bar.style.background = 'linear-gradient(90deg,' + d3.range(0, 1.01, 0.25).map((x) => m.ramp(x)).join(',') + ')';
    el.appendChild(bar);
    el.appendChild(h('span', 'lg-r', m.dom[0] + ' to ' + m.dom[1] + m.unit));
    return;
  }
  BANDS.forEach((b) => {
    const c = h('span', 'lg-c');
    const dot = h('i', 'lg-dot');
    dot.style.background = b.color;
    c.appendChild(dot);
    c.appendChild(document.createTextNode(b.name + ' ' + b.range));
    el.appendChild(c);
  });
  const off = h('span', 'lg-c muted');
  off.appendChild(h('i', 'lg-dot off'));
  off.appendChild(document.createTextNode('Off-season'));
  el.appendChild(off);
});

dash.draw('ranklist', (el) => {
  const M = model();
  el.replaceChildren();
  if (!M) { el.appendChild(h('p', 'muted pad', '-')); return; }
  const items = mapItems(M).sort((a, b) => {
    if (S.sort === 'name') return a.z.short.localeCompare(b.z.short);
    if (S.sort === 'pdx') return a.z.pdx_km - b.z.pdx_km;
    if ((a.v === null) !== (b.v === null)) return a.v === null ? 1 : -1;
    return (b.v || 0) - (a.v || 0) || a.z.short.localeCompare(b.z.short);
  });
  const scored = items.filter((i) => i.v !== null).length;
  const title = S.mode === 'live' ? 'Right now' : 'On ' + doyStr(S.doy, S.year) + ', ' + S.year;
  const head = h('div', 'rl-h');
  head.appendChild(h('span', 'rl-t', title));
  head.appendChild(h('span', 'rl-n', scored + ' scored of ' + items.length + ' zones'));
  if (S.mode === 'live' && !isWx()) {                     // best days this week, from the forecast-scored rows
    const picks = [];
    items.forEach((it) => {
      if (it.v === null || !it.key) return;
      const wk = fcWeek(it.z.rows.filter((r) => r.species === it.key)[0]);
      if (!wk) return;
      const bd = wk.reduce((a, d) => (d.v !== null && (a === null || d.v > a.v) ? d : a), null);
      if (bd && bd.v >= 60) picks.push({ it: it, d: bd, i: wk.indexOf(bd) });
    });
    picks.sort((a, b) => b.d.v - a.d.v || a.d.t - b.d.t || (a.it.z.pdx_km || 0) - (b.it.z.pdx_km || 0));
    if (picks.length) {
      const card = h('div', 'rl-wk');
      card.appendChild(h('h4', null, 'Best days this week'));
      picks.slice(0, 5).forEach((p) => {
        const b = h('button', 'rl-i');
        b.type = 'button';
        const badge = h('span', 'rl-b', String(p.d.v));
        badge.style.background = scoreColor(p.d.v); badge.style.color = inkOn(scoreColor(p.d.v));
        b.appendChild(badge);
        const mid = h('span', 'rl-m');
        mid.appendChild(h('span', 'rl-name', p.it.z.short));
        mid.appendChild(h('span', 'rl-sub', FAM[famOf(p.it.key)].short + ' - ' + (p.i === 0 ? 'today' : fDow(p.d.t) + ' ' + fMD(p.d.t))));
        b.appendChild(mid);
        const dist = p.it.z.pdx_drive_h ? hours(p.it.z.pdx_drive_h) : null;
        b.appendChild(h('span', 'rl-d', dist ? dist : fInt(Math.round(p.it.z.pdx_km * 0.621)) + ' mi'));
        b.addEventListener('click', () => selectZone(p.it.z.id, true));
        card.appendChild(b);
      });
      card.appendChild(h('p', 'zp-note', 'Forecast-scored; ' + (picks.length > 5 ? picks.length + ' zone-mushroom pairs reach prime this week.' : 'these reach prime this week.')));
      el.appendChild(card);
    }
  }
  el.appendChild(head);
  const ul = h('div', 'rl');
  items.forEach((it) => {
    const b = h('button', 'rl-i' + (it.z.id === S.zone ? ' sel' : '') + (it.v === null ? ' off' : ''));
    b.type = 'button';
    const badge = h('span', 'rl-b', it.v === null ? '-' : valueText(it.v));
    if (it.v !== null) { badge.style.background = valueColor(it.v); badge.style.color = inkOn(valueColor(it.v)); }
    b.appendChild(badge);
    const mid = h('span', 'rl-m');
    mid.appendChild(h('span', 'rl-name', it.z.short));
    let sub;
    if (it.v === null) sub = 'off-season';
    else if (isWx()) sub = METRICS[S.metric].label + METRICS[S.metric].unit;
    else sub = FAM[famOf(it.key)].short + ' - ' + BANDS[bandIdx(it.v)].name.toLowerCase();
    mid.appendChild(h('span', 'rl-sub', sub));
    b.appendChild(mid);
    const dist = it.z.pdx_drive_h ? hours(it.z.pdx_drive_h) : null;
    b.appendChild(h('span', 'rl-d', dist ? dist : fInt(Math.round(it.z.pdx_km * 0.621)) + ' mi'));
    b.addEventListener('click', () => selectZone(it.z.id, true));
    ul.appendChild(b);
  });
  el.appendChild(ul);
});

dash.draw('timeread', (el) => {
  const M = model();
  if (!M) { el.textContent = '-'; return; }
  const items = mapItems(M);
  const prime = items.filter((i) => i.v !== null && i.v >= 60).length;
  el.replaceChildren();
  el.appendChild(h('b', 'tr-d', doyStr(S.doy, S.year) + ', ' + S.year));
  el.appendChild(h('span', 'tr-s', prime + (prime === 1 ? ' zone' : ' zones') + ' in prime shape'));
});
dash.draw('tm-year', (sel) => {
  const M = model();
  sel.replaceChildren();
  if (!M) return;
  M.years.slice().reverse().forEach((y) => sel.appendChild(new Option(String(y) + (y === M.todayYear ? ' (so far)' : ''), String(y))));
  sel.value = String(S.year);
  sel.onchange = () => { S.year = +sel.value; redraw(['map', 'ranklist', 'timeread', 'zpanel']); };
});

dash.draw('takeaway', (el) => {
  const M = model();
  if (!M) { el.textContent = '-'; return; }
  const zs = M.zones.filter((z) => z.best && z.best.score >= 60).sort((a, b) => b.best.score - a.best.score);
  const when = new Intl.DateTimeFormat('en-US', { timeZone: 'America/Los_Angeles', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(M.asOf);
  let txt;
  if (zs.length) {
    const t = zs[0];
    txt = zs.length + (zs.length === 1 ? ' zone is' : ' zones are') + ' in prime shape right now. ' + t.short + ' leads: ' + FAM[famOf(t.best.species)].short.toLowerCase() + ' at ' + t.best.score + '.';
  } else {
    txt = 'No zone is in prime shape right now.';
  }
  el.textContent = txt + ' Scores as of ' + when + ' Pacific.';
});

/* ---------- zone panel: every weather measure vs the usual range (from data/wx/<zone>.json) ---------- */
const WXTILES = [
  ['Soil temp, top 7 cm', 'soil_t_shallow_f', ' F', 0, 1], ['Soil temp, 28-100 cm', 'soil_t_deep_f', ' F', 0, 1],
  ['Soil moisture, top', 'soil_m_shallow', '%', 0, 100], ['Soil moisture, mid', 'soil_m_mid', '%', 0, 100], ['Soil moisture, deep', 'soil_m_deep', '%', 0, 100],
  ['Humidity (mean)', 'rh_mean', '%', 0, 1], ['Dew point', 'dew_point_f', ' F', 0, 1], ['Dryness of the air (VPD)', 'vpd_kpa', ' kPa', 2, 1],
  ['Rain, 7 days', 'precip_in', ' in', 1, 1, 7], ['Rain, 14 days', 'precip_in', ' in', 1, 1, 14], ['Rain, 30 days', 'precip_in', ' in', 1, 1, 30],
  ['Air high', 'temp_max_f', ' F', 0, 1], ['Air low', 'temp_min_f', ' F', 0, 1], ['Wind', 'wind_mph', ' mph', 0, 1], ['Cloud cover', 'cloud_pct', '%', 0, 1]
];
const wxCache = {};
function loadWxZone(id) {
  if (wxCache[id]) return Promise.resolve(wxCache[id]);
  return fetch('data/wx/' + id + '.json').then((r) => (r.ok ? r.json() : null)).then((d) => { if (d) wxCache[id] = d; return d; }).catch(() => null);
}
function wxIdx(w, y, doy0) { return Math.round((Date.UTC(y, 0, 1 + doy0) - Date.parse(w.start + 'T00:00:00Z')) / 864e5); }
function wxAt(w, col, i, sum) {
  const arr = w.d[col];
  if (!arr) return null;
  if (sum) {
    let s = 0, n = 0;
    for (let k = i - sum + 1; k <= i; k++) { const v = arr[k]; if (v !== null && v !== undefined) { s += v; n++; } }
    return n >= sum * 0.7 ? s : null;
  }
  const x = arr[i];
  return x === undefined ? null : x;
}
function usualRange(w, col, doy0, y0, sum, mult) {
  const others = [];
  for (let y = 2016; y <= new Date().getUTCFullYear(); y++) {
    if (y === y0) continue;
    for (let k = -7; k <= 7; k++) {
      const ii = wxIdx(w, y, doy0 + k);
      if (ii < 0 || ii >= w.d.rh_mean.length) continue;
      const o = wxAt(w, col, ii, sum);
      if (o !== null) others.push(o * mult);
    }
  }
  return others.sort(d3.ascending);
}
function dryNote(w) {
  const d = new Date(Date.parse(w.last + 'T00:00:00Z'));
  const y0 = d.getUTCFullYear(), doy0 = Math.round((d - Date.UTC(y0, 0, 1)) / 864e5), i0 = wxIdx(w, y0, doy0), low = [];
  [['soil moisture', 'soil_m_shallow', 0], ['humidity', 'rh_mean', 0], ['30-day rain', 'precip_in', 30]].forEach((t) => {
    const v = wxAt(w, t[1], i0, t[2]);
    if (v === null) return;
    const o = usualRange(w, t[1], doy0, y0, t[2], 1);
    if (o.length > 30 && o.filter((x) => x < v).length / o.length <= 0.15) low.push(t[0]);
  });
  return low.length >= 2 ? low : null;
}
function downloadCsv(z, w) {
  const n = w.d.rh_mean.length, t0 = Date.parse(w.start + 'T00:00:00Z'), lines = ['date,' + w.cols.join(',')];
  for (let i = 0; i < n; i++) {
    const row = [new Date(t0 + i * 864e5).toISOString().slice(0, 10)];
    w.cols.forEach((c) => { const v = w.d[c][i]; row.push(v === null || v === undefined ? '' : v); });
    lines.push(row.join(','));
  }
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/csv' }));
  a.download = z.id + '_daily_weather.csv';
  document.body.appendChild(a); a.click(); a.remove();
}
function moreMeasures(host, z) {
  const det = h('details', 'zp-more');
  det.open = !!S.moreOpen;
  det.addEventListener('toggle', () => { S.moreOpen = det.open; });
  const sum = h('summary', null, 'All weather measures, compared with usual');
  det.appendChild(sum);
  const body = h('div', 'zp-morebody');
  det.appendChild(body);
  host.appendChild(det);
  const fill = (w) => {
    body.replaceChildren();
    if (!w) { body.appendChild(h('p', 'zp-note', 'Detailed weather is not available for this zone yet.')); return; }
    let d, label;
    if (S.mode === 'live') { d = new Date(Date.parse(w.last + 'T00:00:00Z')); label = 'Latest complete day, ' + fMD(d); }
    else { d = dDate(S.doy, S.year); label = fMD(d) + ', ' + S.year; }
    const y0 = d.getUTCFullYear(), doy0 = Math.round((d - Date.UTC(y0, 0, 1)) / 864e5), i0 = wxIdx(w, y0, doy0);
    if (i0 < 0 || i0 >= w.d.rh_mean.length) { body.appendChild(h('p', 'zp-note', 'No weather data for this date.')); return; }
    const dry = S.mode === 'live' ? dryNote(w) : null;
    if (dry) {
      sum.textContent = 'All weather measures, compared with usual (unusually dry)';
      body.appendChild(h('p', 'zp-dry', 'Heads-up: ' + dry.join(', ') + ' are all well below the usual range for this date. The score is driven mostly by soil temperature and recent rain events, so weigh these numbers before trusting a high score.'));
    }
    body.appendChild(h('p', 'zp-note', label));
    const grid = h('div', 'zp-tiles wide');
    WXTILES.forEach((t) => {
      const raw = wxAt(w, t[1], i0, t[5]);
      if (raw === null) return;
      const v = raw * t[4];
      const o = usualRange(w, t[1], doy0, y0, t[5], t[4]);
      const tile = h('div', 'zp-tile');
      tile.appendChild(h('span', 'zp-tl', t[0]));
      tile.appendChild(h('b', null, v.toFixed(t[3]) + t[2]));
      if (o.length > 30) {
        const below = o.filter((x) => x < v).length / o.length;
        const tag = below >= 0.8 ? 'high for the date' : below <= 0.2 ? 'low for the date' : 'typical';
        tile.appendChild(h('span', 'zp-os' + (tag === 'typical' ? '' : ' flag'), tag + ' (usual ' + d3.quantile(o, 0.25).toFixed(t[3]) + ' to ' + d3.quantile(o, 0.75).toFixed(t[3]) + ')'));
      }
      grid.appendChild(tile);
    });
    body.appendChild(grid);
    body.appendChild(h('p', 'zp-note', 'Daily values for this zone center from the ERA5-Land reanalysis, newest days from the forecast model. Usual = middle half of the same dates in other years since 2016.'));
    const dl = h('button', 'btn sm alt', 'Download daily weather (CSV)');
    dl.type = 'button';
    dl.addEventListener('click', () => downloadCsv(z, w));
    body.appendChild(dl);
  };
  if (wxCache[z.id]) fill(wxCache[z.id]);
  else { body.appendChild(h('p', 'zp-note', 'Loading weather...')); loadWxZone(z.id).then((w) => { if (S.zone === z.id) fill(w); }); }
}

/* ---------- zone panel ---------- */
function miniOdds(box, rows, M) {
  const w = Math.max(240, box.clientWidth || 320), hh = 92;
  const s = d3.select(box).append('svg').attr('width', '100%').attr('viewBox', '0 0 ' + w + ' ' + hh);
  const act = rows.filter((r) => r.p_hi > 0.02);
  const w0 = act.length ? Math.max(0, d3.min(act, (r) => r.week) - 3) : 1, w1 = act.length ? Math.min(53, d3.max(act, (r) => r.week) + 2) : 53;
  const x = d3.scaleLinear().domain([w0, w1]).range([4, w - 4]);
  const y = d3.scaleLinear().domain([0, 1]).range([hh - 18, 6]);
  const sub = rows.filter((r) => r.week >= w0 && r.week <= w1);
  const fam = FAM[rows[0].family].color;
  s.append('path').attr('fill', fam).attr('opacity', 0.16)
    .attr('d', d3.area().defined((r) => r.mean_score !== null).x((r) => x(r.week)).y0((r) => y(r.p_lo)).y1((r) => y(r.p_hi))(sub));
  s.append('path').attr('fill', 'none').attr('stroke', fam).attr('stroke-width', 2).attr('stroke-linejoin', 'round')
    .attr('d', d3.line().x((r) => x(r.week)).y((r) => y(r.p_prime))(sub));
  const tw = Math.floor((M.todayDoy - 1) / 7) + 1;
  if (tw >= w0 && tw <= w1) {
    s.append('line').attr('class', 'today').attr('x1', x(tw)).attr('x2', x(tw)).attr('y1', 4).attr('y2', hh - 16);
    s.append('text').attr('class', 'ax').attr('x', x(tw) + 3).attr('y', 12).text('Today');
  }
  MONTH_DOY.forEach((d) => {
    const wk = Math.floor((d - 1) / 7) + 1;
    if (wk > w0 && wk < w1) s.append('text').attr('class', 'ax').attr('x', x(wk)).attr('y', hh - 4).text(fMon(dDate(d)));
  });
  s.append('line').attr('class', 'axis').attr('x1', 4).attr('x2', w - 4).attr('y1', hh - 18).attr('y2', hh - 18);
}
dash.draw('zpanel', (el) => {
  const M = model();
  el.replaceChildren();
  if (!M || !S.zone) return;
  const z = M.zById[S.zone];
  const sp = z.spKeys.indexOf(S.zsp) >= 0 ? S.zsp : z.spKeys[0];
  const key = z.id + '|' + sp;
  const fam = famOf(sp);
  el.appendChild(h('div', 'zp-grab'));
  const top = h('div', 'zp-top');
  const tt = h('div', 'zp-tt');
  tt.appendChild(h('h3', 'zp-name', z.short));
  tt.appendChild(h('p', 'zp-sub', (z.sub ? z.sub + ' - ' : '') + fInt(z.elev_ft) + ' ft - ' + z.land));
  top.appendChild(tt);
  const close = h('button', 'icon-btn', 'x');
  close.type = 'button';
  close.setAttribute('aria-label', 'Close zone details');
  close.addEventListener('click', clearZone);
  top.appendChild(close);
  el.appendChild(top);

  const tabs = h('div', 'zp-tabs');
  z.spKeys.forEach((k) => {
    const r = z.rows.filter((x) => x.species === k)[0];
    const b = h('button', 'chip sm' + (k === sp ? ' is-on' : ''));
    b.type = 'button';
    b.appendChild(h('i', 'chip-dot')).style.background = FAM[famOf(k)].color;
    b.appendChild(document.createTextNode(FAM[famOf(k)].short + (r && r.score !== null ? ' ' + r.score : '')));
    b.addEventListener('click', () => { S.zsp = k; redraw(['zpanel']); });
    tabs.appendChild(b);
  });
  el.appendChild(tabs);

  const row = z.rows.filter((r) => r.species === sp)[0];
  const hv = M.hist.get(key);
  const nowScore = S.mode === 'live' ? (row ? row.score : null) : (hv && hv.get(S.year) ? hv.get(S.year)[S.doy - 1] : null);
  const sc = h('div', 'zp-score');
  const num = h('div', 'zp-num', nowScore === null || nowScore === undefined ? '-' : String(nowScore));
  if (nowScore !== null && nowScore !== undefined) num.style.color = scoreColor(nowScore);
  sc.appendChild(num);
  const sd = h('div', 'zp-sd');
  if (nowScore === null || nowScore === undefined) {
    sd.appendChild(h('b', null, S.mode === 'live' ? 'Off-season' : 'No score on this date'));
    const sw = firstRow('season_windows', key);
    sd.appendChild(h('span', 'muted', sw ? 'Usually starts around ' + doyStr(sw.start_med) + '.' : 'Outside the modeled window.'));
  } else {
    sd.appendChild(h('b', null, BANDS[bandIdx(nowScore)].name));
    let nv = S.mode === 'live' ? firstRow('now_vs_typical', key) : null;
    if (nv && nv.years < 5) nv = null;
    if (S.mode === 'live' && row) sd.appendChild(h('span', 'muted', cap(row.confidence || '') + ' confidence'));
    if (nv) {
      const pc = Math.round(nv.percentile * 100);
      sd.appendChild(h('span', 'zp-vs', 'Scores higher than ' + pc + '% of past years on this date (typical ' + nv.typical_median + ').'));
    }
    if (S.mode !== 'live') sd.appendChild(h('span', 'muted', 'Modeled on ' + doyStr(S.doy, S.year) + ', ' + S.year + '.'));
  }
  sc.appendChild(sd);
  el.appendChild(sc);

  if (S.mode === 'live' && row && (row.reasons || row.negatives)) {
    const ul = h('ul', 'zp-why');
    row.reasons.split(' | ').filter(Boolean).forEach((t) => ul.appendChild(h('li', 'pos', t)));
    row.negatives.split(' | ').filter(Boolean).forEach((t) => ul.appendChild(h('li', 'neg', t)));
    el.appendChild(ul);
  }

  const fcw = S.mode === 'live' && row ? fcWeek(row) : null;
  if (fcw) {
    const fs = h('div', 'zp-sec');
    fs.appendChild(h('h4', null, 'Next 7 days (forecast)'));
    const best = fcw.reduce((a, d) => (d.v !== null && (a === null || d.v > a.v) ? d : a), null);
    const bars = h('div', 'zp-fc');
    fcw.forEach((d, i) => {
      const c = h('div', 'zp-fcd' + (best && d === best ? ' best' : ''));
      c.appendChild(h('b', null, d.v === null ? '-' : String(d.v)));
      const bar = h('i');
      bar.style.height = (d.v === null ? 2 : Math.max(3, Math.round(d.v * 0.42))) + 'px';
      bar.style.background = d.v === null ? 'var(--sh-line)' : scoreColor(d.v);
      c.appendChild(bar);
      c.appendChild(h('span', null, i === 0 ? 'Today' : fDow(d.t)));
      c.title = fMD(d.t) + (d.v === null ? ': out of season' : ': ' + d.v + ' (' + BANDS[bandIdx(d.v)].name.toLowerCase() + ')');
      bars.appendChild(c);
    });
    fs.appendChild(bars);
    fs.appendChild(h('p', 'zp-note', best && best.v >= 60 ? 'Best day: ' + fDow(best.t) + ' ' + fMD(best.t) + ' (' + best.v + ').' : 'No day this week reaches prime (60) at this zone.'));
    fs.appendChild(h('p', 'zp-note', 'Same model as today\'s score, run on the weather forecast for soil temperature, rain and frost. Forecasts change daily: check again before you drive.'));
    el.appendChild(fs);
  }

  if (S.mode === 'live' && row && row.d7_med !== null && row.d7_med !== undefined) {
    const so = h('div', 'zp-sec');
    so.appendChild(h('h4', null, 'Next two weeks (from history)'));
    const tiles = h('div', 'zp-out');
    [7, 14].forEach((hz) => {
      const med = row['d' + hz + '_med'];
      if (med === null || med === undefined) return;
      const t = h('div', 'zp-ot');
      t.appendChild(h('span', 'zp-tl', 'In ' + hz + ' days'));
      const n = h('b', 'zp-on', String(med));
      n.style.color = scoreColor(med);
      t.appendChild(n);
      t.appendChild(h('span', 'zp-os', 'middle half ' + row['d' + hz + '_p25'] + ' to ' + row['d' + hz + '_p75']));
      t.appendChild(h('span', 'zp-os', row['d' + hz + '_p60'] + '% of similar days were prime'));
      tiles.appendChild(t);
    });
    so.appendChild(tiles);
    so.appendChild(h('p', 'zp-note', 'Based on ' + row.d7_n + ' similar days over ' + row.d7_years + ' seasons. A history-based outlook, not a weather forecast.'));
    el.appendChild(so);
  }

  const sec1 = h('div', 'zp-sec');
  sec1.appendChild(h('h4', null, 'Season odds'));
  const oddsRows = calcRows('prime_by_week') ? (bySeries(calcRows('prime_by_week')).get(key) || null) : null;
  if (oddsRows) {
    const box = h('div', 'zp-mini');
    sec1.appendChild(box);
    el.appendChild(sec1);
    miniOdds(box, oddsRows, M);
    const sw = firstRow('season_windows', key);
    if (sw) sec1.appendChild(h('p', 'zp-note', 'Usually prime ' + doyStr(sw.start_med) + ' to ' + doyStr(sw.end_med) + ' (earliest ' + doyStr(sw.start_min) + ', latest ' + doyStr(sw.end_max) + '). Prime in ' + sw.years_prime + ' of ' + sw.years_total + ' years.'));
  } else {
    sec1.appendChild(h('p', 'zp-note', 'History is still being built for this zone.'));
    el.appendChild(sec1);
  }
  if (SIGHT_KEY[sp] === 'morel_natural') sec1.appendChild(h('p', 'zp-note', 'Morel scores cover forest morels at foothill and mountain elevations. More than half of public morel reports come from valley floors below about 1,000 ft (parks, yards, orchards), which this score does not cover.'));

  const w = z.w;
  const sec2 = h('div', 'zp-sec');
  sec2.appendChild(h('h4', null, 'Conditions'));
  if (w) {
    const grid = h('div', 'zp-tiles');
    [['Soil temp', w.soil_t_f.toFixed(0) + ' F'], ['Soil moisture', w.soil_m_pct.toFixed(0) + '%'], ['Rain, 14 days', w.rain14_in.toFixed(1) + ' in'], ['Air high', w.tmax_f.toFixed(0) + ' F']].forEach((p) => {
      const t = h('div', 'zp-tile');
      t.appendChild(h('span', 'zp-tl', p[0]));
      t.appendChild(h('b', null, p[1]));
      grid.appendChild(t);
    });
    sec2.appendChild(grid);
    sec2.appendChild(h('p', 'zp-note', 'Weather as of ' + fMD(new Date(w.asof + 'T00:00:00Z')) + ' (reanalysis).' + (row && row.rain_10d_in !== null ? ' Next 10 days: ' + row.rain_10d_in.toFixed(1) + ' in of rain, highs ' + Math.round(row.hi_low_f) + ' to ' + Math.round(row.hi_high_f) + ' F.' : '') + (row && row.rain_era5_through ? ' The score uses ERA5 reanalysis rain through ' + fMD(new Date(row.rain_era5_through + 'T00:00:00Z')) + ' (the same source as the history) and forecast-service rain for the days after.' : '')));
  }
  el.appendChild(sec2);
  moreMeasures(el, z);

  nearbyFinds(el, z, sp);
  habitatSection(el, z, sp);

  const sec3 = h('div', 'zp-sec');
  sec3.appendChild(h('h4', null, 'Access and habitat'));
  sec3.appendChild(h('p', 'zp-note', cap(z.habitat) + '.'));
  const dist = z.pdx_drive_h ? '~' + hours(z.pdx_drive_h) + ' drive from Portland' : fInt(Math.round(z.pdx_km * 0.621)) + ' miles from Portland (straight line)';
  sec3.appendChild(h('p', 'zp-note', dist + '.'));
  const det = h('details', 'zp-permit');
  det.appendChild(h('summary', null, z.permit_verify ? 'Permit rules (verify before you go)' : 'Permit rules'));
  det.appendChild(h('p', null, z.permit));
  sec3.appendChild(det);
  el.appendChild(sec3);

  if (M.fullSeries.indexOf(key) >= 0) {
    const go = h('button', 'btn', 'Season stats for ' + FAM[fam].short.toLowerCase());
    go.type = 'button';
    go.addEventListener('click', () => openStats(key));
    el.appendChild(go);
  }
});

/* ---------- stats: KPIs ---------- */
dash.draw('kpi', (el) => {
  const d = dash.data('kpis');
  if (d.status !== 'ok' || !d.data || !d.data.length) { el.textContent = '-'; return; }
  const v = d.data[0][el.dataset.field];
  const f = el.dataset.fmt;
  el.textContent = v === null || v === undefined ? '-' : f === 'md' ? doyStr(v) : f === 'int' ? fInt(v) : String(v);
});

/* ---------- stats: season windows ---------- */
dash.draw('seasons', (el) => {
  const M = model();
  const sw = calcRows('season_windows');
  if (!M || !sw) { placeholder(el); return; }
  let rows = sw.slice();
  const most = d3.max(sw, (r) => r.years_total);
  if (S.fam !== 'all') rows = rows.filter((r) => r.family === S.fam);
  if (!S.showAll) rows = rows.filter((r) => r.years_total >= most);
  rows.sort((a, b) => a.start_med - b.start_med || a.peak_med - b.peak_med);
  if (!rows.length) { placeholder(el, 'No seasons for this mushroom yet.'); return; }
  const narrow = (el.clientWidth || 600) < 560;
  const rowH = narrow ? 40 : 24, top = 24;
  const H = top + rows.length * rowH + 8;
  const { s, w } = svgIn(el, H);
  const tip = makeTip(el);
  const lbl = (r) => r.zone_name + ' - ' + FAM[r.family].short + (r.years_total < most ? ' *' : '');
  const ml = narrow ? 8 : Math.min(measure(s, rows.map(lbl)) + 14, w * 0.44);
  const d0 = Math.max(1, d3.min(rows, (r) => r.start_min) - 10), d1 = Math.min(366, d3.max(rows, (r) => r.end_max) + 10);
  const x = d3.scaleLinear().domain([d0, d1]).range([ml, w - 10]);
  monthAxis(s.append('g'), x, top - 4, H - 6, d0, d1, H, 14);
  rows.forEach((r, i) => {
    const gy = top + i * rowH;
    const g = s.append('g').attr('transform', 'translate(0,' + gy + ')').attr('class', 'srow' + (r.series === S.series ? ' sel' : '')).style('cursor', 'pointer');
    g.append('rect').attr('class', 'hit').attr('x', 0).attr('y', 0).attr('width', w).attr('height', rowH);
    const by = narrow ? rowH - 14 : rowH / 2;
    if (narrow) g.append('text').attr('class', 'lab').attr('x', 6).attr('y', 14).text(lbl(r));
    else g.append('text').attr('class', 'lab').attr('x', ml - 8).attr('y', rowH / 2 + 4).attr('text-anchor', 'end').text(lbl(r));
    const col = FAM[r.family].color;
    g.append('rect').attr('x', x(r.start_min)).attr('y', by - 1).attr('width', Math.max(2, x(r.end_max) - x(r.start_min))).attr('height', 2).attr('fill', col).attr('opacity', 0.5);
    g.append('rect').attr('x', x(r.start_med)).attr('y', by - 5).attr('width', Math.max(4, x(r.end_med) - x(r.start_med))).attr('height', 10).attr('rx', 5).attr('fill', col);
    g.append('circle').attr('cx', x(r.peak_med)).attr('cy', by).attr('r', 2.6).attr('class', 'dot');
    g.on('mousemove', (ev) => tip.show(ev, [
      { t: r.zone_name + ' - ' + r.species_name, cls: 'tip-t' },
      { sw: col, t: 'Prime ' + doyStr(r.start_med) + ' to ' + doyStr(r.end_med) },
      { t: 'Earliest start ' + doyStr(r.start_min) + ', latest end ' + doyStr(r.end_max), cls: 'tip-m' },
      { t: 'Typical best day ' + doyStr(r.peak_med), cls: 'tip-m' },
      { t: 'Reached prime in ' + r.years_prime + ' of ' + r.years_total + ' years', cls: 'tip-m' }
    ])).on('mouseleave', () => tip.hide()).on('click', () => selectSeries(r.series, true));
  });
});

/* ---------- stats: scores against real reports ---------- */
let REAL = null;
let realReq = null;
function loadReal() {
  if (realReq) return realReq;
  realReq = fetch('data/c/reality.json').then((r) => (r.ok ? r.json() : null)).then((d) => {
    REAL = d || { missing: true };
    redraw(['reality']);
    return REAL;
  }).catch(() => { REAL = { missing: true }; return REAL; });
  return realReq;
}
const RC_VERDICT = {
  king_fall: 'The clearest match',
  chanterelle: 'Weak match',
  king_spring: 'Too few reports to tell',
  morel: 'No match shown (score covers forest morels only)'
};
function rcBars(label, vals, color, fmt, note) {
  const wrap = h('div', 'rc-row');
  wrap.appendChild(h('span', 'rc-rl', label));
  const bars = h('div', 'rc-bars');
  const mx = Math.max.apply(null, vals.concat([1e-9]));
  vals.forEach((v, i) => {
    const c = h('div', 'rc-b');
    const f = h('i');
    f.style.height = Math.max(v > 0 ? 2 : 0, Math.round(v / mx * 56)) + 'px';
    f.style.background = color;
    c.appendChild(f);
    c.title = fmt(v, i);
    bars.appendChild(c);
  });
  wrap.appendChild(bars);
  if (note) wrap.appendChild(h('span', 'rc-rn', note));
  return wrap;
}
/* Measured soil temperature (SNOTEL and AgriMet) by station, weekly means next to the model's matching layer. */
let SENS = null;
let sensReq = null;
function loadSens() {
  if (sensReq) return sensReq;
  sensReq = fetch('data/c/sensors.json').then((r) => (r.ok ? r.json() : null)).then((d) => {
    SENS = d || { stations: [] };
    redraw(['reality']);
    return SENS;
  }).catch(() => { SENS = { stations: [] }; return SENS; });
  return sensReq;
}
function sensChart(host) {
  if (!SENS) { loadSens(); host.appendChild(h('p', 'zp-note', 'Loading sensor data...')); return; }
  if (!SENS.stations.length) return;
  if (!S.sens || !SENS.stations.some((x) => x.id === S.sens)) S.sens = (SENS.stations.filter((x) => x.model && x.net === 'SNOTEL')[0] || SENS.stations[0]).id;
  const st = SENS.stations.filter((x) => x.id === S.sens)[0];
  if (!S.sdepth || !st['depth_' + S.sdepth]) S.sdepth = st.depth_a ? 'a' : 'b';
  const dep = S.sdepth;
  const box = h('div', 'rc-sens');
  const ctl = h('div', 'rc-sctl');
  const sel = h('select', 'dash-select');
  sel.setAttribute('aria-label', 'Sensor station');
  [['Forest clearings (SNOTEL), by elevation', 'SNOTEL'], ['Valley, coast and east-side fields (AgriMet)', 'AgriMet']].forEach((g) => {
    const og = document.createElement('optgroup');
    og.label = g[0];
    SENS.stations.filter((x) => x.net === g[1]).forEach((x) => { og.appendChild(new Option(x.name + ' (' + fInt(x.elev_ft) + ' ft)', x.id)); });
    sel.appendChild(og);
  });
  sel.value = st.id;
  sel.addEventListener('change', () => { S.sens = sel.value; redraw(['reality']); });
  ctl.appendChild(sel);
  ['a', 'b'].forEach((d) => {
    if (!st['depth_' + d]) return;
    const b = h('button', 'chip sm' + (d === dep ? ' is-on' : ''), st['depth_' + d] + ' deep');
    b.type = 'button';
    b.addEventListener('click', () => { S.sdepth = d; redraw(['reality']); });
    ctl.appendChild(b);
  });
  box.appendChild(ctl);
  const yrCol = { 2022: '#6b8fd6', 2023: '#59a96a', 2024: '#d9a441', 2025: '#c26b6b' };
  const leg = h('div', 'rc-leg');
  SENS.years.forEach((y) => { const l = h('span'); l.appendChild(h('i')).style.background = yrCol[y]; l.appendChild(document.createTextNode(String(y))); leg.appendChild(l); });
  const l1 = h('span'); l1.appendChild(h('i', 'thick')); l1.appendChild(document.createTextNode('Sensor average')); leg.appendChild(l1);
  if (st.model) { const l2 = h('span'); l2.appendChild(h('i', 'dash')); l2.appendChild(document.createTextNode('Model average (same weeks)')); leg.appendChild(l2); }
  box.appendChild(leg);
  host.appendChild(box);
  const wrap = h('div', 'chart');
  box.appendChild(wrap);
  const H = 230, mt = 14, mb = 22;
  const { s, w } = svgIn(wrap, H);
  const tip = makeTip(wrap);
  const sens = st.sensor[dep];
  const mod = st.model ? st.model[dep] : null;
  /* averages use only the years in which the sensor has a reading that week, for both lines, so they stay comparable */
  const pairAvg = (obj, i) => { const v = SENS.years.filter((yr) => sens[String(yr)][i] !== null && sens[String(yr)][i] !== undefined).map((yr) => obj[String(yr)][i]).filter((q) => q !== null && q !== undefined); return v.length ? d3.mean(v) : null; };
  const sAvg = d3.range(53).map((i) => pairAvg(sens, i)), mAvg = mod ? d3.range(53).map((i) => (sAvg[i] === null ? null : pairAvg(mod, i))) : null;
  const all = [];
  SENS.years.forEach((y) => { sens[String(y)].forEach((v) => { if (v !== null) all.push(v); }); });
  if (mAvg) mAvg.forEach((v) => { if (v !== null) all.push(v); });
  const win = SENS.windows[S.rc || 'chanterelle'];
  const y = d3.scaleLinear().domain([Math.min(30, d3.min(all) - 2), Math.max(win[3] + 2, d3.max(all) + 2)]).nice().range([H - mb, mt]);
  const ticks = y.ticks(5);
  const ml = measure(s, ticks.map(String)) + 14;
  const x = d3.scaleLinear().domain([0, 52]).range([ml, w - 8]);
  ticks.forEach((tk) => {
    s.append('line').attr('class', 'grid').attr('x1', ml).attr('x2', w - 8).attr('y1', y(tk)).attr('y2', y(tk));
    s.append('text').attr('class', 'ax').attr('x', ml - 6).attr('y', y(tk) + 3).attr('text-anchor', 'end').text(tk);
  });
  s.append('rect').attr('x', ml).attr('width', w - 8 - ml).attr('y', y(win[2])).attr('height', Math.max(0, y(win[1]) - y(win[2]))).attr('fill', FAM[S.rc || 'chanterelle'].color).attr('opacity', 0.14);
  s.append('text').attr('class', 'ax').attr('x', w - 10).attr('y', y(win[2]) + 11).attr('text-anchor', 'end').text(FAM[S.rc || 'chanterelle'].short + ' best soil range ' + win[1] + ' to ' + win[2] + ' F');
  MONTH_DOY.forEach((d) => { s.append('text').attr('class', 'ax').attr('x', x(Math.floor((d - 1) / 7))).attr('y', H - 6).text(fMon(dDate(d))); });
  const line = d3.line().defined((d) => d[1] !== null && d[1] !== undefined).x((d) => x(d[0])).y((d) => y(d[1]));
  SENS.years.forEach((yr) => {
    s.append('path').attr('d', line(sens[String(yr)].map((v, i) => [i, v]))).attr('fill', 'none').attr('stroke', yrCol[yr]).attr('stroke-width', 1.1).attr('opacity', 0.75);
  });
  s.append('path').attr('d', line(sAvg.map((v, i) => [i, v]))).attr('fill', 'none').attr('stroke', 'var(--color-fg)').attr('stroke-width', 2.4);
  if (mAvg) s.append('path').attr('d', line(mAvg.map((v, i) => [i, v]))).attr('fill', 'none').attr('stroke', 'var(--color-fg)').attr('stroke-width', 1.8).attr('stroke-dasharray', '5 4').attr('opacity', 0.85);
  const hit = s.append('rect').attr('x', ml).attr('y', 0).attr('width', w - 8 - ml).attr('height', H).attr('fill', 'transparent');
  hit.on('mousemove', (ev) => {
    const i = clamp(Math.round(x.invert(d3.pointer(ev, s.node())[0])), 0, 52);
    const lines = [{ t: doyStr(i * 7 + 1) + ' (week ' + (i + 1) + ')', cls: 'tip-t' }];
    SENS.years.forEach((yr) => { const v = sens[String(yr)][i]; if (v !== null) lines.push({ sw: yrCol[yr], t: yr + ': ' + v.toFixed(1) + ' F measured', cls: 'tip-m' }); });
    if (mAvg && mAvg[i] !== null) lines.push({ t: 'Model ' + mAvg[i].toFixed(1) + ' F' + (sAvg[i] !== null ? ' (' + (mAvg[i] - sAvg[i] > 0 ? '+' : '') + (mAvg[i] - sAvg[i]).toFixed(1) + ' vs sensor)' : ''), cls: 'tip-l' });
    tip.show(ev, lines);
  }).on('mouseleave', () => tip.hide());
  const gw = mAvg ? d3.range(53).filter((i) => sAvg[i] !== null && mAvg[i] !== null && sAvg[i] > 36) : [];
  const gap = gw.length >= 8 ? d3.mean(gw.map((i) => mAvg[i] - sAvg[i])) : null;
  box.appendChild(h('p', 'zp-note', st.name + ' (' + st.net + ', ' + st.kind + ', ' + fInt(st.elev_ft) + ' ft): measured at ' + st['depth_' + dep] + ' deep' + (mAvg ? ', model layer ' + (dep === 'a' ? '0 to 7 cm' : '7 to 28 cm') + (gap !== null ? '; on average the model is ' + Math.abs(gap).toFixed(1) + ' F ' + (gap < 0 ? 'colder' : 'warmer') + ' than the sensor over snow-free weeks' : '') : '; no model comparison for this station') + '. Weekly means, 2022 to 2025. Only years with a reading are averaged.' + (st.net === 'SNOTEL' ? ' Midnight readings; flat lines near 32 F are soil under snow.' : ' Sensors sit in open, often irrigated fields.') + ' Shaded band: the soil range the scores treat as best for the selected mushroom (' + FAM[S.rc || 'chanterelle'].short + ', set by the tabs above).'));
}
dash.draw('reality', (el) => {
  const M = model();
  el.replaceChildren();
  if (!M) { placeholder(el); return; }
  if (!REAL) { loadReal(); el.appendChild(h('p', 'muted pad', 'Loading...')); return; }
  if (REAL.missing) { el.appendChild(h('p', 'muted pad', 'This section needs data that is not available right now.')); return; }
  if (!SIGHT) { loadSightings(); el.appendChild(h('p', 'muted pad', 'Loading reports...')); return; }
  if (!HAB) loadHab();
  if (!S.rc) S.rc = 'chanterelle';
  const fam = S.rc, key = SIGHT_KEY[fam], col = FAM[fam].color, nm = FAM[fam].short;

  const tabs = h('div', 'rc-tabs');
  FAMS.forEach((f) => {
    const b = h('button', 'chip sm' + (f === fam ? ' is-on' : ''));
    b.type = 'button';
    b.appendChild(h('i', 'chip-dot')).style.background = FAM[f].color;
    b.appendChild(document.createTextNode(FAM[f].short));
    b.addEventListener('click', () => { S.rc = f; redraw(['reality']); });
    tabs.appendChild(b);
  });
  el.appendChild(tabs);

  const rows = SIGHT.rows.filter((r) => r.sp === key);
  const years = rows.map((r) => r.y);
  const open = rows.filter((r) => OPEN_LAND[r.land]).length;
  const kp = h('div', 'rc-kpis');
  [[fInt(rows.length), 'public reports of ' + nm.toLowerCase() + 's', Math.min.apply(null, years) + ' to ' + Math.max.apply(null, years)],
   [fPct(open / Math.max(1, rows.length)), 'on land usually open to picking', 'national forest, BLM, state'],
   [fPct(rows.filter((r) => r.land === 'p').length / Math.max(1, rows.length)), 'on private or unmapped land', 'about where people photograph, not pick']].forEach((k) => {
    const d = h('div', 'rc-kpi');
    d.appendChild(h('b', null, k[0]));
    d.appendChild(h('span', null, k[1]));
    d.appendChild(h('small', 'muted', k[2]));
    kp.appendChild(d);
  });
  el.appendChild(kp);

  /* 1. timing: reports by week vs zones typically in prime */
  const sec1 = h('div', 'rc-sec');
  sec1.appendChild(h('h3', null, 'Does the timing line up?'));
  const wk = d3.range(53).map(() => 0);
  rows.forEach((r) => { wk[Math.min(52, Math.floor((r.doy - 1) / 7))]++; });
  const wb = calcRows('weekly_busy');
  const model53 = d3.range(53).map(() => 0);
  (wb || []).filter((r) => r.family === fam).forEach((r) => { model53[r.week - 1] = r.avg_zones; });
  const mxw = Math.max.apply(null, wk.concat([1])), mxm = Math.max.apply(null, model53.concat([1e-9]));
  const chart = h('div', 'rc-timing');
  wk.forEach((v, i) => {
    const c = h('div', 'rc-tc');
    const bar = h('i');
    bar.style.height = Math.max(v > 0 ? 2 : 0, Math.round(v / mxw * 64)) + 'px';
    bar.style.background = col;
    c.appendChild(bar);
    const dot = h('b');
    dot.style.bottom = Math.round(model53[i] / mxm * 64) + 'px';
    c.appendChild(dot);
    c.title = doyStr(i * 7 + 1) + ': ' + v + ' reports; model typically has ' + model53[i].toFixed(1) + ' zones in prime';
    chart.appendChild(c);
  });
  sec1.appendChild(chart);
  const ax = h('div', 'rc-ax');
  MONTH_DOY.forEach((d) => { const s = h('span', null, fMon(dDate(d))); s.style.left = ((Math.floor((d - 1) / 7)) / 53 * 100) + '%'; ax.appendChild(s); });
  sec1.appendChild(ax);
  const half = (a, mx) => a.findIndex((x) => x >= 0.5 * mx);
  const inSeason = wk.reduce((a, v, i) => a + (model53[i] >= 0.25 * mxm ? v : 0), 0);
  sec1.appendChild(h('p', 'zp-note', 'Bars: reports per week of the year, all years. Dots: how many zones are typically in prime that week. Each is scaled to its own peak, so this compares timing, not height. Reports climb past half their peak in the week of ' + doyStr(half(wk, mxw) * 7 + 1) + ' and the model passes half its peak in the week of ' + doyStr(half(model53, mxm) * 7 + 1) + '. ' + fPct(inSeason / Math.max(1, rows.length)) + ' of reports fall in weeks where the model has at least a quarter of its peak number of zones in prime.'));
  el.appendChild(sec1);

  /* 2. how well the scores match reports */
  const v = REAL.validation[fam];
  const sec2 = h('div', 'rc-sec');
  sec2.appendChild(h('h3', null, 'Do high scores match more reports?'));
  const vt = h('div', 'rc-val');
  vt.appendChild(h('b', null, RC_VERDICT[fam]));
  vt.appendChild(h('span', null, v.rr === null ? 'Too few reports for a ratio.' : 'On days when other mushrooms were being reported nearby, ' + nm.toLowerCase() + 's were reported ' + v.rr.toFixed(1) + ' times as often on prime days (60+) as on low-score days (95% range ' + v.rr_ci[0].toFixed(1) + ' to ' + v.rr_ci[1].toFixed(1) + '; 1.0 means no difference).'));
  vt.appendChild(h('span', 'muted', v.find_days + ' report-days in ' + v.zones + ' zones. Does this year beat other years on the same date? ' + (v.yswap >= 55 && v.yswap_ci[0] > 50 ? 'Yes.' : 'No evidence (' + v.yswap.toFixed(0) + ' on a scale where 50 means none).')));
  sec2.appendChild(vt);
  sec2.appendChild(h('p', 'zp-note', 'Counted only on days when other mushrooms were reported nearby, so days with more people out looking do not look better by themselves. See the sources page for the method and limits.'));
  el.appendChild(sec2);

  /* 3. where reports happen vs where the zones are */
  const sec3 = h('div', 'rc-sec');
  sec3.appendChild(h('h3', null, 'Where reports come from, by elevation'));
  el.appendChild(sec3);
  const bins = REAL.find_elevation.bins_ft, hist = REAL.find_elevation.hist[fam];
  const totR = Math.max(1, hist.reduce((a, b) => a + b, 0));
  const zc = bins.map(() => 0);
  let nz = 0;
  M.zones.forEach((z) => { if (z.spKeys.some((k) => famOf(k) === fam)) { zc[Math.min(bins.length - 1, Math.floor(z.elev_ft / 500))]++; nz++; } });
  const lab = (i) => (i === bins.length - 1 ? '8,000+ ft' : fInt(bins[i]) + ' to ' + fInt(bins[i] + 500) + ' ft');
  const low = hist.slice(0, 2).reduce((a, b) => a + b, 0) / totR;
  const ewrap = h('div', 'chart');
  sec3.appendChild(ewrap);
  const EH = 244, et = 16, eb = 22, mid = 100;
  const { s: es, w: ew } = svgIn(ewrap, EH);
  const rep = hist.map((x) => x / totR * 100), zon = zc.map((x) => x / Math.max(1, nz) * 100);
  const ymax = Math.max(10, Math.ceil(Math.max.apply(null, rep.concat(zon)) / 10) * 10);
  const yh = d3.scaleLinear().domain([0, ymax]).range([0, mid - et - 6]);
  const eml = measure(es, [ymax + '%']) + 14;
  const ex = d3.scaleBand().domain(d3.range(bins.length)).range([eml, ew - 8]).paddingInner(0.12);
  [['Reports (share of reports)', rep, col, et + 4, mid - 2], ['Zones (share of zones)', zon, '#8b93a1', mid + 36, EH - eb]].forEach((p) => {
    const base = p[4];
    es.append('text').attr('class', 'ax strong').attr('x', eml).attr('y', p[3] - 8).text(p[0]);
    [0, ymax / 2, ymax].forEach((tk) => {
      es.append('line').attr('class', tk === 0 ? 'axis' : 'grid').attr('x1', eml).attr('x2', ew - 8).attr('y1', base - yh(tk)).attr('y2', base - yh(tk));
      es.append('text').attr('class', 'ax').attr('x', eml - 6).attr('y', base - yh(tk) + 3).attr('text-anchor', 'end').text(tk + '%');
    });
    p[1].forEach((v, k) => {
      const r = es.append('rect').attr('x', ex(k)).attr('width', ex.bandwidth()).attr('y', base - yh(v)).attr('height', Math.max(v > 0 ? 1.5 : 0, yh(v))).attr('fill', p[2]).attr('rx', 1.5);
      r.append('title').text(lab(k) + ': ' + v.toFixed(0) + '%');
    });
  });
  [0, 4, 8, 12, 16].forEach((k) => {
    es.append('text').attr('class', 'ax').attr('x', ex(k)).attr('y', EH - 6).text(k === 16 ? '8,000+ ft' : fInt(bins[k]) + ' ft');
  });
  sec3.appendChild(h('p', 'zp-note', low >= 0.25
    ? fPct(low) + ' of ' + nm.toLowerCase() + ' reports are below 1,000 ft (mostly valley floors, parks and the coast), where the model has few zones. ' + (fam === 'morel' ? 'The morel score only covers about ' + REAL.morel_band.share_in_band_all + '% of reports by elevation band (' + REAL.morel_band.share_in_band_public_land + '% on national forest and BLM land).' : 'Most zones sit in forest at mid elevations.')
    : 'Reports and zones sit at similar elevations: only ' + fPct(low) + ' of ' + nm.toLowerCase() + ' reports are below 1,000 ft.'));

  /* 4. forest structure */
  if (HAB && HAB.species && HAB.species[key]) {
    const hs = HAB.species[key];
    const sec4 = h('div', 'rc-sec');
    sec4.appendChild(h('h3', null, 'What kind of forest are reports in?'));
    [['In mapped forest', 'forest'], ['In late-development closed forest', 'late'], ['In stands 100 ft (30 m) or taller', 'tall']].forEach((p) => {
      const r = h('div', 'rc-pair');
      r.appendChild(h('span', 'rc-pl', p[0]));
      [['Reports', hs.finds_pct[p[1]], col], ['Surrounding land', hs.background_pct[p[1]], 'var(--sh-muted)']].forEach((q) => {
        const b = h('div', 'rc-hb2');
        b.appendChild(h('span', 'rc-hl', q[0]));
        const tr = h('div', 'rc-ht');
        const i = h('i');
        i.style.width = q[1] + '%'; i.style.background = q[2];
        tr.appendChild(i);
        b.appendChild(tr);
        b.appendChild(h('span', 'rc-hv', q[1] + '%'));
        r.appendChild(b);
      });
      sec4.appendChild(r);
    });
    sec4.appendChild(h('p', 'zp-note', fam === 'morel' ? 'Morel reports are far less tied to forest than the others: many are on open or disturbed ground.' : 'Reports lean toward older, taller forest than the land around our zones, though trails and roads shape where people look. Source: LANDFIRE 2024.'));
    el.appendChild(sec4);
  }

  /* 5. soil temperature check */
  const so = REAL.soil;
  const sec5 = h('div', 'rc-sec');
  el.appendChild(sec5);                                  // attached early: the sensor chart measures its width
  sec5.appendChild(h('h3', null, 'Is the soil-temperature input right?'));
  const mons = [4, 5, 6, 7, 8, 9, 10, 11];
  const bias = mons.map((m) => so.by_month_shallow[m]);
  const bwrap = h('div', 'chart');
  sec5.appendChild(bwrap);
  const BH = 170, bt = 20, bbm = 22;
  const { s: bs, w: bwid } = svgIn(bwrap, BH);
  const byv = d3.scaleLinear().domain([-8, 2]).range([BH - bbm, bt]);
  const bticks = [-8, -6, -4, -2, 0, 2];
  const bml = measure(bs, bticks.map(String)) + 12;
  const bx = d3.scaleBand().domain(mons).range([bml, bwid - 8]).paddingInner(0.28).paddingOuter(0.1);
  bs.append('text').attr('class', 'ax').attr('x', bml).attr('y', 11).text('Model minus sensor, degrees F (below zero = model colder)');
  bticks.forEach((tk) => {
    bs.append('line').attr('class', tk === 0 ? 'axis' : 'grid').attr('x1', bml).attr('x2', bwid - 8).attr('y1', byv(tk)).attr('y2', byv(tk));
    bs.append('text').attr('class', 'ax').attr('x', bml - 6).attr('y', byv(tk) + 3).attr('text-anchor', 'end').text(tk);
  });
  mons.forEach((m, i) => {
    const v = bias[i], x0 = bx(m), mname = fMon(new Date(Date.UTC(2024, m - 1, 1))).slice(0, 3);
    const top = Math.min(byv(0), byv(v)), hgt = Math.max(1.5, Math.abs(byv(v) - byv(0)));
    const r = bs.append('rect').attr('x', x0).attr('width', bx.bandwidth()).attr('y', top).attr('height', hgt).attr('rx', 2).attr('fill', v < 0 ? '#2f6fb3' : '#c0562a');
    r.append('title').text(mname + ': model ' + (v < 0 ? 'colder' : 'warmer') + ' than the sensors by ' + Math.abs(v).toFixed(1) + ' F');
    bs.append('text').attr('class', 'ax strong').attr('x', x0 + bx.bandwidth() / 2).attr('text-anchor', 'middle').attr('y', v < 0 ? byv(v) + 13 : byv(v) - 5).text((v > 0 ? '+' : '') + v.toFixed(1));
    bs.append('text').attr('class', 'ax').attr('x', x0 + bx.bandwidth() / 2).attr('text-anchor', 'middle').attr('y', BH - 6).text(mname);
  });
  sec5.appendChild(h('p', 'zp-note', 'Measured soil temperature at ' + so.snotel.length + ' NRCS SNOTEL stations in forest clearings (420 to 6,020 ft) and ' + so.agrimet.length + ' Bureau of Reclamation AgriMet stations in valleys, on the coast and east of the Cascades, 2022 to 2025, against the weather history the scores are built on (degrees F, blue = model colder). The history tracks day-to-day changes closely but runs 2 to 6 F cold in spring and late fall. Today\'s live and forecast numbers use a different model that is closer (about ' + Math.abs(so.live_model_bias_f).toFixed(1) + ' F cold, ' + so.live_model_window + '). A seasonal correction was tested and did not clearly improve the match with reports, so scores are unchanged.'));
  sec5.appendChild(h('h3', 'rc-h3b', 'The measured soil temperature, station by station (28 SNOTEL and 7 AgriMet stations)'));
  sensChart(sec5);
  const det = h('details', 'rc-det');
  det.appendChild(h('summary', null, 'Average gap by station (table)'));
  const tb = h('table', 'rc-tab');
  const hd = h('tr');
  ['Station', 'Elevation', 'Shallow layer', 'Deeper layer'].forEach((t) => hd.appendChild(h('th', null, t)));
  tb.appendChild(hd);
  so.snotel.forEach((s) => {
    const tr = h('tr');
    [s.name + ' (SNOTEL)', fInt(s.elev_ft) + ' ft', s.bias_shallow === null ? '-' : (s.bias_shallow > 0 ? '+' : '') + s.bias_shallow + ' F', s.bias_deep === null ? '-' : (s.bias_deep > 0 ? '+' : '') + s.bias_deep + ' F'].forEach((t) => tr.appendChild(h('td', null, t)));
    tb.appendChild(tr);
  });
  so.agrimet.forEach((s) => {
    const tr = h('tr');
    [s.name + ' (AgriMet)', 'valley / coast', s.bias_shallow === null ? '-' : (s.bias_shallow > 0 ? '+' : '') + s.bias_shallow + ' F', s.bias_deep === null ? '-' : (s.bias_deep > 0 ? '+' : '') + s.bias_deep + ' F'].forEach((t) => tr.appendChild(h('td', null, t)));
    tb.appendChild(tr);
  });
  det.appendChild(tb);
  sec5.appendChild(det);
});

/* ---------- stats: statewide weekly ---------- */
dash.draw('weekly', (el) => {
  const rows = calcRows('weekly_busy');
  if (!rows) { placeholder(el); return; }
  const weeks = d3.range(1, 54).map((wk) => {
    const o = { week: wk };
    FAMS.forEach((f) => { o[f] = 0; });
    return o;
  });
  rows.forEach((r) => { weeks[r.week - 1][r.family] = r.avg_zones; });
  weeks.forEach((o) => { o.total = FAMS.reduce((a, f) => a + o[f], 0); });
  if (S.week === null) S.week = weeks.reduce((b, o) => (o.total > b.total ? o : b), weeks[0]).week;
  const H = 230, mt = 22, mb = 22;
  const { s, w } = svgIn(el, H);
  const tip = makeTip(el);
  const ymax = d3.max(weeks, (o) => o.total) * 1.12;
  const y = d3.scaleLinear().domain([0, ymax]).nice().range([H - mb, mt]);
  const ticks = y.ticks(4);
  const ml = measure(s, ticks.map(String)) + 12;
  const x = d3.scaleBand().domain(weeks.map((o) => o.week)).range([ml, w - 6]).paddingInner(0.14);
  ticks.forEach((tk) => {
    s.append('line').attr('class', 'grid').attr('x1', ml).attr('x2', w - 6).attr('y1', y(tk)).attr('y2', y(tk));
    s.append('text').attr('class', 'ax').attr('x', ml - 6).attr('y', y(tk) + 3).attr('text-anchor', 'end').text(tk);
  });
  MONTH_DOY.forEach((d) => {
    const wk = Math.floor((d - 1) / 7) + 1;
    s.append('text').attr('class', 'ax').attr('x', x(wk)).attr('y', H - 6).text(fMon(dDate(d)));
  });
  const series = d3.stack().keys(FAMS)(weeks);
  series.forEach((layer) => {
    s.append('g').selectAll('rect').data(layer).join('rect')
      .attr('x', (d) => x(d.data.week)).attr('width', x.bandwidth())
      .attr('y', (d) => y(d[1])).attr('height', (d) => Math.max(0, y(d[0]) - y(d[1])))
      .attr('fill', FAM[layer.key].color).attr('rx', 1.2);
  });
  const selW = weeks[S.week - 1];
  s.append('rect').attr('class', 'selband').attr('x', x(selW.week) - 2).attr('y', mt - 6).attr('width', x.bandwidth() + 4).attr('height', H - mb - mt + 6).attr('rx', 3);
  const peak = weeks.reduce((b, o) => (o.total > b.total ? o : b), weeks[0]);
  const lx = clamp(x(peak.week) + x.bandwidth() / 2, 60, w - 60);
  s.append('text').attr('class', 'ax strong').attr('x', lx).attr('y', y(peak.total) - 6).attr('text-anchor', 'middle').text('Busiest: week of ' + doyStr((peak.week - 1) * 7 + 1));
  const hit = s.append('rect').attr('x', ml).attr('y', 0).attr('width', w - ml).attr('height', H).attr('fill', 'transparent').style('cursor', 'pointer');
  const wkAt = (ev) => clamp(Math.floor((d3.pointer(ev, s.node())[0] - x.range()[0]) / x.step()) + 1, 1, 53);
  hit.on('mousemove', (ev) => {
    const o = weeks[wkAt(ev) - 1];
    const d0 = (o.week - 1) * 7 + 1;
    const lines = [{ t: doyStr(d0) + ' to ' + doyStr(Math.min(366, d0 + 6)), cls: 'tip-t' }, { t: o.total.toFixed(1) + ' zones typically in prime', cls: 'tip-l' }];
    FAMS.forEach((f) => { if (o[f] > 0) lines.push({ sw: FAM[f].color, t: FAM[f].short + ' ' + o[f].toFixed(1), cls: 'tip-m' }); });
    tip.show(ev, lines);
  }).on('mouseleave', () => tip.hide()).on('click', (ev) => { S.week = wkAt(ev); redraw(['weekly', 'weeklens']); });
});
dash.draw('weeklens', (el) => {
  const M = model();
  const rows = calcRows('prime_by_week');
  el.replaceChildren();
  if (!M || !rows || S.week === null) { el.appendChild(h('p', 'muted pad', '-')); return; }
  const wk = S.week;
  const d0 = (wk - 1) * 7 + 1;
  el.appendChild(h('div', 'wl-h', 'Most likely prime, week of ' + doyStr(d0)));
  const list = rows.filter((r) => r.week === wk && r.p_prime > 0).sort((a, b) => b.p_prime - a.p_prime || b.p_go - a.p_go).slice(0, 8);
  if (!list.length) { el.appendChild(h('p', 'muted', 'Nothing has reached prime this week in past years.')); return; }
  list.forEach((r) => {
    const info = seriesInfo(M, r.series);
    const b = h('button', 'wl-i' + (r.series === S.series ? ' sel' : ''));
    b.type = 'button';
    b.appendChild(h('span', 'wl-n', info.label));
    const bar = h('span', 'wl-bar');
    const fill = h('i', 'wl-fill');
    fill.style.width = Math.round(r.p_prime * 100) + '%';
    fill.style.background = FAM[info.fam].color;
    bar.appendChild(fill);
    b.appendChild(bar);
    b.appendChild(h('span', 'wl-p', fPct(r.p_prime)));
    b.addEventListener('click', () => selectSeries(r.series, true));
    el.appendChild(b);
  });
});

/* ---------- stats: explorer ---------- */
dash.draw('series-select', (sel) => {
  const M = model();
  sel.replaceChildren();
  if (!M) return;
  setDefaultsFromModel(M);
  M.fullSeries.map((k) => seriesInfo(M, k)).sort((a, b) => a.z.short.localeCompare(b.z.short) || FAMS.indexOf(a.fam) - FAMS.indexOf(b.fam))
    .forEach((i) => sel.appendChild(new Option(i.label, i.key)));
  sel.value = S.series;
  sel.onchange = () => selectSeries(sel.value, false);
});
function stat(label, value, sub) {
  const d = h('div', 'st');
  d.appendChild(h('span', 'st-l', label));
  d.appendChild(h('b', 'st-v', value));
  if (sub) d.appendChild(h('span', 'st-s', sub));
  return d;
}
dash.draw('exhead', (el) => {
  const M = model();
  const syRows = calcRows('series_year');
  el.replaceChildren();
  if (!M || !syRows || !S.series) return;
  const info = seriesInfo(M, S.series);
  const sw = firstRow('season_windows', S.series);
  const yrs = (bySeries(syRows).get(S.series) || []).filter((r) => !r.partial);
  const best = yrs.reduce((b, r) => (!b || r.prime_days > b.prime_days ? r : b), null);
  const worst = yrs.reduce((b, r) => (!b || r.prime_days < b.prime_days ? r : b), null);
  let nv = firstRow('now_vs_typical', S.series);
  if (nv && nv.years < 5) nv = null;
  const live = info.z.rows.filter((r) => r.species === info.sp)[0];
  const row = h('div', 'st-row');
  row.appendChild(stat('Typical prime window', sw ? doyStr(sw.start_med) + ' to ' + doyStr(sw.end_med) : '-', sw ? 'earliest ' + doyStr(sw.start_min) + ', latest ' + doyStr(sw.end_max) : 'not enough prime seasons'));
  row.appendChild(stat('Reliability', sw ? sw.years_prime + ' of ' + sw.years_total + ' years' : '-', 'reached prime at least once' + (sw && sw.years_total < 8 ? ' (short record)' : '')));
  row.appendChild(stat('Best year', best ? String(best.year) : '-', best ? best.prime_days + ' prime days' + (worst ? ' (worst ' + worst.year + ': ' + worst.prime_days + ')' : '') : ''));
  row.appendChild(stat('Right now', live && live.score !== null ? String(live.score) : 'off-season', nv ? 'higher than ' + Math.round(nv.percentile * 100) + '% of past years for today' : 'live model score'));
  el.appendChild(row);
});

dash.draw('odds', (el) => {
  const M = model();
  const rows0 = calcRows('prime_by_week');
  if (!M || !rows0 || !S.series) { placeholder(el); return; }
  const rows = bySeries(rows0).get(S.series);
  if (!rows) { placeholder(el, 'Not enough history for this zone yet.'); return; }
  const fam = FAM[rows[0].family].color;
  const act = rows.filter((r) => r.p_hi > 0.03);
  const w0 = Math.max(1, d3.min(act, (r) => r.week) - 2), w1 = Math.min(53, d3.max(act, (r) => r.week) + 2);
  const sub = rows.filter((r) => r.week >= w0 && r.week <= w1);
  const H = 250, mt = 20, mb = 24;
  const { s, w } = svgIn(el, H);
  const tip = makeTip(el);
  const y = d3.scaleLinear().domain([0, 1]).range([H - mb, mt]);
  const ml = measure(s, ['100%']) + 12;
  const x = d3.scaleLinear().domain([w0, w1]).range([ml, w - 10]);
  [0, 0.25, 0.5, 0.75, 1].forEach((tk) => {
    s.append('line').attr('class', 'grid').attr('x1', ml).attr('x2', w - 10).attr('y1', y(tk)).attr('y2', y(tk));
    s.append('text').attr('class', 'ax').attr('x', ml - 6).attr('y', y(tk) + 3).attr('text-anchor', 'end').text(fPct(tk));
  });
  MONTH_DOY.forEach((d) => {
    const wk = (d - 1) / 7 + 1;
    if (wk > w0 && wk < w1) s.append('text').attr('class', 'ax').attr('x', x(wk)).attr('y', H - 6).text(fMon(dDate(d)));
  });
  s.append('path').attr('fill', fam).attr('opacity', 0.16).attr('d', d3.area().defined((r) => r.mean_score !== null).x((r) => x(r.week)).y0((r) => y(r.p_lo)).y1((r) => y(r.p_hi)).curve(d3.curveMonotoneX)(sub));
  s.append('path').attr('fill', 'none').attr('stroke', fam).attr('stroke-width', 2.2).attr('stroke-linejoin', 'round').attr('stroke-linecap', 'round')
    .attr('d', d3.line().x((r) => x(r.week)).y((r) => y(r.p_prime)).curve(d3.curveMonotoneX)(sub));
  s.append('path').attr('fill', 'none').attr('stroke', fam).attr('stroke-width', 1.6).attr('stroke-dasharray', '4 3')
    .attr('d', d3.line().x((r) => x(r.week)).y((r) => y(r.p_go)).curve(d3.curveMonotoneX)(sub));
  const tw = (M.todayDoy - 1) / 7 + 1;
  if (tw >= w0 && tw <= w1) {
    s.append('line').attr('class', 'today').attr('x1', x(tw)).attr('x2', x(tw)).attr('y1', mt - 4).attr('y2', H - mb);
    s.append('text').attr('class', 'ax strong').attr('x', x(tw) + 4).attr('y', mt + 4).text('Today');
  }
  const rule = s.append('line').attr('class', 'rule').attr('y1', mt).attr('y2', H - mb).style('display', 'none');
  const dot = s.append('circle').attr('r', 4).attr('fill', fam).style('stroke', 'var(--color-bg)').attr('stroke-width', 2).style('display', 'none');
  const bis = d3.bisector((r) => r.week).center;
  s.append('rect').attr('x', ml).attr('y', 0).attr('width', w - ml).attr('height', H).attr('fill', 'transparent')
    .on('mousemove', (ev) => {
      const wk = x.invert(d3.pointer(ev, s.node())[0]);
      const r = sub[clamp(bis(sub, wk), 0, sub.length - 1)];
      rule.style('display', null).attr('x1', x(r.week)).attr('x2', x(r.week));
      dot.style('display', null).attr('cx', x(r.week)).attr('cy', y(r.p_prime));
      const d0 = r.week_start_doy;
      tip.show(ev, [
        { t: 'Week of ' + doyStr(d0), cls: 'tip-t' },
        { sw: fam, t: 'Prime (60+) in ' + r.years_prime + ' of ' + r.years + ' years: ' + fPct(r.p_prime) },
        { t: '80% range ' + fPct(r.p_lo) + ' to ' + fPct(r.p_hi), cls: 'tip-m' },
        { t: 'Go now (80+): ' + fPct(r.p_go), cls: 'tip-m' }
      ]);
    }).on('mouseleave', () => { tip.hide(); rule.style('display', 'none'); dot.style('display', 'none'); });
});

function seasonSpan(rows) {
  let a = 53, b = 1;
  rows.forEach((r) => {
    const wk = r.weekly.split(',');
    for (let i = 0; i < 53; i++) if (wk[i] !== '') { a = Math.min(a, i + 1); b = Math.max(b, i + 1); }
  });
  return [a, b];
}
dash.draw('calendar', (el) => {
  const M = model();
  const sy = calcRows('series_year');
  if (!M || !sy || !S.series) { placeholder(el); return; }
  const rows = (bySeries(sy).get(S.series) || []).slice().sort((a, b) => a.year - b.year);
  if (!rows.length) { placeholder(el, 'Not enough history for this zone yet.'); return; }
  const span = seasonSpan(rows);
  const w0 = Math.max(1, span[0] - 1), w1 = Math.min(53, span[1] + 1);
  const cellH = 20, mt = 24;
  const H = mt + rows.length * cellH + 6;
  const { s, w } = svgIn(el, H);
  const tip = makeTip(el);
  const ml = measure(s, ['2026*']) + 12;
  const x = d3.scaleBand().domain(d3.range(w0, w1 + 1)).range([ml, w - 4]).paddingInner(0.1);
  const y = d3.scaleBand().domain(rows.map((r) => r.year)).range([mt, H - 6]).paddingInner(0.12);
  MONTH_DOY.forEach((d) => {
    const wk = Math.floor((d - 1) / 7) + 1;
    if (wk >= w0 && wk <= w1) s.append('text').attr('class', 'ax').attr('x', x(wk)).attr('y', 14).text(fMon(dDate(d)));
  });
  rows.forEach((r) => {
    const wk = r.weekly.split(',');
    s.append('text').attr('class', 'ax' + (r.year === S.syear ? ' strong' : '')).attr('x', ml - 6).attr('y', y(r.year) + y.bandwidth() / 2 + 3).attr('text-anchor', 'end').text(r.year + (r.partial ? '*' : ''));
    d3.range(w0, w1 + 1).forEach((c) => {
      const v = wk[c - 1];
      const rect = s.append('rect').attr('x', x(c)).attr('y', y(r.year)).attr('width', x.bandwidth()).attr('height', y.bandwidth()).attr('rx', 2)
        .style('fill', v === '' ? 'var(--cell-empty)' : scoreColor(+v)).style('cursor', 'pointer');
      rect.on('mousemove', (ev) => tip.show(ev, [
        { t: r.year + ', week of ' + doyStr((c - 1) * 7 + 1, r.year), cls: 'tip-t' },
        v === '' ? { t: 'Off-season / not scored', cls: 'tip-m' } : { sw: scoreColor(+v), t: 'Best score ' + v + ' (' + BANDS[bandIdx(+v)].name + ')' }
      ])).on('mouseleave', () => tip.hide()).on('click', () => { S.syear = r.year; redraw(['calendar', 'years', 'yeartrace']); });
    });
    if (r.year === S.syear) s.append('rect').attr('class', 'selrow').attr('x', ml - 2).attr('y', y(r.year) - 2).attr('width', w - ml - 2).attr('height', y.bandwidth() + 4).attr('rx', 4);
  });
});

dash.draw('years', (el) => {
  const M = model();
  const sy = calcRows('series_year');
  if (!M || !sy || !S.series) { placeholder(el); return; }
  const rows = (bySeries(sy).get(S.series) || []).slice().sort((a, b) => a.year - b.year);
  if (!rows.length) { placeholder(el, 'Not enough history for this zone yet.'); return; }
  const fam = FAM[famOf(S.series.split('|')[1])].color;
  const H = 250, mt = 22, mb = 24;
  const { s, w } = svgIn(el, H);
  const tip = makeTip(el);
  const full = rows.filter((r) => !r.partial);
  const avg = d3.mean(full, (r) => r.prime_days);
  const y = d3.scaleLinear().domain([0, Math.max(10, d3.max(rows, (r) => r.prime_days))]).nice().range([H - mb, mt]);
  const ticks = y.ticks(4);
  const ml = measure(s, ticks.map(String)) + 12;
  const x = d3.scaleBand().domain(rows.map((r) => r.year)).range([ml, w - 8]).paddingInner(0.22);
  ticks.forEach((tk) => {
    s.append('line').attr('class', 'grid').attr('x1', ml).attr('x2', w - 8).attr('y1', y(tk)).attr('y2', y(tk));
    s.append('text').attr('class', 'ax').attr('x', ml - 6).attr('y', y(tk) + 3).attr('text-anchor', 'end').text(tk);
  });
  rows.forEach((r) => {
    const bw = Math.min(x.bandwidth(), 36), bx = x(r.year) + (x.bandwidth() - bw) / 2;
    const g = s.append('g').style('cursor', 'pointer');
    g.append('rect').attr('x', bx).attr('width', bw).attr('y', y(r.prime_days)).attr('height', Math.max(0, y(0) - y(r.prime_days))).attr('rx', 3)
      .attr('fill', fam).attr('opacity', r.partial ? 0.18 : 0.38);
    g.append('rect').attr('x', bx).attr('width', bw).attr('y', y(r.go_days)).attr('height', Math.max(0, y(0) - y(r.go_days))).attr('rx', 3)
      .attr('fill', fam).attr('opacity', r.partial ? 0.5 : 1);
    if (r.year === S.syear) g.append('rect').attr('class', 'selbar').attr('x', bx - 3).attr('width', bw + 6).attr('y', mt - 4).attr('height', H - mb - mt + 4).attr('rx', 4);
    s.append('text').attr('class', 'ax' + (r.year === S.syear ? ' strong' : '')).attr('x', x(r.year) + x.bandwidth() / 2).attr('y', H - 6).attr('text-anchor', 'middle').text(String(r.year).slice(2) + (r.partial ? '*' : ''));
    if (bw >= 20) s.append('text').attr('class', 'ax val').attr('x', x(r.year) + x.bandwidth() / 2).attr('y', y(r.prime_days) - 4).attr('text-anchor', 'middle').text(r.prime_days);
    g.append('rect').attr('x', x(r.year)).attr('width', x.bandwidth()).attr('y', 0).attr('height', H).attr('fill', 'transparent');
    g.on('mousemove', (ev) => tip.show(ev, [
      { t: r.year + (r.partial ? ' (so far)' : ''), cls: 'tip-t' },
      { sw: fam, t: r.prime_days + ' prime days (60+)' },
      { t: r.go_days + ' go-now days (80+)', cls: 'tip-m' },
      { t: r.first_prime ? 'Prime ' + doyStr(r.first_prime, r.year) + ' to ' + doyStr(r.last_prime, r.year) : 'Never reached prime', cls: 'tip-m' }
    ])).on('mouseleave', () => tip.hide()).on('click', () => { S.syear = r.year; redraw(['calendar', 'years', 'yeartrace']); });
  });
  s.append('line').attr('class', 'avg').attr('x1', ml).attr('x2', w - 8).attr('y1', y(avg)).attr('y2', y(avg));
  s.append('text').attr('class', 'ax strong').attr('x', w - 8).attr('y', y(avg) - 5).attr('text-anchor', 'end').text('Average ' + avg.toFixed(0) + ' days');
});

dash.draw('yeartrace', (el) => {
  const M = model();
  const sy = calcRows('series_year');
  if (!M || !sy || !S.series) { placeholder(el); return; }
  const hv = M.hist.get(S.series);
  const rows = (bySeries(sy).get(S.series) || []).slice().sort((a, b) => a.year - b.year);
  if (!hv || !rows.length) { placeholder(el, 'Not enough history for this zone yet.'); return; }
  if (S.syear === null || !hv.get(S.syear)) S.syear = rows[rows.length - 1].year;
  const year = S.syear;
  const fam = FAM[famOf(S.series.split('|')[1])].color;
  const span = seasonSpan(rows);
  const d0 = Math.max(1, (span[0] - 2) * 7 + 1), d1 = Math.min(366, span[1] * 7 + 7);
  const others = rows.filter((r) => !r.partial && r.year !== year).map((r) => hv.get(r.year));
  const days = d3.range(d0, d1 + 1);
  const band = days.map((d) => {
    const vals = others.map((a) => a[d - 1]).filter((v) => v !== null && v !== undefined).sort((a, b) => a - b);
    return { d, n: vals.length, lo: vals.length ? vals[0] : null, hi: vals.length ? vals[vals.length - 1] : null, med: vals.length ? d3.median(vals) : null };
  });
  const cur = hv.get(year);
  const H = 250, mt = 20, mb = 24;
  const { s, w } = svgIn(el, H);
  const tip = makeTip(el);
  const y = d3.scaleLinear().domain([0, 100]).range([H - mb, mt]);
  const ml = measure(s, ['100']) + 12;
  const x = d3.scaleLinear().domain([d0, d1]).range([ml, w - 10]);
  [0, 20, 40, 60, 80, 100].forEach((tk) => {
    s.append('line').attr('class', 'grid').attr('x1', ml).attr('x2', w - 10).attr('y1', y(tk)).attr('y2', y(tk));
    s.append('text').attr('class', 'ax').attr('x', ml - 6).attr('y', y(tk) + 3).attr('text-anchor', 'end').text(tk);
  });
  s.append('rect').attr('class', 'zone-go').attr('x', ml).attr('width', w - 10 - ml).attr('y', y(100)).attr('height', y(80) - y(100));
  s.append('rect').attr('class', 'zone-prime').attr('x', ml).attr('width', w - 10 - ml).attr('y', y(80)).attr('height', y(60) - y(80));
  MONTH_DOY.forEach((d) => { if (d > d0 && d < d1) s.append('text').attr('class', 'ax').attr('x', x(d) + 3).attr('y', H - 6).text(fMon(dDate(d))); });
  const ok = band.filter((b) => b.lo !== null);
  s.append('path').style('fill', 'var(--color-fg)').attr('opacity', 0.1)
    .attr('d', d3.area().defined((b) => b.lo !== null).x((b) => x(b.d)).y0((b) => y(b.lo)).y1((b) => y(b.hi))(band));
  s.append('path').attr('fill', 'none').style('stroke', 'var(--color-fg-muted)').attr('stroke-width', 1.4).attr('stroke-dasharray', '4 3')
    .attr('d', d3.line().defined((b) => b.med !== null).x((b) => x(b.d)).y((b) => y(b.med))(band));
  const pts = days.map((d) => ({ d, v: cur[d - 1] === undefined ? null : cur[d - 1] }));
  s.append('path').attr('fill', 'none').attr('stroke', fam).attr('stroke-width', 2.4).attr('stroke-linejoin', 'round').attr('stroke-linecap', 'round')
    .attr('d', d3.line().defined((p) => p.v !== null).x((p) => x(p.d)).y((p) => y(p.v))(pts));
  if (year === M.todayYear && M.todayDoy >= d0 && M.todayDoy <= d1) {
    s.append('line').attr('class', 'today').attr('x1', x(M.todayDoy)).attr('x2', x(M.todayDoy)).attr('y1', mt - 4).attr('y2', H - mb);
    s.append('text').attr('class', 'ax strong').attr('x', x(M.todayDoy) + 4).attr('y', mt + 2).text('Today');
  }
  const rule = s.append('line').attr('class', 'rule').attr('y1', mt).attr('y2', H - mb).style('display', 'none');
  s.append('rect').attr('x', ml).attr('y', 0).attr('width', w - ml).attr('height', H).attr('fill', 'transparent')
    .on('mousemove', (ev) => {
      const d = clamp(Math.round(x.invert(d3.pointer(ev, s.node())[0])), d0, d1);
      const b = band[d - d0], v = cur[d - 1];
      rule.style('display', null).attr('x1', x(d)).attr('x2', x(d));
      const lines = [{ t: doyStr(d, year) + ', ' + year, cls: 'tip-t' }, v === null || v === undefined ? { t: 'Off-season / not scored', cls: 'tip-m' } : { sw: fam, t: 'Score ' + v + ' (' + BANDS[bandIdx(v)].name + ')' }];
      if (b.lo !== null) lines.push({ t: 'Other years: typical ' + Math.round(b.med) + ', range ' + b.lo + ' to ' + b.hi, cls: 'tip-m' });
      tip.show(ev, lines);
    }).on('mouseleave', () => { tip.hide(); rule.style('display', 'none'); });
  void ok;
});
dash.draw('yeartrace-title', (el) => {
  el.textContent = S.syear === null ? '-' : String(S.syear) + (S.syear === (model() || {}).todayYear ? ' so far' : '') + ' against the other years';
});

/* ---------- stats: elevation vs timing ---------- */
dash.draw('elev', (el) => {
  const M = model();
  const sw = calcRows('season_windows');
  const fit = calcRows('timing_fit');
  if (!M || !sw || !fit) { placeholder(el); return; }
  const H = 340, mt = 14, mb = 34;
  const { s, w } = svgIn(el, H);
  const tip = makeTip(el);
  const ex = d3.extent(sw, (r) => r.elev_ft);
  const x = d3.scaleLinear().domain([Math.max(0, Math.floor(ex[0] / 500) * 500 - 250), Math.ceil(ex[1] / 500) * 500 + 250]);
  const y = d3.scaleLinear().domain([90, 340]).range([H - mb, mt]);
  const ticksY = MONTH_DOY.filter((d) => d >= 90 && d <= 340);
  const ml = measure(s, ['Dec']) + 12;
  x.range([ml, w - 12]);
  ticksY.forEach((d) => {
    s.append('line').attr('class', 'grid').attr('x1', ml).attr('x2', w - 12).attr('y1', y(d)).attr('y2', y(d));
    s.append('text').attr('class', 'ax').attr('x', ml - 6).attr('y', y(d) + 3).attr('text-anchor', 'end').text(fMon(dDate(d)));
  });
  x.ticks(6).forEach((tk) => {
    s.append('text').attr('class', 'ax').attr('x', x(tk)).attr('y', H - 18).attr('text-anchor', 'middle').text(fInt(tk));
  });
  s.append('text').attr('class', 'ax').attr('x', (ml + w - 12) / 2).attr('y', H - 4).attr('text-anchor', 'middle').text('Zone elevation (ft)');
  fit.forEach((f) => {
    const pts = sw.filter((r) => r.family === f.family);
    const e = d3.extent(pts, (r) => r.elev_ft);
    if (f.n < 4 || e[0] === e[1] || f.r2 < 0.25) return;
    const yy = (el2) => f.intercept + f.slope_days_per_1000ft / 1000 * el2;
    s.append('line').attr('stroke', FAM[f.family].color).attr('stroke-width', 1.6).attr('stroke-dasharray', '5 4').attr('opacity', 0.8)
      .attr('x1', x(e[0])).attr('x2', x(e[1])).attr('y1', y(yy(e[0]))).attr('y2', y(yy(e[1])));
  });
  sw.slice().sort((a, b) => (a.series === S.series) - (b.series === S.series)).forEach((r) => {
    const col = FAM[r.family].color;
    const c = s.append('circle').attr('cx', x(r.elev_ft)).attr('cy', y(r.peak_med)).attr('r', r.series === S.series ? 9 : 6.5).attr('fill', col).attr('opacity', 0.9)
      .style('stroke', r.series === S.series ? 'var(--color-fg)' : 'var(--color-bg)').attr('stroke-width', r.series === S.series ? 2.4 : 1.6).style('cursor', 'pointer');
    c.on('mousemove', (ev) => tip.show(ev, [
      { t: r.zone_name + ' - ' + r.species_name, cls: 'tip-t' },
      { sw: col, t: fInt(r.elev_ft) + ' ft, typical best day ' + doyStr(r.peak_med) },
      { t: 'Prime ' + doyStr(r.start_med) + ' to ' + doyStr(r.end_med), cls: 'tip-m' }
    ])).on('mouseleave', () => tip.hide()).on('click', () => selectSeries(r.series, true));
  });
});
dash.draw('elev-fit', (el) => {
  const fit = calcRows('timing_fit');
  el.replaceChildren();
  if (!fit) return;
  fit.slice().sort((a, b) => FAMS.indexOf(a.family) - FAMS.indexOf(b.family)).forEach((f) => {
    const c = h('div', 'fit');
    const dot = h('i', 'chip-dot');
    dot.style.background = FAM[f.family].color;
    c.appendChild(dot);
    const d = f.slope_days_per_1000ft;
    c.appendChild(h('span', null, FAM[f.family].short + ': ' + (d >= 0 ? '+' : '') + d.toFixed(1) + ' days per 1,000 ft'));
    c.appendChild(h('span', 'muted', (f.r2 < 0.25 ? 'weak trend, ' : '') + 'r2 ' + f.r2.toFixed(2) + ', ' + f.n + ' zones'));
    el.appendChild(c);
  });
});

dash.draw('brief', (el) => {
  const M = model();
  el.replaceChildren();
  if (!M || !M.about.brief_text) return;
  M.about.brief_text.split('\n').filter(Boolean).forEach((p) => el.appendChild(h('p', null, p)));
  el.appendChild(h('p', 'muted small', (M.about.brief_note || '') + (M.about.brief_date ? ' (' + M.about.brief_date + ')' : '')));
});

dash.draw('minscore-read', (el) => { el.textContent = S.minScore > 0 ? String(S.minScore) + '+' : 'any'; });

dash.draw('footnote', (el) => {
  const M = model();
  el.replaceChildren();
  if (!M) return;
  el.appendChild(h('span', null, M.about.caveat + ' All data comes from public sources: see the '));
  const src = h('a', null, 'data sources and credits');
  src.href = 'sources.html';
  el.appendChild(src);
  el.appendChild(document.createTextNode('.'));
});

/* ---------- listeners ---------- */
$$('[data-tab]').forEach((b) => b.addEventListener('click', () => showTab(b.dataset.tab)));
$$('[data-sp]').forEach((b) => b.addEventListener('click', () => {
  S.sp = b.dataset.sp;
  const M = model();
  if (M && S.zone) { const z = M.zById[S.zone]; if (S.sp !== 'all' && z.spKeys.indexOf(S.sp) >= 0) S.zsp = S.sp; }
  sync();
  redraw(MAPSET);
}));
$$('[data-mode]').forEach((b) => b.addEventListener('click', () => {
  S.mode = b.dataset.mode;
  if (S.mode !== 'time') stopPlay();
  sync();
  redraw(MAPSET.concat(['tm-year']));
}));
$$('[data-fam]').forEach((b) => b.addEventListener('click', () => { S.fam = b.dataset.fam; sync(); redraw(['seasons']); }));
$('#metric').addEventListener('change', (e) => { S.metric = e.target.value; sync(); redraw(['map', 'legend', 'ranklist']); });
$('#region').addEventListener('change', (e) => { S.region = e.target.value; sync(); redraw(['map', 'ranklist']); });
$('#land').addEventListener('change', (e) => { S.land = e.target.value; redraw(['map', 'ranklist']); });
$('#elev').addEventListener('change', (e) => { S.elev = e.target.value; redraw(['map', 'ranklist']); });
$('#sort').addEventListener('change', (e) => { S.sort = e.target.value; redraw(['ranklist']); });
$('#minscore').addEventListener('input', (e) => { S.minScore = +e.target.value; redraw(['map', 'ranklist', 'minscore-read']); });
$('#q').addEventListener('input', (e) => { S.q = e.target.value; redraw(['map', 'ranklist']); });
$('#reset').addEventListener('click', () => {
  S.region = 'all'; S.land = 'all'; S.elev = 'any'; S.minScore = 0; S.q = ''; S.sort = 'metric'; S.seasonOnly = false;
  sync();
  redraw(['map', 'ranklist', 'minscore-read']);
});
$('#seasons-more').addEventListener('click', () => { S.showAll = !S.showAll; sync(); redraw(['seasons']); });
$('#opt-heat').addEventListener('change', (e) => { S.heat = e.target.checked; redraw(['map']); });
$('#opt-markers').addEventListener('change', (e) => { S.markers = e.target.checked; redraw(['map']); });
$('#opt-season').addEventListener('change', (e) => { S.seasonOnly = e.target.checked; redraw(['map', 'ranklist']); });
$('#opt-landmap').addEventListener('change', (e) => { S.landMap = e.target.checked; sync(); redraw(['map']); });
$('#opt-sight').addEventListener('change', (e) => { S.sight = e.target.checked; sync(); redraw(['map']); });
$('#sight-when').addEventListener('change', (e) => { S.sightWhen = e.target.value; redraw(['map']); });
$('#opt-sightpub').addEventListener('change', (e) => { S.sightPub = e.target.checked; redraw(['map']); });
$('#layers-btn').addEventListener('click', () => { S.layers = !S.layers; sync(); });
$('#zoom-in').addEventListener('click', () => { if (MAP) MAP.lmap.zoomIn(); });
$('#zoom-out').addEventListener('click', () => { if (MAP) MAP.lmap.zoomOut(); });
$('#zoom-reset').addEventListener('click', () => { if (MAP) MAP.userMoved = false; resetView(); });
$('#tm-slider').addEventListener('input', (e) => { S.doy = +e.target.value; redraw(['map', 'timeread', 'ranklist', 'zpanel']); });
$('#tm-play').addEventListener('click', () => { if (S.playing) stopPlay(); else startPlay(); sync(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && S.zone) clearZone(); });

dash.onData(() => {
  const M = model();
  if (M) setDefaultsFromModel(M);
  sync();
});
const named = (location.hash || '').slice(1);
if (named === 'stats') { S.tab = 'stats'; }
sync();
})();
