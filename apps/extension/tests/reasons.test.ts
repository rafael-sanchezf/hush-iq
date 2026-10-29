// The why lines in "What informed your Hush score" (src/lib/reasons.ts): built by rules from the engine's own
// evidence, at most two per source, saying only what the evidence holds, the same with AI reading on or off.
// The evidence here is the engine's recorded output for four addresses; nothing is copied from a listing.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { level, sourceLines, streetName, tiles } from '../src/lib/reasons.ts';
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

test('street: the street that matters most, then the complaints', () => {
  assert.deepEqual(sourceLines(ev('ludlow', 'street')), [
    'Essex St, four lanes, 54 m away, a bus or truck route.',
    '116 traffic noise complaints to 311 within 100 m in two years, most often car or truck music.',
  ]);
  // A tie on lanes goes to the nearest street.
  assert.match(sourceLines(ev('claremont', 'street'))[0], /^Claremont Ave, two lanes, 36 m away/);
  assert.equal(streetName('W  47 ST'), 'W 47 St');
  assert.equal(streetName('FDR DR'), 'FDR Dr');
});

test('nightlife: the nearest place by kind, never by its license name; ground-floor shops lead when there are some', () => {
  assert.deepEqual(sourceLines(ev('ludlow', 'nightlife')), [
    'A bar 18 m away, the nearest of 80 licensed places within 150 m, 22 of them bars.',
    '1308 party or music complaints within 150 m in two years, 727 of them 10 pm to 5 am.',
  ]);
  const w47 = sourceLines(ev('w47', 'nightlife'), { groundFloorCommercial: true });
  assert.equal(w47[0], 'Shops or a bar on this building’s ground floor; 58 licensed places within 150 m, 12 of them bars.');
  for (const l of [...w47, ...sourceLines(ev('ludlow', 'nightlife'))]) assert.doesNotMatch(l, /LLC|INC|CORP/i);
});

test('neighbors: complaints at the building, then how it is built', () => {
  assert.deepEqual(sourceLines(ev('claremont', 'building')), [
    '4 noise complaints about neighbors at this building in two years, across 61 apartments, most often banging or pounding.',
    'Built 1905: pre-war elevator building, masonry and plaster.',
  ]);
  assert.match(sourceLines(ev('w47', 'building'))[0], /^No noise complaints about neighbors/);
});

test('sirens: the facilities near the building, never a route past it', () => {
  assert.deepEqual(sourceLines(ev('ludlow', 'sirens')), [
    'A hospital 275 m away and a firehouse 484 m away.',
    'Four emergency facilities within 600 m in all.',
  ]);
  assert.deepEqual(sourceLines(ev('w47', 'sirens')), ['A firehouse 132 m away and a police station 541 m away.']);
  for (const slug of ['bedford', 'claremont', 'ludlow', 'w47']) {
    for (const l of sourceLines(ev(slug, 'sirens'))) assert.doesNotMatch(l, /route|street|avenue|past/i, l);
  }
});

test('construction: complaints, then the open permits on the block', () => {
  assert.deepEqual(sourceLines(ev('claremont', 'construction')), [
    '2 construction noise complaints within 100 m in two years, most often work before or after hours.',
    'Two open loud-work permits on this block, the last running to December 2026.',
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
