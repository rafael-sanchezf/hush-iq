// The why lines in "What informed your Hush score" (src/lib/reasons.ts): built by rules from the engine's own
// evidence, at most two per source, saying only what the evidence holds, the same with AI reading on or off.
// The evidence here is the engine's recorded output: four addresses without upgrades (v1 ingredients), and one with
// every engine v2 source upgrade (315 W 57th St). Nothing is copied from a listing.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { level, objectiveRank, sourceLines, streetName, tiles } from '../src/lib/reasons.ts';
import { BOTHER_WORDS, SOURCE_WORDS } from '../src/lib/words.ts';
import type { Field, Ingredient, Observed, ReaderFields, Score } from '../src/lib/types.ts';

const read = (p: string) => JSON.parse(readFileSync(new URL(p, import.meta.url), 'utf8'));
const v1 = (slug: string): { ingredients: Ingredient[] } => read(`../src/lib/mock/fixtures/${slug}.v1.json`);
const ev = (slug: string, name: Ingredient['name']) => v1(slug).ingredients.find((i) => i.name === name)!;
const W47: Score = read('./fixtures/v2-full-w47.json');

test('level words cut Manhattan in thirds', () => {
  assert.equal(level(0), 'Loud');
  assert.equal(level(33.3), 'Loud');
  assert.equal(level(33.4), 'Average');
  assert.equal(level(66.6), 'Average');
  assert.equal(level(66.7), 'Quiet');
  assert.equal(level(100), 'Quiet');
});

const W57 = read('./fixtures/v2-w57-two-units.json');
const up = (name: Ingredient['name']) => ({ name, evidence: W57.evidence[name] as string[] });
const UP = { groundFloorCommercial: W57.ground_floor_commercial as boolean };

// ---------------------------------------------------------------- with the upgrades: their facts lead

test('street with its upgrade: the main street, its lanes and its traffic, then buses and trucks', () => {
  assert.deepEqual(sourceLines(up('street')), [
    'West 57th St, four lanes, 31 m away: about 920 vehicles an hour by day and 330 at night, estimated from streets like it.',
    'About 25 buses an hour by day and 5 at night; a local truck route, about 6 in 100 daytime vehicles trucks.',
  ]);
  const counted = ['AMSTERDAM AVE: arterial, 4 travel lanes, 25 mph, bus or truck route, 110 m away',
    'NYC DOT counted about 1,400 vehicles an hour on Amsterdam Ave by day and about 450 an hour at night (2023 count).',
    'Amsterdam Ave is a through truck route.'];
  assert.deepEqual(sourceLines({ name: 'street', evidence: counted }), [
    'Amsterdam Ave, four lanes, 110 m away: about 1,400 vehicles an hour by day and 450 at night, counted by the city in 2023.',
    'A through truck route.',
  ]);
  assert.match(sourceLines({ name: 'street', evidence: ['Hudson River Greenway has no count on this block; the nearest count on the same street, 80 m away, and similar streets suggest about 40 vehicles an hour by day and 10 at night.'] })[0],
    /^Hudson River Greenway: about 40 vehicles an hour by day and 10 at night, estimated from a count 80 m along the street\.$/);
  assert.deepEqual(sourceLines({ name: 'street', evidence: ['Hudson River Greenway is a footpath or bike path with no motor traffic.'] }), ['Hudson River Greenway is a footpath or bike path with no motor traffic.']);
});

test('local businesses with the upgrade: places by kind, then late-night nights and outdoor dining', () => {
  const lines = sourceLines(up('nightlife'), UP);
  assert.deepEqual(lines, [
    'Shops or a bar on this building’s ground floor; 24 licensed places within 150 m: 4 bars, 14 restaurants and 6 other venues.',
    'Party, music or loud talking reported within 150 m on 26 of the last 730 nights, 10 pm to 5 am; 4 outdoor dining spots, the nearest 32 m away, open until 11 pm.',
  ]);
  for (const l of lines) assert.doesNotMatch(l, /LLC|INC|CORP/i);
  assert.deepEqual(sourceLines({ name: 'nightlife', evidence: ['0 licensed venues within 150 m', 'No outdoor dining, bar-style licence or reported late-night noise within 150 m.'] }), [
    'No licensed bars or restaurants within 150 m.',
    'No outdoor dining, bar-style licence or reported late-night noise within 150 m.',
  ]);
});

test('neighbors with the upgrade: complaints against the building type, then apartments per floor', () => {
  assert.deepEqual(sourceLines(up('building')), [
    '9 noise complaints about neighbors at this building in two years, across 284 apartments; elevator apartment buildings average 3 noise complaints per 100 apartments a year, against 6 for Manhattan.',
    'About 7 apartments share each floor; built 1965.',
  ]);
  assert.deepEqual(sourceLines({ name: 'building', evidence: ['About one apartment per floor.', '3 whole-apartment short-term rentals (under 30 nights) listed within about 150 m.'] }), [
    'About one apartment per floor.',
    '3 short-term rentals listed within about 150 m.',
  ]);
});

test('construction with the upgrade: active permits by kind and distance, then night work', () => {
  assert.deepEqual(sourceLines(up('construction')), [
    'A Con Ed street opening permit is active on a block 30 m away; four open loud-work permits on this block (general construction), the last running to December 2026.',
    'Night work allowed on 12 nights in the past year by an after-hours variance 100 m away.',
  ]);
  assert.deepEqual(sourceLines({ name: 'construction', evidence: ['No DOT street-work permits or after-hours variances within 100 m in the past year.'] }), [
    'No DOT street-work permits or after-hours variances within 100 m in the past year.',
  ]);
});

// ---------------------------------------------------------------- without the upgrades: the frozen lines alone

test('street: the street that matters most, then the complaints', () => {
  assert.deepEqual(sourceLines(ev('ludlow', 'street')), [
    'Essex St, four lanes, 54 m away, a bus or truck route.',
    '116 traffic noise complaints to 311 within 100 m in two years, most often car or truck music.',
  ]);
  // A tie on lanes goes to the nearest street.
  assert.match(sourceLines(ev('claremont', 'street'))[0], /^Claremont Ave, two lanes, 36 m away/);
  assert.equal(streetName('W  47 ST'), 'West 47th St');
  assert.equal(streetName('E 112 ST'), 'East 112th St');
  assert.equal(streetName('FDR DR'), 'FDR Dr');
});

test('local businesses: the nearest place by kind, never by its license name; ground-floor shops lead when there are some', () => {
  assert.deepEqual(sourceLines(ev('ludlow', 'nightlife')), [
    'A bar 18 m away is the nearest of 80 licensed places within 150 m: 22 bars, 34 restaurants and 24 other venues.',
    '1308 party or music complaints within 150 m in two years, 727 of them 10 pm to 5 am.',
  ]);
  const w47 = sourceLines(ev('w47', 'nightlife'), { groundFloorCommercial: true });
  assert.equal(w47[0], 'Shops or a bar on this building’s ground floor; 58 licensed places within 150 m: 12 bars, 25 restaurants and 21 other venues.');
  for (const l of [...w47, ...sourceLines(ev('ludlow', 'nightlife'))]) assert.doesNotMatch(l, /LLC|INC|CORP/i);
});

test('neighbors: complaints at the building, then how it is built', () => {
  assert.deepEqual(sourceLines(ev('claremont', 'building')), [
    '4 noise complaints about neighbors at this building in two years, across 61 apartments, most often banging or pounding.',
    'Built 1905, pre-war elevator building, masonry and plaster.',
  ]);
  assert.match(sourceLines(ev('w47', 'building'))[0], /^No noise complaints about neighbors/);
});


test('sirens: the routed emergency trips lead, then the nearest firehouse and hospital', () => {
  // The engine's own evidence for 315 W 57th St, with its sirens upgrade.
  assert.deepEqual(sourceLines(up('sirens')), [
    'About 45 ambulance trips a day on this block.',
    'A firehouse 292 m away and a hospital 364 m away.',
  ]);
  const stations = ['ENGINE 1 (firehouse), 1 MAIN STREET, 150 m', 'GENERAL (hospital), 2 MAIN STREET, 420 m'];
  assert.deepEqual(sourceLines({ name: 'sirens', evidence: [...stations, 'About 12 ambulance trips a day pass on this block.', 'About 3 fire engine runs a day use it too.'] }), [
    'About 12 ambulance trips and 3 fire engine runs a day on this block.',
    'A firehouse 150 m away and a hospital 420 m away.',
  ]);
  assert.deepEqual(sourceLines({ name: 'sirens', evidence: [...stations, 'About 20 ambulance trips a day pass on this block, most heading to a hospital about 400 m away.'] }), [
    'About 20 ambulance trips a day on this block, most heading to a hospital about 400 m away.',
    'A firehouse 150 m away.',
  ]);
  assert.deepEqual(sourceLines({ name: 'sirens', evidence: ['Almost no ambulance or fire engine trips pass this block.', 'The busiest street within 300 m carries about 120 emergency trips a day.'] }), [
    'Almost no ambulance or fire engine trips on this block; about 120 a day on the busiest street within 300 m.',
  ]);
});

test('sirens without route sentences (no upgrade, or no routed street within 500 m): the stations alone', () => {
  assert.deepEqual(sourceLines(ev('ludlow', 'sirens')), [
    'A hospital 275 m away and a firehouse 484 m away.',
    'Four emergency facilities within 600 m in all.',
  ]);
  assert.deepEqual(sourceLines(ev('w47', 'sirens')), ['A firehouse 132 m away and a police station 541 m away.']);
  for (const slug of ['bedford', 'claremont', 'ludlow', 'w47']) {
    for (const l of sourceLines(ev(slug, 'sirens'))) assert.doesNotMatch(l, /route|street|avenue|past/i, l);
  }
});

test('the bars show the objective rank: the same for every renter, floor and side; the verdict still differs', () => {
  const [low, high] = W57.units;
  assert.notEqual(low.verdict, high.verdict);
  const bars = (u: typeof low) => Object.fromEntries(u.ingredients.map((i: Ingredient) => [i.name, Math.round(objectiveRank(i).rank)]));
  assert.deepEqual(bars(low), { street: 10, nightlife: 31, building: 52, sirens: 11, construction: 46 });
  assert.deepEqual(bars(high), bars(low));
  assert.deepEqual(low.ingredients.map((i: Ingredient) => level(objectiveRank(i).rank)), high.ingredients.map((i: Ingredient) => level(objectiveRank(i).rank)));
  // A score without the field (the hosted API, the replay of v1) falls back to the renter's rank.
  assert.deepEqual(objectiveRank({ quieter_than: 40 }), { rank: 40, objective: false });
  assert.deepEqual(objectiveRank({ quieter_than: 40, block_quieter_than: 12 }), { rank: 12, objective: true });
});

test('nightlife reads "Local businesses" for the renter; the API key and the tick stay', () => {
  assert.equal(SOURCE_WORDS.nightlife.title, 'Local businesses');
  assert.deepEqual(BOTHER_WORDS.people, { label: 'Local businesses', hint: 'Bars, restaurants, theatres, crowds' });
  assert.equal(W57.units[0].ingredients.find((i: Ingredient) => i.name === 'nightlife').label, 'Local businesses');
  for (const slug of ['bedford', 'claremont', 'ludlow', 'w47']) {
    assert.equal(ev(slug, 'nightlife').label, 'Local businesses', slug);
  }
});

test('construction: the open permits on the block, then the complaints', () => {
  assert.deepEqual(sourceLines(ev('claremont', 'construction')), [
    'Two open loud-work permits on this block (structural, general construction), the last running to December 2026.',
    '2 construction noise complaints within 100 m in two years, most often work before or after hours.',
  ]);
});

test('every source of every recorded address gets one or two lines, the v2 score the same as its v1 ingredients', () => {
  for (const slug of ['bedford', 'claremont', 'ludlow', 'w47']) {
    for (const i of v1(slug).ingredients) {
      const lines = sourceLines(i);
      assert.ok(lines.length >= 1 && lines.length <= 2, `${slug} ${i.name}`);
      for (const l of lines) assert.match(l, /^[A-Z0-9].*\.$/, l);
    }
  }
  for (const i of W47.ingredients) assert.deepEqual(sourceLines(i), sourceLines(ev('w47', i.name)));
});

test('only what the evidence says: every number in a line is a number in that source’s evidence', () => {
  const nums = (t: string) => (t.match(/\d[\d,]*/g) ?? []).map((n) => n.replace(/,/g, ''));
  const cases: { name: Ingredient['name']; evidence: string[] }[] = [
    ...(Object.keys(W57.evidence) as Ingredient['name'][]).map(up),
    ...['bedford', 'claremont', 'ludlow', 'w47'].flatMap((slug) => v1(slug).ingredients),
  ];
  for (const c of cases) {
    const have = new Set(nums(c.evidence.join(' ')));
    for (const line of sourceLines(c, UP)) {
      for (const n of nums(line)) assert.ok(have.has(n), `${c.name}: ${n} in "${line}" is not in its evidence`);
    }
  }
});

test('missing evidence: a plain line, never an invented one', () => {
  assert.deepEqual(sourceLines({ name: 'street', evidence: [] }), ['The city data has nothing on this near the building.']);
  assert.deepEqual(sourceLines({ name: 'sirens', evidence: ['0 emergency facilities within 600 m'] }), ['No firehouse, hospital or police station within 600 m.']);
  assert.deepEqual(sourceLines({ name: 'nightlife', evidence: ['0 licensed venues within 150 m'] }), ['No licensed bars or restaurants within 150 m.']);
  // A line in a shape the rules do not know is shown as the city data has it.
  assert.deepEqual(sourceLines({ name: 'construction', evidence: ['crane on the corner lot'] }), ['Crane on the corner lot.']);
});

// ---------------------------------------------------------------- the tiles

const read_ = <T>(value: T, quote: string): Field<T> => ({ value, status: 'read', evidence: [{ source: 'text', quote }] });
const cant = <T>(): Field<T> => ({ value: null, status: 'cant_tell', evidence: [] });
const FIELDS: ReaderFields = {
  address: read_('310 West 47th Street', '310 West 47th Street'), unit: cant(), floor: read_(3, '3rd floor'), side: read_('street', 'faces 47th Street'),
};
const NO_PHOTOS: Observed = { view: cant(), windows: cant(), ac_units: cant(), wall_material: cant() };
const byKey = (t: ReturnType<typeof tiles>) => Object.fromEntries(t.map((x) => [x.key, x]));

test('tiles: known ones say where they came from', () => {
  const t = byKey(tiles(W47, FIELDS, NO_PHOTOS, { aiOff: false, photos: 0 }));
  assert.deepEqual(Object.keys(t), ['address', 'floor', 'side', 'building', 'windows', 'walls']);
  assert.deepEqual(t.floor.lines, ['Floor 3 of 7', 'From the listing: “3rd floor”']);
  assert.deepEqual(t.building.lines, ['City records: 7 floors, built 1910', '65 apartments.']);
  assert.ok(t.address.known && t.floor.known && t.side.known && t.building.known);
});

test('tiles: an open floor or side says what was assumed and what to ask', () => {
  const open: Score = {
    ...W47,
    unit: { ...W47.unit, floor: 4, floor_from: 'expected', side: 'unknown', side_from: 'unknown' } as Score['unit'],
    range: {
      loudest_case: { verdict: 'Loud', quieter_than: 52, floor: 2, side: 'front' },
      quietest_case: { verdict: 'Quiet', quieter_than: 71, floor: 6, side: 'rear' },
    } as Score['range'],
  };
  const t = byKey(tiles(open, { ...FIELDS, floor: cant(), side: cant() }, NO_PHOTOS, { aiOff: false, photos: 0 }));
  assert.equal(t.floor.known, false);
  assert.deepEqual(t.floor.lines, ['Not on the listing. Scored across floors 2 to 6.', 'Ask the broker which floor.']);
  assert.equal(t.side.known, false);
  assert.match(t.side.lines[1], /^Ask the broker/);
});

test('tiles: windows and walls come from the photos and are not scored yet; with AI reading off they are red', () => {
  const off = byKey(tiles(W47, FIELDS, NO_PHOTOS, { aiOff: true, photos: 0 }));
  assert.deepEqual(off.windows.lines, ['Not read: AI reading is off.', 'Not scored yet.']);
  assert.equal(off.walls.known, false);
  assert.deepEqual(byKey(tiles(W47, FIELDS, NO_PHOTOS, { aiOff: false, photos: 0 })).walls.lines, ['No photos read.', 'Not scored yet.']);

  const seen: Observed = {
    ...NO_PHOTOS,
    windows: { value: { floor_to_ceiling: true, operable: null }, status: 'read', evidence: [{ source: 'photo:2', what: 'floor-to-ceiling glass' }] },
  };
  const on = byKey(tiles(W47, FIELDS, seen, { aiOff: false, photos: 4 }));
  assert.equal(on.windows.known, true);
  assert.deepEqual(on.windows.lines, ['Floor-to-ceiling', 'Photo 3: floor-to-ceiling glass', 'Not scored yet.']);
  assert.deepEqual(on.walls.lines, ['Not in the photos or the text.', 'Not scored yet.']);
});

test('AI reading on or off: the same noise lines and the same first four tiles; only windows and walls change', () => {
  // The lines read the score, never the reader's mode: one result read by rules and one read by the model, on the
  // same score, show the same why for every source and for address, floor, side and building.
  const ctx = { groundFloorCommercial: W47.unit.ground_floor_commercial };
  assert.deepEqual(W47.ingredients.map((i) => sourceLines(i, ctx)), structuredClone(W47).ingredients.map((i: Ingredient) => sourceLines(i, ctx)));
  const off = tiles(W47, FIELDS, NO_PHOTOS, { aiOff: true, photos: 0 });
  const on = tiles(W47, FIELDS, NO_PHOTOS, { aiOff: false, photos: 4 });
  assert.deepEqual(off.slice(0, 4), on.slice(0, 4));
  assert.notDeepEqual(off[4].lines, on[4].lines);
});
