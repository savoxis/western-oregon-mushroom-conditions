/* Checks the page's shared ranking (window.ShroomRank in site/calcs.js) with tied fixtures. Run by tests/test_rank.py.
   usage: node rank_test.js PATH_TO_calcs.js     Prints one failure per line and exits 1 if there are any. */
'use strict';
const fs = require('fs');
const vm = require('vm');

const ctx = { dash: { calc() {} }, console };
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), ctx, { filename: 'calcs.js' });
const R = ctx.window.ShroomRank;
const fails = [];
const check = (ok, msg) => { if (!ok) fails.push(msg); };

const zone = (short, drive, score, raw, species, fc) => ({
  id: short, short, pdx_drive_h: drive,
  best: { species: species || 'chanterelle', score, score_raw: raw },
  rows: [{ species: species || 'chanterelle', score, score_raw: raw, fc: fc || [score, score - 1, score - 3, score - 6].join(','),
    fc_raw: raw === undefined || fc ? '' : [raw, raw - 1, raw - 3, raw - 6].map((x) => x.toFixed(2)).join(',') }],
});
const word = (k) => k.replace('_', ' ');

// the three lists for a set of zones: first zone in the headline, in "Best days this week" and in "Right now"
function firsts(zones) {
  const head = R.headline(zones, word);
  const items = zones.map((z) => ({ z, v: z.best.score, key: z.best.species, row: z.best }));
  const week = R.bestDays(items, (it) => it.z.rows[0].fc.split(',').map((x, i) => ({ t: i, v: +x, raw: R.rawDay(it.z.rows[0], i) })));
  const now = R.rankItems(items, (it) => R.rawScore(it.row));
  return { head, bestDays: week[0].it.z.short, now: now[0].z.short };
}
const headFirst = (head) => head.replace(/^\d+ zones? (is|are) in prime shape right now\. /, '').split(/,| and | lead| leads| tie| \(/)[0];

/* 1. three zones tie at 94 (same score, same unrounded score): the shorter drive wins everywhere */
let zs = [zone('Camas Valley', 3.5, 94, 94.4), zone('North Santiam', 1.75, 94, 94.4), zone('McKenzie Bridge', 2.75, 94, 94.4)];
let f = firsts(zs);
check(f.bestDays === 'North Santiam' && f.now === 'North Santiam' && headFirst(f.head) === 'North Santiam',
  'tie at 94: all three lists should put North Santiam (shortest drive) first, got ' + JSON.stringify(f));
check(f.head === '3 zones are in prime shape right now. North Santiam, McKenzie Bridge and Camas Valley lead: chanterelle at 94.', 'tie headline text: ' + f.head);

/* 2. the unrounded score beats the drive time */
zs = [zone('Camas Valley', 3.5, 94, 94.49), zone('North Santiam', 1.75, 94, 94.1), zone('McKenzie Bridge', 2.75, 94, 94.3)];
f = firsts(zs);
check(f.bestDays === 'Camas Valley' && f.now === 'Camas Valley' && headFirst(f.head) === 'Camas Valley', 'unrounded score should decide first: ' + JSON.stringify(f));

/* 3. same score and drive: name decides */
zs = [zone('Zeta', 2, 94, 94.2), zone('Alpha', 2, 94, 94.2), zone('Mid', 2, 94, 94.2)];
f = firsts(zs);
check(f.bestDays === 'Alpha' && f.now === 'Alpha' && headFirst(f.head) === 'Alpha', 'name should break the last tie: ' + JSON.stringify(f));

/* 4. headline wording */
check(R.headline([zone('A', 1, 94, 94.4)], word) === '1 zone is in prime shape right now. A leads: chanterelle at 94.', 'single leader text');
check(R.headline([zone('A', 1, 94, 94.4), zone('B', 2, 94, 94.4)], word) === '2 zones are in prime shape right now. A and B lead: chanterelle at 94.', 'two-way tie text');
zs = [zone('A', 1, 94, 94.4), zone('B', 2, 94, 94.3), zone('C', 3, 94, 94.2), zone('D', 4, 94, 94.1), zone('E', 5, 90, 90)];
check(R.headline(zs, word) === '5 zones are in prime shape right now. 4 zones tie at 94, led by A (chanterelle).', 'four-way tie text: ' + R.headline(zs, word));
check(R.headline([zone('A', 1, 94, 94.4, 'king_fall'), zone('B', 2, 94, 94.4, 'chanterelle')], word) === '2 zones are in prime shape right now. A (king fall) and B (chanterelle) lead at 94.', 'mixed-mushroom tie text: ' + R.headline([zone('A', 1, 94, 94.4, 'king_fall'), zone('B', 2, 94, 94.4, 'chanterelle')], word));
check(R.headline([zone('A', 1, 40, 40)], word) === 'No zone is in prime shape right now.', 'no prime zone text');
check(R.headline([zone('A', 1, 94, 94.4), zone('B', 2, 93, 93.9)], word) === '2 zones are in prime shape right now. A leads: chanterelle at 94.', 'a lead that is not shared is named alone');

/* 5. no unrounded score in older data: the rounded one is used and the tie-break still applies */
zs = [zone('Far', 3, 94, undefined), zone('Near', 1, 94, undefined)];
zs.forEach((z) => { delete z.best.score_raw; delete z.rows[0].score_raw; });
f = firsts(zs);
check(f.bestDays === 'Near' && f.now === 'Near' && headFirst(f.head) === 'Near', 'without unrounded scores the drive should still break the tie: ' + JSON.stringify(f));

/* 6. a later, higher day can legitimately put another zone first in "Best days this week" */
zs = [zone('Today', 1, 94, 94.4, 'chanterelle', '94,93,92,91'), zone('Later', 2, 90, 90.2, 'chanterelle', '90,92,96,95')];
const items = zs.map((z) => ({ z, v: z.best.score, key: z.best.species, row: z.best }));
const week = R.bestDays(items, (it) => it.z.rows[0].fc.split(',').map((x, i) => ({ t: i, v: +x, raw: R.rawDay(it.z.rows[0], i) })));
check(week[0].it.z.short === 'Later' && week[0].d.v === 96, 'a higher forecast day should still win "Best days this week"');

if (fails.length) { fails.forEach((m) => console.log('FAIL ' + m)); process.exit(1); }
console.log('ok');
