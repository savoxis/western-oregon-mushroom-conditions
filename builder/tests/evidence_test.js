/* Checks the page's field-evidence rule (window.ShroomEvidence in site/calcs.js). Run by tests/test_evidence.py.
   usage: node evidence_test.js PATH_TO_calcs.js     Prints one failure per line and exits 1 if there are any. */
'use strict';
const fs = require('fs');
const vm = require('vm');

const ctx = { dash: { calc() {} }, console };
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), ctx, { filename: 'calcs.js' });
const E = ctx.window.ShroomEvidence;
const fails = [];
const check = (ok, msg) => { if (!ok) fails.push(msg); };

// a report n km east of (44, -120), at the same latitude; one degree of longitude is 111.32 * cos(44 degrees) km there
const KM_PER_DEG_LON = 111.32 * Math.cos(44 * Math.PI / 180);
const east = (km, sp) => ({ sp: sp || 'morel_natural', lat: 44, lon: -120 + km / KM_PER_DEG_LON });
const many = (n, km, sp) => Array.from({ length: n }, () => east(km, sp));
const at = (sight, key) => E.check(sight, 44, -120, key || 'morel_natural');

// no reports at all, or none of this species: none
check(at({ rows: [], blur: [] }).level === 'none', 'empty data should be none');
check(at({ rows: many(30, 5, 'chanterelle'), blur: [] }).level === 'none', 'reports of another species do not count');
check(at({}).level === 'none', 'missing arrays should be none, not an error');
check(at(null).level === 'none', 'null data should be none, not an error');

// thin: 1 to 4, ok: 5 or more (within the circle that applies)
check(at({ rows: many(1, 10), blur: [] }).level === 'thin', 'one report is thin');
check(at({ rows: many(4, 10), blur: [] }).level === 'thin', 'four reports are thin');
check(at({ rows: many(5, 10), blur: [] }).level === 'ok', 'five reports are enough');
check(at({ rows: many(3, 10), blur: many(2, 10) }).level === 'ok', 'blurred reports count toward the total');

// the circle: 40 km, widened to 80 km only when fewer than 15 are inside 40 km
let r = at({ rows: many(15, 39), blur: [] });
check(r.km === 40 && r.mi === 25 && r.n === 15, '15 reports inside 40 km keep the 40 km circle');
r = at({ rows: many(14, 39), blur: [] });
check(r.km === 80 && r.mi === 50, '14 reports inside 40 km widen the circle to 80 km');
r = at({ rows: many(3, 60), blur: [] });
check(r.km === 80 && r.n === 3 && r.level === 'thin', 'reports 60 km away count in the wide circle');
r = at({ rows: many(10, 81), blur: [] });
check(r.n === 0 && r.level === 'none', 'reports beyond 80 km do not count');
r = at({ rows: many(10, 79), blur: [] });
check(r.n === 10 && r.level === 'ok', 'reports at 79 km count');
check(at({ rows: many(14, 39).concat(many(1, 70)), blur: [] }).n === 15, 'the wide circle includes the near ones too');

// distance is true kilometres: a degree of longitude is shorter than a degree of latitude here
check(E.check({ rows: [{ sp: 'morel_natural', lat: 44, lon: -120 + 0.6 }], blur: [] }, 44, -120, 'morel_natural').n === 1, '0.6 deg of lon is about 48 km at 44 N: inside 80 km');
check(E.check({ rows: [{ sp: 'morel_natural', lat: 44, lon: -120 + 1.1 }], blur: [] }, 44, -120, 'morel_natural').n === 0, '1.1 deg of lon is about 88 km at 44 N: outside 80 km');
check(E.check({ rows: [{ sp: 'morel_natural', lat: 44 + 0.6, lon: -120 }], blur: [] }, 44, -120, 'morel_natural').n === 1, '0.6 deg of lat is about 67 km: inside 80 km');
check(E.check({ rows: [{ sp: 'morel_natural', lat: 44 + 0.8, lon: -120 }], blur: [] }, 44, -120, 'morel_natural').n === 0, '0.8 deg of lat is about 89 km: outside 80 km');

// the message: loud for none, cautious for thin, nothing when there is enough
let m = E.message(at({ rows: [], blur: [] }), 'morel');
check(m && m.title === 'No field evidence' && /Scores here come from the weather model alone/.test(m.body) && /unverified/.test(m.body), 'none message says so plainly');
check(m && /within 50 miles/.test(m.body), 'none message names the 50-mile circle (nothing near, so it was widened)');
m = E.message(at({ rows: many(15, 5), blur: [] }), 'morel');
check(m === null, 'no message when there is enough evidence');
m = E.message(at({ rows: many(1, 5), blur: [] }), 'morel');
check(m && m.title === 'Thin field evidence' && /Only 1 public report of morel/.test(m.body), 'thin message says one report, singular');
m = E.message(at({ rows: many(3, 5), blur: [] }), 'king bolete');
check(m && /Only 3 public reports of king bolete/.test(m.body), 'thin message says how many, plural');
check(E.message(null, 'morel') === null, 'no event, no message');
check(!/safe/i.test(E.message(at({ rows: [], blur: [] }), 'morel').body), 'the message never says safe');

if (fails.length) { fails.forEach((f) => console.log('FAIL: ' + f)); process.exit(1); }
console.log('ok');
