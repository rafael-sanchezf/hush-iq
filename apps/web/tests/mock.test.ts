// The replay reader and the template verdict keep the same rule as the live services: every field read is a
// quoted span of the listing, and every citation points at an evidence line that was sent.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { checkCitations } from '../src/lib/cite.ts';
import { normalizeTurn } from '../src/lib/turns.ts';
import { extract } from '../src/lib/mock/extract.ts';
import { SAMPLES } from '../src/lib/mock/listings.ts';
import { templateVerdict } from '../src/lib/mock/verdict.ts';
import { scoreFromV1, type Baseline, type V1Response } from '../src/lib/replay/v2.ts';
import type { Answers, Field } from '../src/lib/types.ts';

const read = (p: string) => JSON.parse(readFileSync(new URL(p, import.meta.url), 'utf8'));
const baseline: Baseline = read('../src/lib/replay/manhattan.json');
const sample = (id: string) => SAMPLES.find((s) => s.id === id)!.text;

function quoted(text: string, f: Field<unknown>, key = '') {
  if (f.status === 'cant_tell') {
    assert.equal(f.value, key === 'side' ? 'unknown' : null);
    assert.equal(f.evidence.length, 0);
    return;
  }
  assert.ok(f.evidence.length > 0);
  for (const e of f.evidence) {
    assert.equal(e.source, 'text');
    if (e.source === 'text') assert.ok(text.includes(e.quote), `quote not in the listing: ${e.quote}`);
  }
}

test('every field read from a sample is a quoted span of it', () => {
  for (const s of SAMPLES) {
    const x = extract(s.text);
    for (const [k, f] of [...Object.entries(x.fields), ...Object.entries(x.observed)]) quoted(s.text, f as Field<unknown>, k);
  }
});

test('the samples read as written', () => {
  const c = extract(sample('claremont'));
  assert.equal(c.geocode, '140 Claremont Avenue, New York');
  assert.equal(c.fields.unit.value, '4C');
  assert.equal(c.fields.floor.value, 4);
  assert.equal(c.fields.side.status, 'cant_tell');
  assert.equal(c.observed.wall_material.value, 'brick');
  assert.equal(c.observed.windows.status, 'cant_tell');
  assert.ok(c.ignored.includes('quiet'));

  const w = extract(sample('w47'));
  assert.equal(w.geocode, '310 West 47th Street, New York');
  assert.equal(w.fields.unit.value, '3F');
  assert.equal(w.fields.floor.value, 3);
  assert.equal(w.fields.side.value, 'street');
  assert.equal(w.position, 'front');
  assert.equal(w.observed.ac_units.value, 'through_wall');
  assert.equal(w.observed.view.value, 'street');

  const b = extract(sample('bedford'));
  assert.equal(b.geocode, '158 Bedford Avenue, Brooklyn');
  assert.equal(b.fields.floor.status, 'cant_tell');
  assert.equal(b.fields.side.status, 'cant_tell');
  assert.equal(b.observed.ac_units.value, 'window');
});

test('a listing with no address is can’t tell, and a conflicting side is not guessed', () => {
  const x = extract('Lovely studio, 5th floor, faces the courtyard and also faces the street.');
  assert.equal(x.fields.address.status, 'cant_tell');
  assert.equal(x.geocode, null);
  assert.equal(x.fields.floor.value, 5);
  assert.equal(x.fields.side.status, 'cant_tell');
  assert.ok(x.sideConflict);
});

test('the template cites only evidence it built, for every sample and answer set', () => {
  const answerSets: Answers[] = [
    { sleep_from: 23, sleep_until: 7, day_bothers: true, bothers: [] },
    { sleep_from: 2, sleep_until: 10, day_bothers: false, bothers: ['people'] },
    { sleep_from: 22, sleep_until: 6, day_bothers: true, bothers: ['traffic', 'sirens', 'construction'] },
  ];
  for (const slug of ['claremont', 'w47', 'bedford', 'ludlow']) {
    const v1: V1Response = read(`../src/lib/mock/fixtures/${slug}.v1.json`);
    const text = SAMPLES.find((s) => s.id === slug)?.text ?? 'Studio at 140 Ludlow Street, 2nd floor.';
    const x = extract(text);
    for (const answers of answerSets) {
      const score = scoreFromV1(v1, { floor: x.fields.floor.value, position: x.position }, answers, baseline);
      const v = templateVerdict({ score, answers, fields: x.fields });
      assert.ok(v.sentences.length >= 2);
      const { dropped } = checkCitations(v);
      assert.equal(dropped, 0, `${slug}: a sentence cites a line that was not sent`);
      for (const s of v.sentences) assert.ok(s.cites.length > 0, `${slug}: uncited sentence: ${s.text}`);
    }
  }
});

test('the live reader’s turns read as panel steps', () => {
  const refused = normalizeTurn({ n: 2, by: 'model', tool: 'submit_listing', ok: false, ms: 2140,
    result: { error: 'refused', refused: { side: 'no quote states it' }, accepted: ['address', 'floor'] } }, 0);
  assert.equal(refused.status, 'refused');
  assert.equal(refused.kind, 'check');
  assert.match(refused.title, /refused side/);
  assert.match(refused.detail ?? '', /no quote states it/);
  assert.equal(refused.i, 2);
  assert.equal(refused.ms, 2140);

  const score = normalizeTurn({ n: 4, by: 'code', tool: 'score', ok: true, result: { engine: 'v2', verdict: 'Very loud', quieter_than: 0.4, range: null } }, 0);
  assert.equal(score.kind, 'score');
  assert.match(score.detail ?? '', /Very loud: quieter than 0%/);

  const photo = normalizeTurn({ n: 1, by: 'model', tool: 'read_photo', ok: true, args: { indexes: [0, 2] }, result: {} }, 0);
  assert.equal(photo.title, 'Looked at photos 1, 3');

  const said = normalizeTurn({ n: 3, by: 'model', tool: null, ok: true, said: 'I need the photos.' }, 0);
  assert.equal(said.kind, 'note');

  const mine = normalizeTurn({ i: 5, kind: 'geocode', title: 'Found the building' }, 0);
  assert.equal(mine.title, 'Found the building');
});
