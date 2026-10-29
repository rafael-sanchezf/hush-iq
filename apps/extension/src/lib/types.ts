/**
 * Copied from the website (apps/web/src/lib/types.ts) so the two read the services alike; the one addition is
 * `ReadInput.photo_urls`.
 *
 * The shapes the site reads and sends. Score is engine v2's `/v2/score` response
 * (packages/model/noise_score/v2.py); Reader and Verdict follow the shared shapes each service documents in
 * its CONTRACT.md. Every number in a Score is a rank, a weight, a floor or a count: no decibels.
 */

export const SOURCES = ['street', 'nightlife', 'building', 'sirens', 'construction'] as const;
export type Source = (typeof SOURCES)[number];

export const VERDICTS = ['Very loud', 'Loud', 'Typical', 'Quiet', 'Very quiet'] as const;
export type VerdictWord = (typeof VERDICTS)[number];

export const WINDOWS = ['night', 'early', 'day'] as const;
export type Window = (typeof WINDOWS)[number];

/** What the renter ticks, in the v2 query's names. `people` is nightlife and street life. */
export const BOTHERS = ['traffic', 'sirens', 'neighbors', 'people', 'construction'] as const;
export type Bother = (typeof BOTHERS)[number];

/** The three taps. */
export interface Answers {
  sleep_from: number;
  sleep_until: number;
  day_bothers: boolean;
  bothers: Bother[];
}

// ---------------------------------------------------------------- score, engine v2

export interface Cap {
  source: Source;
  cap: VerdictWord;
  why: string;
  applied: boolean;
}

export interface RangeCase {
  verdict: VerdictWord;
  quieter_than: number;
  floor: number | null;
  side: 'front' | 'rear' | 'unknown';
}

export interface Ingredient {
  name: Source;
  label: string;
  quieter_than: number;
  verdict: VerdictWord;
  weight: number;
  ticked: boolean;
  temporary: boolean;
  evidence: string[];
}

export interface ScoreAddress {
  query?: string;
  label?: string;
  lat?: number;
  lng?: number;
  bbl?: string;
  bin?: string;
  borough?: string;
}

export interface Score {
  engine: 'v2';
  verdict: VerdictWord;
  quieter_than: number;
  uncapped_verdict: VerdictWord;
  caps: Cap[];
  range: { loudest_case: RangeCase; quietest_case: RangeCase } | null;
  ingredients: Ingredient[];
  answers: { sleep: { from: number; until: number }; day_bothers: boolean; ticks: string[] };
  slot_weights: Record<Window, number>;
  unit: {
    floor: number | null;
    floor_from: 'listing' | 'expected' | null;
    side: 'front' | 'rear' | 'unknown';
    side_from: 'listing' | 'unknown';
    building_floors: number | null;
    ground_floor_commercial: boolean;
  };
  address: ScoreAddress;
  building_facts: Record<string, string | null> | null;
  manhattan: { buildings: number; apartments: number; as_of: string };
  as_of?: string;
  lookback_months?: number;
  sources: { name: string; url: string }[];
  caveats: string[];
  /** Set by the site when the score was replayed in the browser from v1's ingredients (mock or fallback). */
  replayed_from?: 'v1';
}

// ---------------------------------------------------------------- reader

/** `start` and `end` are offsets into the text as sent (the live reader adds them). */
export type EvidenceRef = { source: 'text'; quote: string; start?: number; end?: number } | { source: `photo:${number}`; what: string };

export interface Field<T> {
  value: T | null;
  status: 'read' | 'cant_tell';
  evidence: EvidenceRef[];
}

/** As services/agent/CONTRACT.md: a cant_tell side has the value "unknown"; read `status`, not `value`. */
export type Side = 'street' | 'rear' | 'courtyard' | 'corner' | 'unknown';

export interface ReaderFields {
  address: Field<string>;
  unit: Field<string>;
  floor: Field<number>;
  side: Field<Side>;
}

export interface Windows {
  floor_to_ceiling: boolean;
  operable: boolean | null;
}

/** Typed by the reader: view, AC and walls are enums, windows an object. Shown, not scored. */
export interface Observed {
  view: Field<string>;
  windows: Field<Windows | string>;
  ac_units: Field<string>;
  wall_material: Field<string>;
}

export type TurnKind = 'read' | 'look' | 'tool' | 'check' | 'ask' | 'geocode' | 'score' | 'note';
export type TurnStatus = 'ok' | 'cant_tell' | 'refused' | 'error';

export interface ReaderTurn {
  i: number;
  kind: TurnKind;
  title: string;
  detail?: string;
  status?: TurnStatus;
  evidence?: EvidenceRef[];
  /** From the live reader: who chose the step, the tool, and how long it took. */
  by?: 'model' | 'code';
  tool?: string | null;
  ms?: number;
}

export interface ReaderResult {
  fields: ReaderFields;
  position: 'front' | 'rear' | 'unknown';
  observed: Observed;
  score: Score | Record<string, unknown> | null;
  trace: unknown[];
  /** The rest of the live reader's result; the replay fills what it can. */
  status?: 'complete' | 'partial';
  score_engine?: 'v2' | 'v1' | null;
  needs?: string[];
  notes?: string[];
  location?: ScoreAddress | null;
  model?: string;
  mode?: 'live' | 'mock';
}

export interface ReadInput {
  text: string;
  /** Data URLs, downscaled in the browser. */
  photos: string[];
  /**
   * Extension only, additive: listing photos the browser could not inline because their host does not allow
   * cross-origin reads, for the backend to fetch. Indexed after `photos`. The reader ignores it until it reads it.
   */
  photo_urls?: string[];
  answers?: Answers;
}

// ---------------------------------------------------------------- verdict

export interface EvidenceLine {
  id: string;
  text: string;
  kind?: string;
  source?: string | null;
}

export interface Sentence {
  text: string;
  cites: string[];
}

export interface Verdict {
  evidence: EvidenceLine[];
  sentences: Sentence[];
  writer: 'muse-spark-open' | 'muse-spark-1.3' | 'template' | string;
  /** Each attempt, so a fallback is never silent: `{writer, attempt, ok, errors, why, ms}`. */
  trace?: { writer: string; attempt?: number; ok: boolean; errors?: string[]; why?: string; ms?: number }[];
}

export interface VerdictInput {
  score: Score;
  answers: Answers;
  fields: ReaderFields;
}

// ---------------------------------------------------------------- the client

export interface Services {
  reader: 'live' | 'mock';
  verdict: 'live' | 'mock';
  score: 'v2' | 'v1-replay';
}
