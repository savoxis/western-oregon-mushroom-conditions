/* Charts drawn with Recharts (vendored UMD build, no build step, no CDN) through React.createElement. Each function draws into an element and replaces any earlier
   chart in it. All text in a chart is a number or a label the page itself made: nothing from a data file is ever used as markup. */
(function () {
  'use strict';
  const R = window.Recharts, RC = window.React, RD = window.ReactDOM;
  const e = RC.createElement;
  const roots = new WeakMap();

  function palette() {
    const cs = getComputedStyle(document.documentElement);
    const g = (n, f) => (cs.getPropertyValue(n) || '').trim() || f;
    return { muted: g('--color-fg-muted', '#78bb98'), fg: g('--color-fg', '#e6fff0'), grid: 'rgba(128,128,128,.22)', band: 'rgba(128,128,128,.18)' };
  }
  function mount(el, node) {
    let root = roots.get(el);
    if (!root) { el.replaceChildren(); root = RD.createRoot(el); roots.set(el, root); }
    root.render(node);
  }
  function clear(el) { const r = roots.get(el); if (r) { r.unmount(); roots.delete(el); } }

  /* tooltip body from [{t, cls, sw}] lines, in the same look as the page's other tooltips */
  function tip(linesFor) {
    return e(R.Tooltip, {
      isAnimationActive: false, cursor: { fill: 'rgba(128,128,128,.14)' },
      content: (p) => {
        if (!p.active || !p.payload || !p.payload.length) return null;
        const lines = linesFor(p.payload[0].payload);
        return e('div', { className: 'rc-tip' }, lines.map((ln, i) => e('div', { key: i, className: ln.cls || 'tip-l' },
          ln.sw ? e('i', { className: 'tip-sw', style: { background: ln.sw } }) : null, ln.t)));
      }
    });
  }

  /* Statewide week-by-week stacked bars (one stack per mushroom family), the selected week outlined, the busiest week labelled.
     c: { weeks: [{week, total, <family>: n}], fams, colors: {family: color}, sel, peak: {week, total, label}, ticks: [{week, label}], tipLines(w), onPick(week) } */
  function weekly(el, c) {
    const k = palette();
    const labelOf = {};
    c.ticks.forEach((t) => { labelOf[t.week] = t.label; });
    const bars = c.fams.map((f) => e(R.Bar, { key: f, dataKey: f, stackId: 'a', fill: c.colors[f], isAnimationActive: false },
      c.weeks.map((w) => e(R.Cell, { key: w.week, fill: c.colors[f], stroke: w.week === c.sel ? k.fg : 'none', strokeWidth: w.week === c.sel ? 1.5 : 0, fillOpacity: !c.sel || w.week === c.sel ? 1 : 0.78 }))));
    mount(el, e(R.ResponsiveContainer, { width: '100%', height: 230 },
      e(R.BarChart, { data: c.weeks, margin: { top: 24, right: 6, bottom: 0, left: -14 }, barCategoryGap: '14%', style: { cursor: 'pointer' },
        onClick: (s) => { if (s && s.activeLabel !== undefined && s.activeLabel !== null) c.onPick(Number(s.activeLabel)); } },
        e(R.CartesianGrid, { stroke: k.grid, vertical: false }),
        e(R.XAxis, { dataKey: 'week', ticks: c.ticks.map((t) => t.week), interval: 0, tickFormatter: (w) => labelOf[w] || '', tick: { fill: k.muted, fontSize: 11 }, tickLine: false, axisLine: false }),
        e(R.YAxis, { tick: { fill: k.muted, fontSize: 11 }, tickLine: false, axisLine: false, width: 34 }),
        tip(c.tipLines),
        bars,
        e(R.ReferenceDot, { x: c.peak.week, y: c.peak.total, r: 0, ifOverflow: 'extendDomain', label: { value: c.peak.label, position: 'top', fill: k.fg, fontSize: 11, fontWeight: 600 } }))));
  }

  /* One bar per year: prime days (faint) behind go-now days (solid), a dashed average line, the selected year outlined.
     c: { rows: [{year, label, prime, go, partial}], color, avg, sel, onPick(year), tipLines(row) } */
  function years(el, c) {
    const k = palette();
    const sz = 28;
    const cells = (key) => c.rows.map((r) => e(R.Cell, { key: r.year, fill: c.color, fillOpacity: key === 'prime' ? (r.partial ? 0.18 : 0.38) : (r.partial ? 0.5 : 1), stroke: r.year === c.sel ? k.fg : 'none', strokeWidth: r.year === c.sel ? 1.5 : 0 }));
    mount(el, e(R.ResponsiveContainer, { width: '100%', height: 250 },
      e(R.BarChart, { data: c.rows, margin: { top: 24, right: 8, bottom: 0, left: -14 }, barGap: -sz, style: { cursor: 'pointer' },
        onClick: (s) => { const p = s && s.activePayload && s.activePayload[0]; if (p) c.onPick(p.payload.year); } },
        e(R.CartesianGrid, { stroke: k.grid, vertical: false }),
        e(R.XAxis, { dataKey: 'label', tick: { fill: k.muted, fontSize: 11 }, tickLine: false, axisLine: false, interval: 0 }),
        e(R.YAxis, { tick: { fill: k.muted, fontSize: 11 }, tickLine: false, axisLine: false, width: 34, allowDecimals: false }),
        tip(c.tipLines),
        e(R.Bar, { dataKey: 'prime', barSize: sz, radius: [3, 3, 0, 0], isAnimationActive: false, name: 'prime' }, cells('prime'),
          e(R.LabelList, { dataKey: 'prime', position: 'top', fill: k.muted, fontSize: 11 })),
        e(R.Bar, { dataKey: 'go', barSize: sz, radius: [3, 3, 0, 0], isAnimationActive: false, name: 'go' }, cells('go')),
        e(R.ReferenceLine, { y: c.avg, stroke: k.fg, strokeDasharray: '5 4', strokeOpacity: 0.7, label: { value: 'Average ' + c.avg.toFixed(0) + ' days', position: 'insideTopRight', fill: k.fg, fontSize: 11, fontWeight: 600 } }))));
  }

  window.HChart = { weekly: weekly, years: years, clear: clear };
})();
