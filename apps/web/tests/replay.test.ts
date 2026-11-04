// The browser replay of engine v2 (src/lib/replay/v2.ts) against the Python engine itself. The fixtures are
// engine v2's own output on the hosted v1 ingredients of four addresses, 30 random floors, sides and answers
// each, plus one full /v2/score from fresh pulls. Regenerate them when v2.py or config_v2.py change.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import type { Answers } from '../src/lib/types.ts';
import { scoreFromV1, scoreLevels, type Baseline, type Levels, type Unit, type V1Response } from '../src/lib/replay/v2.ts';

const read = (p: string) => JSON.parse(readFileSync(new URL(p, import.meta.url), 'utf8'));
const baseline: Baseline = read('../src/lib/replay/manhattan.json');
const parity = read('./fixtures/v2-parity.json');
const v1 = (slug: string): V1Response => read(`../src/lib/mock/fixtures/${slug}.v1.json`);

function neutralOf(d: V1Response): Levels {
  return Object.fromEntries(d.ingredients.map((i) => [i.name, i.levels])) as Levels;
}

test('replay matches engine v2 on every recorded case', () => {
  assert.ok(parity.cases.length >= 100);
  for (const c of parity.cases) {
    const d = v1(c.slug);
    const facts = { floors: d.unit.building_floors || null, commercial: Boolean(d.unit.ground_floor_commercial) };
    const got = scoreLevels(neutralOf(d), facts, c.unit as Unit, c.answers as Answers, baseline);
    const label = `${c.slug} ${JSON.stringify(c.unit)} ${JSON.stringify(c.answers)}`;
    assert.deepEqual(JSON.parse(JSON.stringify(got)), c.expected, label);
  }
});

test('replay builds the whole /v2/score shape', () => {
  const full = read('./fixtures/v2-full-w47.json');
  const answers: Answers = { sleep_from: 23, sleep_until: 7, day_bothers: true, bothers: ['traffic', 'sirens'] };
  const got = scoreFromV1(v1('w47'), { floor: 3, position: 'front' }, answers, baseline);
  const { replayed_from, ...rest } = JSON.parse(JSON.stringify(got));
  assert.equal(replayed_from, 'v1');
  for (const key of ['verdict', 'quieter_than', 'uncapped_verdict', 'caps', 'range', 'slot_weights', 'unit', 'manhattan', 'caveats']) {
    assert.deepEqual(rest[key], full[key], key);
  }
  assert.deepEqual(
    rest.ingredients.map((i: { name: string; quieter_than: number; verdict: string; weight: number; ticked: boolean }) =>
      [i.name, i.quieter_than, i.verdict, i.weight, i.ticked]),
    full.ingredients.map((i: { name: string; quieter_than: number; verdict: string; weight: number; ticked: boolean }) =>
      [i.name, i.quieter_than, i.verdict, i.weight, i.ticked]),
  );
});
