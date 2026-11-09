/* dash.js - small runtime for the redesigned page: loads the compact datasets, runs the calcs and the [data-draw] renderers.
   Same contract the dashboard prototype was written against (dash.data / dash.calc / dash.draw / dash.onData). No keys, no third parties. */
(async function () {
  'use strict';
  const ids = ['zones', 'live', 'history', 'weather', 'about', 'grid', 'grid_hist'];
  const ds = {};
  const root = document.getElementById('dash-root');
  try {
    const got = await Promise.all(ids.map((id) => fetch('data/c/' + id + '.json', { cache: 'no-cache' }).then((r) => { if (!r.ok) throw new Error(id + ' ' + r.status); return r.json(); })));
    ids.forEach((id, i) => { ds[id] = got[i]; });
  } catch (e) {
    root.insertAdjacentHTML('afterbegin', '<p style="padding:1rem">The data could not be loaded (' + String(e.message).replace(/[<>&]/g, '') + '). The nightly build may not have finished yet; try again in a few minutes.</p>');
    return;
  }
  const calcs = {}, cache = {}, draws = {};
  const run = (name) => {
    const d = draws[name];
    if (!d) return;
    document.querySelectorAll('[data-draw="' + name + '"]').forEach((el) => {
      if (el.closest('[hidden]')) return;
      try {
        if (typeof d.fn === 'function') d.fn(el);
        else {
          if (!d.st.has(el)) d.st.set(el, { made: d.fn.mount(el) });
          d.fn.update(el, d.st.get(el).made);
        }
      } catch (e) { console.error('draw ' + name, e); }
    });
  };
  let onData = null;
  window.dash = {
    data(id) {
      if (ds[id]) return { status: 'ok', data: ds[id] };
      if (calcs[id]) {
        if (!cache[id]) { const c = calcs[id]; cache[id] = c.fn.apply(null, c.inputs.map((i) => window.dash.data(i).data)); }
        return { status: 'ok', data: cache[id] };
      }
      return { status: 'missing', data: null };
    },
    calc(id, d) { calcs[id] = d; },
    draw(n, fn) { if (fn === undefined) return run(n); draws[n] = { fn, st: new WeakMap() }; return undefined; },
    onData(fn) { onData = fn; },
    setLink(name) { try { history.replaceState(null, '', name === 'stats' ? '#stats' : location.pathname); } catch (e) { /* ignore */ } }
  };
  for (const f of ['calcs.js', 'app.js']) {
    await new Promise((res, rej) => { const s = document.createElement('script'); s.src = f; s.onload = res; s.onerror = rej; document.body.appendChild(s); });
  }
  if (onData) onData();
  Object.keys(draws).forEach(run);
  window.__ready = true;
})();
