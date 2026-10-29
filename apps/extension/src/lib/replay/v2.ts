/**
 * Engine v2's ranking step, replayed in the browser. Used only while `/v2/score` is not deployed: it takes
 * the frozen model's facade-neutral levels from the hosted `/v1/score` (no floor, position front, no
 * profile, so position adds 0 dB) and ranks them against the frozen Manhattan sample exactly as
 * packages/model/noise_score/v2.py does (rules V1 to V8 in packages/model/ENGINE_V2.md). The output has the
 * `/v2/score` shape and is marked `replayed_from: "v1"`. tests/replay.test.ts holds it to the Python engine.
 *
 * Function names follow v2.py so the two read side by side. Decibels stay inside this file.
 */
import type { Answers, Cap, Ingredient, RangeCase, Score, ScoreAddress, Source, VerdictWord, Window } from '../types.ts';
import { SOURCES, VERDICTS, WINDOWS } from '../types.ts';

// ---------------------------------------------------------------- frozen numbers (config.py, config_v2.py)
const SLOT_HOURS: Record<Window, [number, number]> = { night: [22, 5], early: [5, 8], day: [8, 22] };
const FLOOR_DB_PER_FLOOR = -1.0;
const FLOOR_MAX_ATTENUATION_DB = -8.0;
const POSITION_DB: Record<string, number> = { front: 0.0, unknown: -2.0, rear: -8.0 };
const GROUND_FLOOR_COMMERCIAL_DB = 5.0;
const TOP_FLOOR_DB = -3.0;
const FIRST_FLOOR_DB = 2.0;
const ABOVE_COMMERCIAL_DB = 2.0;
const OUTDOOR: Source[] = ['street', 'nightlife', 'sirens', 'construction'];

const ASLEEP_HOUR_WEIGHT = 3.0;
const AWAKE_HOUR_WEIGHT = 1.0;
const AWAKE_HOUR_WEIGHT_NOT_BOTHERED = 0.5;
const SOURCE_WEIGHTS: Record<Source, number> = { street: 32, sirens: 20, building: 20, nightlife: 15, construction: 13 };
const TICKED_MULTIPLIER = 3.0;
const TICK_TO_SOURCE: Record<string, Source> = {
  traffic: 'street', people: 'nightlife', neighbors: 'building', sirens: 'sirens', construction: 'construction',
};
const ANY_SOURCE_CAP_PCT = 5.0;
const ANY_SOURCE_CAP_VERDICT: VerdictWord = 'Loud';
const TICKED_SOURCE_CAP_PCT = 10.0;
const TICKED_SOURCE_CAP_VERDICT: VerdictWord = 'Typical';
const EPS = 1e-6;

export const CAVEATS = [
  'Every number here is a rank against Manhattan, not a sound measurement.',
  'Each source is compared only with the same source elsewhere; the weights say which matters more.',
  '311 counts measure who complains, not how loud it is.',
  'Construction is temporary; permits expire.',
];

// ---------------------------------------------------------------- types
export type Levels = Record<Source, Record<Window, number>>;
export interface Facts { floors: number | null; commercial: boolean }
export interface Unit { floor: number | null; position: 'front' | 'rear' | 'unknown' }
export interface Sample { w: number; f: number | null; c: boolean; l: number[] }
export interface Baseline { as_of: string; apartments: number; samples: Sample[] }

/** Python's round(x, 1): half to even on exact binary ties, as `round` does. */
export function pyRound1(x: number): number {
  const t = x * 10;
  const fl = Math.floor(t);
  if (t - fl === 0.5) return (fl % 2 === 0 ? fl : fl + 1) / 10;
  return Math.round(t) / 10;
}

export function verdictFor(quieterThan: number): VerdictWord {
  return VERDICTS[Math.max(0, Math.min(Math.floor(quieterThan / 20), 4))];
}

function windowOf(hour: number): Window {
  for (const name of WINDOWS) {
    const [a, b] = SLOT_HOURS[name];
    if (a < b && a <= hour && hour < b) return name;
    if (a > b && (hour >= a || hour < b)) return name;
  }
  return 'day';
}

function asleep(hour: number, start: number, end: number): boolean {
  if (start === end) return false;
  return start > end ? hour >= start || hour < end : start <= hour && hour < end;
}

export function slotWeights(answers: Answers): Record<Window, number> {
  const awake = answers.day_bothers ? AWAKE_HOUR_WEIGHT : AWAKE_HOUR_WEIGHT_NOT_BOTHERED;
  const w: Record<Window, number> = { night: 0, early: 0, day: 0 };
  for (let h = 0; h < 24; h++) w[windowOf(h)] += asleep(h, answers.sleep_from, answers.sleep_until) ? ASLEEP_HOUR_WEIGHT : awake;
  const total = w.night + w.early + w.day;
  return { night: w.night / total, early: w.early / total, day: w.day / total };
}

export function sourceWeights(answers: Answers): { weights: Record<Source, number>; ticked: Set<Source> } {
  const ticked = new Set<Source>(answers.bothers.filter((t) => t in TICK_TO_SOURCE).map((t) => TICK_TO_SOURCE[t]));
  const raw = {} as Record<Source, number>;
  let total = 0;
  for (const n of SOURCES) {
    raw[n] = SOURCE_WEIGHTS[n] * (ticked.has(n) ? TICKED_MULTIPLIER : 1.0);
    total += raw[n];
  }
  const weights = {} as Record<Source, number>;
  for (const n of SOURCES) weights[n] = raw[n] / total;
  return { weights, ticked };
}

// ---------------------------------------------------------------- floor and side [V7]
function residentialFloors(facts: Facts): [number | null, number | null] {
  const floors = facts.floors;
  if (!floors) return [null, null];
  const low = facts.commercial && floors >= 2 ? 2 : 1;
  return [low, floors];
}

function expectedFloor(facts: Facts): number | null {
  const [low, top] = residentialFloors(facts);
  return low === null || top === null ? null : Math.floor((low + top) / 2 + 0.5);
}

function typicalUnit(facts: Facts): Unit {
  return { floor: expectedFloor(facts), position: 'unknown' };
}

function resolve(unit: Unit, facts: Facts): [Unit, 'listing' | 'expected', 'listing' | 'unknown'] {
  let floor = unit.floor;
  let floorFrom: 'listing' | 'expected' = 'listing';
  if (floor === null) {
    floor = expectedFloor(facts);
    floorFrom = 'expected';
  } else if (facts.floors) {
    floor = Math.min(floor, facts.floors);
  }
  const sideFrom = unit.position === 'front' || unit.position === 'rear' ? 'listing' : 'unknown';
  return [{ floor, position: sideFrom === 'listing' ? unit.position : 'unknown' }, floorFrom, sideFrom];
}

// ---------------------------------------------------------------- position, as baseline.position_db
function floorAttenuation(unit: Unit): number {
  if (!unit.floor || unit.floor <= 1) return 0.0;
  return Math.max(FLOOR_MAX_ATTENUATION_DB, FLOOR_DB_PER_FLOOR * (unit.floor - 1));
}

function positionDb(facts: Facts, unit: Unit): Record<Source, number> {
  const floors = facts.floors || 0;
  const f = unit.floor;
  const att = floorAttenuation(unit) + (POSITION_DB[unit.position] ?? POSITION_DB.unknown);
  const adj = { building: 0.0 } as Record<Source, number>;
  for (const n of OUTDOOR) adj[n] = att;
  if (facts.commercial && f && f <= 2) adj.nightlife += GROUND_FLOOR_COMMERCIAL_DB;
  if (f) {
    if (floors && f >= floors) adj.building += TOP_FLOOR_DB;
    if (f === 1) adj.building += FIRST_FLOOR_DB;
    if (f === 2 && facts.commercial) adj.building += ABOVE_COMMERCIAL_DB;
  }
  return adj;
}

function sourceLevels(neutral: Levels, facts: Facts, unit: Unit, slots: Record<Window, number>): Record<Source, number> {
  const adj = positionDb(facts, unit);
  const out = {} as Record<Source, number>;
  for (const n of SOURCES) {
    let v = 0;
    for (const s of WINDOWS) v += slots[s] * (neutral[n][s] + adj[n]);
    out[n] = v;
  }
  return out;
}

// ---------------------------------------------------------------- ranks
function bisectLeft(a: number[], x: number): number {
  let lo = 0, hi = a.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (a[mid] < x) lo = mid + 1; else hi = mid; }
  return lo;
}

function bisectRight(a: number[], x: number): number {
  let lo = 0, hi = a.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (x < a[mid]) hi = mid; else lo = mid + 1; }
  return lo;
}

/** Weighted "quieter than X%" against a fixed list of values. Ties count half. */
class Ranker {
  private values: number[];
  private cum: number[];
  private total: number;

  constructor(pairs: [number, number][]) {
    const sorted = [...pairs].sort((p, q) => p[0] - q[0] || p[1] - q[1]);
    this.values = sorted.map((p) => p[0]);
    this.cum = [0];
    for (const [, w] of sorted) this.cum.push(this.cum[this.cum.length - 1] + w);
    this.total = this.cum[this.cum.length - 1];
  }

  private split(value: number): [number, number, number] {
    const lo = bisectLeft(this.values, value - EPS);
    const hi = bisectRight(this.values, value + EPS);
    return [this.cum[lo], this.cum[hi] - this.cum[lo], this.total - this.cum[hi]];
  }

  quieterThanLevel(level: number): number {
    const [, ties, louder] = this.split(level);
    return (100 * (louder + ties / 2)) / this.total;
  }

  quieterThanRank(avg: number): number {
    const [lower, ties] = this.split(avg);
    return (100 * (lower + ties / 2)) / this.total;
  }
}

function sampleLevels(s: Sample): Levels {
  const out = {} as Levels;
  SOURCES.forEach((n, i) => {
    out[n] = { night: s.l[i * 3], early: s.l[i * 3 + 1], day: s.l[i * 3 + 2] };
  });
  return out;
}

/** [V4, V5] The fixed Manhattan for one set of answers: every sample building at a typical apartment. */
class Reference {
  slots: Record<Window, number>;
  weights: Record<Source, number>;
  perSource: Record<Source, Ranker>;
  averageRanker: Ranker;

  constructor(slots: Record<Window, number>, weights: Record<Source, number>, b: Baseline) {
    this.slots = slots;
    this.weights = weights;
    const rows = b.samples.map((s) => {
      const facts: Facts = { floors: s.f, commercial: s.c };
      return [sourceLevels(sampleLevels(s), facts, typicalUnit(facts), slots), s.w] as const;
    });
    this.perSource = {} as Record<Source, Ranker>;
    for (const n of SOURCES) this.perSource[n] = new Ranker(rows.map(([r, w]) => [r[n], w]));
    this.averageRanker = new Ranker(rows.map(([r, w]) => [this.average(this.ranks(r)), w]));
  }

  ranks(levels: Record<Source, number>): Record<Source, number> {
    const out = {} as Record<Source, number>;
    for (const n of SOURCES) out[n] = this.perSource[n].quieterThanLevel(levels[n]);
    return out;
  }

  average(ranks: Record<Source, number>): number {
    let v = 0;
    for (const n of SOURCES) v += this.weights[n] * ranks[n];
    return v;
  }
}

const refCache = new Map<string, Reference>();

function referenceFor(slots: Record<Window, number>, weights: Record<Source, number>, b: Baseline): Reference {
  const key = JSON.stringify([slots, weights, b.as_of, b.samples.length]);
  let ref = refCache.get(key);
  if (!ref) {
    ref = new Reference(slots, weights, b);
    if (refCache.size > 64) refCache.clear();
    refCache.set(key, ref);
  }
  return ref;
}

// ---------------------------------------------------------------- the verdict
function verdictOf(neutral: Levels, facts: Facts, unit: Unit, ref: Reference, ticked: Set<Source>) {
  const ranks = ref.ranks(sourceLevels(neutral, facts, unit, ref.slots));
  const quieterThan = ref.averageRanker.quieterThanRank(ref.average(ranks));
  const uncapped = verdictFor(quieterThan);
  const caps: Cap[] = [];
  for (const n of SOURCES) {
    if (ranks[n] <= ANY_SOURCE_CAP_PCT) {
      caps.push({ source: n, cap: ANY_SOURCE_CAP_VERDICT, why: `in Manhattan's loudest ${ANY_SOURCE_CAP_PCT}%`, applied: false });
    }
    if (ticked.has(n) && ranks[n] <= TICKED_SOURCE_CAP_PCT) {
      caps.push({
        source: n, cap: TICKED_SOURCE_CAP_VERDICT, applied: false,
        why: `you said it bothers you, and it is in Manhattan's loudest ${TICKED_SOURCE_CAP_PCT}%`,
      });
    }
  }
  const i = Math.min(VERDICTS.indexOf(uncapped), ...caps.map((c) => VERDICTS.indexOf(c.cap)));
  for (const c of caps) c.applied = VERDICTS.indexOf(c.cap) < VERDICTS.indexOf(uncapped);
  const rounded = {} as Record<Source, number>;
  for (const n of SOURCES) rounded[n] = pyRound1(ranks[n]);
  return { verdict: VERDICTS[i], uncapped_verdict: uncapped, quieter_than: pyRound1(quieterThan), caps, ranks: rounded };
}

function caseOf(neutral: Levels, facts: Facts, unit: Unit, ref: Reference, ticked: Set<Source>): RangeCase {
  const v = verdictOf(neutral, facts, unit, ref, ticked);
  return { verdict: v.verdict, quieter_than: v.quieter_than, floor: unit.floor, side: unit.position };
}

/** The v2 score from the decomposition alone, as v2.score_levels. */
export function scoreLevels(neutral: Levels, facts: Facts, unit: Unit, answers: Answers, b: Baseline) {
  const slots = slotWeights(answers);
  const { weights, ticked } = sourceWeights(answers);
  const ref = referenceFor(slots, weights, b);
  const [used, floorFrom, sideFrom] = resolve(unit, facts);
  const main = verdictOf(neutral, facts, used, ref, ticked);

  let range: Score['range'] = null;
  if (floorFrom !== 'listing' || sideFrom !== 'listing') {
    const [low, top] = residentialFloors(facts);
    const knownFloor = floorFrom === 'listing' ? used.floor : null;
    const knownSide = sideFrom === 'listing' ? used.position : null;
    const loud: Unit = { floor: knownFloor || low, position: knownSide || 'front' };
    const quiet: Unit = { floor: knownFloor || top, position: knownSide || 'rear' };
    range = { loudest_case: caseOf(neutral, facts, loud, ref, ticked), quietest_case: caseOf(neutral, facts, quiet, ref, ticked) };
  }

  const pct = <K extends string>(o: Record<K, number>) => {
    const out = {} as Record<K, number>;
    for (const k of Object.keys(o) as K[]) out[k] = pyRound1(100 * o[k]);
    return out;
  };
  return {
    verdict: main.verdict,
    quieter_than: main.quieter_than,
    uncapped_verdict: main.uncapped_verdict,
    caps: main.caps,
    range,
    ranks: main.ranks,
    weights: pct(weights),
    ticked: [...ticked].sort(),
    slot_weights: pct(slots),
    unit: {
      floor: used.floor,
      floor_from: used.floor !== null ? floorFrom : null,
      side: used.position,
      side_from: sideFrom,
      building_floors: facts.floors,
      ground_floor_commercial: facts.commercial,
    },
    manhattan: { buildings: b.samples.length, apartments: b.apartments, as_of: b.as_of },
  };
}

// ---------------------------------------------------------------- from a v1 response
export interface V1Ingredient {
  name: Source;
  label: string;
  levels: Record<Window, number>;
  evidence: string[];
  temporary: boolean;
}

export interface V1Response {
  address: ScoreAddress;
  unit: { building_floors: number | null; ground_floor_commercial: boolean };
  building_facts: Record<string, string | null> | null;
  ingredients: V1Ingredient[];
  as_of?: string;
  lookback_months?: number;
  sources?: { name: string; url: string }[];
}

/** A facade-neutral v1 response (no floor, position front, no profile) to the full `/v2/score` shape. */
export function scoreFromV1(v1: V1Response, unit: Unit, answers: Answers, b: Baseline): Score {
  const neutral = {} as Levels;
  for (const i of v1.ingredients) neutral[i.name] = { night: i.levels.night, early: i.levels.early, day: i.levels.day };
  const facts: Facts = { floors: v1.unit.building_floors || null, commercial: Boolean(v1.unit.ground_floor_commercial) };
  const core = scoreLevels(neutral, facts, unit, answers, b);
  const ingredients: Ingredient[] = v1.ingredients.map((i) => ({
    name: i.name,
    label: i.label,
    quieter_than: core.ranks[i.name],
    verdict: verdictFor(core.ranks[i.name]),
    weight: core.weights[i.name],
    ticked: core.ticked.includes(i.name),
    temporary: i.temporary,
    evidence: i.evidence,
  }));
  return {
    engine: 'v2',
    verdict: core.verdict,
    quieter_than: core.quieter_than,
    uncapped_verdict: core.uncapped_verdict,
    caps: core.caps,
    range: core.range,
    ingredients,
    answers: { sleep: { from: answers.sleep_from, until: answers.sleep_until }, day_bothers: answers.day_bothers, ticks: [...answers.bothers] },
    slot_weights: core.slot_weights,
    unit: core.unit,
    address: v1.address,
    building_facts: v1.building_facts,
    manhattan: core.manhattan,
    as_of: v1.as_of,
    lookback_months: v1.lookback_months,
    sources: v1.sources ?? [],
    caveats: CAVEATS,
    replayed_from: 'v1',
  };
}
