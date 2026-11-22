/* Phase 1 spike: can MapLibre draw this site's map? One page, not linked from anywhere, reading the same data files as the real page.
   It draws the USGS topo, the Gaussian-blended heat surface (computed ONCE on a fixed lat/lon grid and handed to the GPU as an image source, so panning and zooming
   cost nothing), the zones as a circle layer coloured by score, and measures: time to compute the surface, and frame times while zooming. */
(function () {
  'use strict';
  const $ = (s) => document.querySelector(s);
  const BANDS = ['#7d8695', '#b99d63', '#e0b535', '#7bc05a', '#1e9e5f'];
  const STOPS = [10, 30, 50, 70, 90];
  const BBOX = { w: -124.8, e: -116.4, s: 41.9, n: 46.4 };                      // Oregon
  const TOPO = 'https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}';
  const out = (t) => { $('#out').textContent = t; };
  const hex = (h) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
  function ramp(v) {                                                          // the same stops as the live page's scoreRamp
    if (v <= STOPS[0]) return hex(BANDS[0]);
    if (v >= STOPS[4]) return hex(BANDS[4]);
    for (let i = 0; i < 4; i++) if (v <= STOPS[i + 1]) { const t = (v - STOPS[i]) / (STOPS[i + 1] - STOPS[i]), a = hex(BANDS[i]), b = hex(BANDS[i + 1]); return a.map((x, k) => Math.round(x + (b[k] - x) * t)); }
    return hex(BANDS[4]);
  }
  const J = (u) => fetch(u).then((r) => r.json());
  let MAP = null, ZONES = [], GRID = [], LIVE = [], RING = null;

  function points(fam) {
    const best = {};
    LIVE.forEach((r) => { if (r.score_raw !== null && (r.species === fam || r.family === fam)) { const z = best[r.zone]; if (z === undefined || r.score_raw > z) best[r.zone] = r.score_raw; } });
    const pts = [];
    ZONES.forEach((z) => { if (best[z.id] !== undefined) pts.push({ lat: z.lat, lon: z.lon, v: best[z.id], z: true }); });
    GRID.forEach((g) => { if (g.species === fam && g.score !== null) pts.push({ lat: g.lat, lon: g.lon, v: g.score }); });
    return pts;
  }

  /* the heat surface: Gaussian-weighted mean of the nearby scores (sigma 25 km, reach 80 km), clipped to Oregon's outline, on a fixed lat/lon grid */
  function heatCanvas(pts, cellDeg) {
    const gw = Math.round((BBOX.e - BBOX.w) / cellDeg), gh = Math.round((BBOX.n - BBOX.s) / cellDeg);
    const cv = document.createElement('canvas');
    cv.width = gw; cv.height = gh;
    const ctx = cv.getContext('2d');
    const img = ctx.createImageData(gw, gh);
    const kx = Math.cos(44 * Math.PI / 180) * 111.32, ky = 110.57;
    const sigma = 25, reach = 80, inv2s2 = 1 / (2 * sigma * sigma);
    const px = pts.map((p) => ({ x: (p.lon - BBOX.w) * kx, y: (BBOX.n - p.lat) * ky, v: p.v }));
    const dx = cellDeg * kx, dy = cellDeg * ky;
    for (let j = 0; j < gh; j++) {
      for (let i = 0; i < gw; i++) {
        const x = (i + 0.5) * dx, y = (j + 0.5) * dy;
        let sw = 0, sv = 0;
        for (let n = 0; n < px.length; n++) {
          const ax = x - px[n].x, ay = y - px[n].y;
          if (ax > reach || ax < -reach || ay > reach || ay < -reach) continue;
          const d2 = ax * ax + ay * ay;
          if (d2 > reach * reach) continue;
          const w = Math.exp(-d2 * inv2s2);
          sw += w; sv += w * px[n].v;
        }
        if (sw < 0.02) continue;
        const c = ramp(sv / sw), o = (j * gw + i) * 4;
        img.data[o] = c[0]; img.data[o + 1] = c[1]; img.data[o + 2] = c[2]; img.data[o + 3] = Math.round(Math.min(1, sw / 0.55) * 0.62 * 255);
      }
    }
    // draw into a second canvas through the Oregon clip so nothing shows outside the state
    const tmp = document.createElement('canvas'); tmp.width = gw; tmp.height = gh;
    tmp.getContext('2d').putImageData(img, 0, 0);
    const outc = document.createElement('canvas'); outc.width = gw * 2; outc.height = gh * 2;
    const octx = outc.getContext('2d');
    octx.beginPath();
    RING.forEach((p, k) => { const x = (p[0] - BBOX.w) / (BBOX.e - BBOX.w) * outc.width, y = (BBOX.n - p[1]) / (BBOX.n - BBOX.s) * outc.height; if (k) octx.lineTo(x, y); else octx.moveTo(x, y); });
    octx.closePath(); octx.clip();
    octx.imageSmoothingEnabled = true; octx.imageSmoothingQuality = 'high';
    octx.drawImage(tmp, 0, 0, outc.width, outc.height);
    return { canvas: outc, cells: gw * gh };
  }
  const corners = [[BBOX.w, BBOX.n], [BBOX.e, BBOX.n], [BBOX.e, BBOX.s], [BBOX.w, BBOX.s]];

  function drawAll() {
    const fam = $('#fam').value, cell = parseFloat($('#cell').value);
    const pts = points(fam);
    const t0 = performance.now();
    const h = heatCanvas(pts, cell);
    const ms = performance.now() - t0;
    const url = h.canvas.toDataURL('image/png');
    const src = MAP.getSource('heat');
    if (src) src.updateImage({ url: url, coordinates: corners });
    else {
      MAP.addSource('heat', { type: 'image', url: url, coordinates: corners });
      MAP.addLayer({ id: 'heat', type: 'raster', source: 'heat', paint: { 'raster-opacity': 1, 'raster-fade-duration': 0 } }, 'zones');
    }
    MAP.getSource('zones').setData({ type: 'FeatureCollection', features: pts.filter((p) => p.z).map((p) => ({ type: 'Feature', properties: { v: p.v }, geometry: { type: 'Point', coordinates: [p.lon, p.lat] } })) });
    return { ms: ms, pts: pts.length, cells: h.cells, png: Math.round(url.length * 0.75 / 1024) };
  }

  function bench() {
    const fam = $('#fam').value, pts = points(fam), res = [];
    [0.04, 0.03, 0.02].forEach((c) => { const t = performance.now(); const h = heatCanvas(pts, c); res.push(c + ' deg: ' + h.cells + ' cells, ' + (performance.now() - t).toFixed(1) + ' ms'); });
    out('Heat surface from ' + pts.length + ' points, one computation each (the live page redoes this on every pan and zoom):\n' + res.join('\n'));
  }
  function zoomBench() {
    out('zooming...');
    const times = [];
    let last = performance.now();
    const tick = () => { const n = performance.now(); times.push(n - last); last = n; if (running) requestAnimationFrame(tick); };
    let running = true;
    requestAnimationFrame(tick);
    MAP.jumpTo({ center: [-122.6, 44.5], zoom: 6 });
    const steps = [{ zoom: 9.5, center: [-122.0, 44.2] }, { zoom: 6, center: [-120.5, 44] }, { zoom: 9, center: [-123, 43.5] }, { zoom: 6, center: [-120.8, 44] }];
    let k = 0;
    const next = () => {
      if (k >= steps.length) { running = false; const t = times.slice(5); const avg = t.reduce((a, b) => a + b, 0) / t.length; const worst = Math.max.apply(null, t);
        out('Zoom benchmark (4 animated zooms, 1.2 s each): ' + t.length + ' frames, mean ' + avg.toFixed(1) + ' ms (' + (1000 / avg).toFixed(0) + ' fps), worst ' + worst.toFixed(0) + ' ms.\nNo heat recomputation happens during these zooms: the surface is a GPU image.'); return; }
      MAP.easeTo(Object.assign({ duration: 1200 }, steps[k++]));
      MAP.once('moveend', next);
    };
    next();
  }

  Promise.all([J('data/c/zones.json'), J('data/c/grid.json'), J('data/c/live.json'), J('oregon.json')]).then((a) => {
    ZONES = a[0]; GRID = a[1]; LIVE = a[2];
    const g = a[3].geometry; RING = (g.type === 'MultiPolygon' ? g.coordinates.reduce((m, p) => (p[0].length > m.length ? p[0] : m), []) : g.coordinates[0]);
    maplibregl.setWorkerUrl('vendor/maplibre/maplibre-gl-csp-worker.js');
    MAP = new maplibregl.Map({ container: 'map', center: [-120.6, 44.0], zoom: 6, minZoom: 4.5, maxZoom: 13, attributionControl: { compact: true },
      style: { version: 8, sources: { topo: { type: 'raster', tiles: [TOPO], tileSize: 256, maxzoom: 15, attribution: 'Tiles: U.S. Geological Survey' } },
        layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#050806' } }, { id: 'topo', type: 'raster', source: 'topo', paint: { 'raster-opacity': 0.55, 'raster-saturation': -0.6 } }] } });
    MAP.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    MAP.on('load', () => {
      MAP.addSource('zones', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      MAP.addLayer({ id: 'zones', type: 'circle', source: 'zones', paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 5, 5, 10, 12],
        'circle-color': ['interpolate', ['linear'], ['get', 'v'], 10, BANDS[0], 30, BANDS[1], 50, BANDS[2], 70, BANDS[3], 90, BANDS[4]], 'circle-stroke-color': '#050806', 'circle-stroke-width': 1.5 } });
      const r = drawAll();
      out('Drawn: ' + r.pts + ' points, heat grid ' + r.cells + ' cells computed in ' + r.ms.toFixed(1) + ' ms, image about ' + r.png + ' KB.\nMapLibre CSP build is about 970 KB (Leaflet 148 KB).\nUse the buttons to time the surface and a zoom.');
    });
    $('#fam').addEventListener('change', () => { const r = drawAll(); out('Redrawn: ' + r.pts + ' points in ' + r.ms.toFixed(1) + ' ms.'); });
    $('#cell').addEventListener('change', () => { const r = drawAll(); out('Redrawn at ' + r.cells + ' cells in ' + r.ms.toFixed(1) + ' ms.'); });
    $('#bench-heat').addEventListener('click', bench);
    $('#bench-zoom').addEventListener('click', zoomBench);
  }).catch((e) => out('could not load the data: ' + e.message));
})();
