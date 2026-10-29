/**
 * The why behind each noise source and each building tile in "What informed your Hush score", at most two plain
 * lines each (Rafa's design of 2026-10-29, HIQ-140).
 *
 * Built by rules from the engine's own evidence: `score.ingredients[].evidence`, `building_facts` and `unit`, plus
 * the reader's fields for the tiles. No model writes these, so they read the same with AI reading on or off, and
 * they say only what the evidence holds. A street is "a bus or truck route" because the city's street file says so,
 * never "heavy truck volume"; sirens name the facilities near the building, never a route past it, which waits for
 * HIQ-49.
 *
 * The evidence lines are the engine's (packages/model, frozen). A line in a shape this file does not know is
 * skipped; when nothing for a source parses, its first line is shown as the city data has it.
 */
import type { Field, Ingredient, Observed, ReaderFields, Score, Source } from './types.ts';
import { addressLine, cleanEvidence, observedLabel, sideLabel } from './words.ts';

// ---------------------------------------------------------------- the level word

export type Level = 'Loud' | 'Average' | 'Quiet';

/**
 * A source's rank in thirds of Manhattan. `quieter_than` is the share of Manhattan apartments this one is quieter
 * than: under a third is Loud, a third to two thirds is Average, two thirds and over is Quiet.
 */
export function level(quieterThan: number): Level {
  return quieterThan < 100 / 3 ? 'Loud' : quieterThan < 200 / 3 ? 'Average' : 'Quiet';
}

// ---------------------------------------------------------------- small words

const WORDS = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'];
const words = (n: number) => (Number.isInteger(n) && n >= 0 && n < WORDS.length ? WORDS[n] : String(n));
const Words = (n: number) => words(n).charAt(0).toUpperCase() + words(n).slice(1);
const plural = (n: number, one: string, many = `${one}s`) => (n === 1 ? one : many);
const article = (kind: string) => (/^[aeiou]/.test(kind) ? `an ${kind}` : `a ${kind}`);
const metres = (m: string | number) => `${Math.round(Number(m))} m`;
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const sentence = (s: string) => cap(s).replace(/[.;,\s]*$/, '.');

/** "24 months" as people say it. */
function span(months: number): string {
  return months % 12 === 0 ? `${words(months / 12)} ${plural(months / 12, 'year')}` : `${months} months`;
}

/** The first, largest kind in a city breakdown such as "(car/truck music 8, engine idling 5)", in plain words. */
function topKind(breakdown: string | undefined): string | null {
  const first = breakdown?.split(/,\s*/)[0]?.trim();
  if (!first) return null;
  return first
    .replace(/\s+\d+$/, '')
    .replace(/^noise:\s*/i, '')
    .replace(/\s*\([a-z]{1,3}\d\)\s*/gi, ' ')
    .replace(/\//g, ' or ')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase() || null;
}

const STREET_ABBR: Record<string, string> = { ST: 'St', AVE: 'Ave', AV: 'Ave', DR: 'Dr', PL: 'Pl', BLVD: 'Blvd', PKWY: 'Pkwy', RD: 'Rd', LN: 'Ln', SQ: 'Sq', HWY: 'Hwy', CT: 'Ct', TER: 'Ter', EXPY: 'Expy', EXPWY: 'Expwy' };

/** "W  47 ST" reads "W 47 St", "ESSEX ST" reads "Essex St"; a word with no vowel, like FDR, stays in capitals. */
export function streetName(raw: string): string {
  return raw.trim().split(/\s+/).map((w) => {
    const up = w.toUpperCase();
    if (STREET_ABBR[up]) return STREET_ABBR[up];
    if (/^\d/.test(w) || w.length === 1 || !/[AEIOUY]/i.test(w)) return up;
    return up.charAt(0) + up.slice(1).toLowerCase();
  }).join(' ');
}

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

// ---------------------------------------------------------------- one source

/** Context the evidence lines do not carry. */
export interface SourceContext {
  /** PLUTO counts commercial units in the building: shops or a bar on the ground floor. */
  groundFloorCommercial?: boolean;
}

function street(ev: string[]): string[] {
  const streets: { name: string; lanes: number; route: boolean; m: number }[] = [];
  let complaints = '';
  for (const e of ev) {
    let m = e.match(/^(.+?): [a-z ]+, (\d+) travel lanes?, \d+ mph, (bus or truck route, )?([\d.]+) m away$/);
    if (m) {
      streets.push({ name: streetName(m[1]), lanes: Number(m[2]), route: Boolean(m[3]), m: Number(m[4]) });
      continue;
    }
    m = e.match(/^(\d+) vehicle noise complaints to 311 within (\d+) m in (\d+) months(?: \((.+)\))?$/);
    if (m) {
      const n = Number(m[1]);
      const top = n ? topKind(m[4]) : null;
      complaints = `${n ? n : 'No'} traffic noise ${plural(n, 'complaint')} to 311 within ${m[2]} m in ${span(Number(m[3]))}${top ? `, most often ${top}` : ''}.`;
    }
  }
  const out: string[] = [];
  // The street that matters most: the most lanes, a bus or truck route counting as one more, then the nearest.
  const main = [...streets].sort((a, b) => b.lanes + Number(b.route) - (a.lanes + Number(a.route)) || a.m - b.m)[0];
  if (main) out.push(`${main.name}, ${words(main.lanes)} ${plural(main.lanes, 'lane')}, ${metres(main.m)} away${main.route ? ', a bus or truck route' : ''}.`);
  if (complaints) out.push(complaints);
  return out;
}

function nightlife(ev: string[], ctx: SourceContext): string[] {
  let venues: { n: number; within: string; bars: number } | null = null;
  let nearest: { kind: string; m: number } | null = null;
  let complaints = '';
  for (const e of ev) {
    let m = e.match(/^(\d+) licensed venues within (\d+) m(?:: (.+))?$/);
    if (m) {
      const bars = m[3]?.match(/(\d+) bars?\b/);
      venues = { n: Number(m[1]), within: m[2], bars: bars ? Number(bars[1]) : 0 };
      continue;
    }
    m = e.match(/^nearest loud: .+ \(([a-z ]+)\), .+, ([\d.]+) m$/);
    if (m) {
      if (!nearest || Number(m[2]) < nearest.m) nearest = { kind: m[1], m: Number(m[2]) };
      continue;
    }
    m = e.match(/^(\d+) party, music or loud-talking complaints within (\d+) m in (\d+) months(?:; (\d+) of them 10 pm to 5 am)?$/);
    if (m) {
      const n = Number(m[1]);
      const late = m[4] !== undefined ? Number(m[4]) : null;
      complaints = `${n ? n : 'No'} party or music ${plural(n, 'complaint')} within ${m[2]} m in ${span(Number(m[3]))}${n && late !== null ? `, ${late} of them 10 pm to 5 am` : ''}.`;
    }
  }
  const out: string[] = [];
  const count = venues
    ? venues.n
      ? `${venues.n} licensed ${plural(venues.n, 'place')} within ${venues.within} m${venues.bars ? `, ${venues.bars} of them ${plural(venues.bars, 'bar')}` : ''}`
      : `no licensed bars or restaurants within ${venues.within} m`
    : '';
  if (ctx.groundFloorCommercial) {
    out.push(`Shops or a bar on this building’s ground floor${count ? `; ${count}` : ''}.`);
  } else if (nearest && venues?.n) {
    out.push(`${cap(article(nearest.kind))} ${metres(nearest.m)} away, the nearest of ${count}.`);
  } else if (count) {
    out.push(sentence(count));
  } else if (nearest) {
    out.push(`${cap(article(nearest.kind))} ${metres(nearest.m)} away.`);
  }
  if (complaints) out.push(complaints);
  return out;
}

function neighbors(ev: string[]): string[] {
  const out: string[] = [];
  for (const e of ev) {
    let m = e.match(/^(\d+) residential noise complaints to 311 at this building in (\d+) months, (\d+) units: .+?(?: \(([^()]+ \d+(?:, [^()]+ \d+)*)\))?$/);
    if (m) {
      const n = Number(m[1]);
      const top = n ? topKind(m[4]) : null;
      out.unshift(`${n ? n : 'No'} noise ${plural(n, 'complaint')} about neighbors at this building in ${span(Number(m[2]))}, across ${m[3]} apartments${top ? `, most often ${top}` : ''}.`);
      continue;
    }
    m = e.match(/^built (\d{4}): (.+)$/);
    if (m) out.push(`Built ${m[1]}: ${m[2].replace(/[.\s]*$/, '')}.`);
  }
  return out;
}

function sirens(ev: string[]): string[] {
  let total: { n: number; within: string } | null = null;
  const places: { kind: string; m: number }[] = [];
  for (const e of ev) {
    let m = e.match(/^(\d+) emergency facilit(?:y|ies) within (\d+) m/);
    if (m) {
      total = { n: Number(m[1]), within: m[2] };
      continue;
    }
    m = e.match(/^.+ \(([a-z ]+)\), .+, ([\d.]+) m$/);
    if (m) places.push({ kind: m[1], m: Number(m[2]) });
  }
  places.sort((a, b) => a.m - b.m);
  const out: string[] = [];
  const shown = places.slice(0, 2).map((p) => `${article(p.kind)} ${metres(p.m)} away`);
  if (shown.length) out.push(sentence(shown.join(' and ')));
  if (total && total.n > shown.length) {
    out.push(shown.length
      ? `${Words(total.n)} emergency facilities within ${total.within} m in all.`
      : `${Words(total.n)} emergency ${plural(total.n, 'facility', 'facilities')} within ${total.within} m.`);
  } else if (total && total.n === 0) {
    out.push(`No firehouse, hospital or police station within ${total.within} m.`);
  }
  return out;
}

function construction(ev: string[]): string[] {
  const out: string[] = [];
  let permits: { n: number } | null = null;
  let until = '';
  for (const e of ev) {
    let m = e.match(/^(\d+) construction noise complaints within (\d+) m in (\d+) months(?: \((.+)\))?$/);
    if (m) {
      const n = Number(m[1]);
      const top = n ? topKind(m[4])?.replace(/^construction (before or after hours)$/, 'work $1') : null;
      out.unshift(`${n ? n : 'No'} construction noise ${plural(n, 'complaint')} within ${m[2]} m in ${span(Number(m[3]))}${top ? `, most often ${top}` : ''}.`);
      continue;
    }
    m = e.match(/^(\d+) unexpired loud-work permits? on this tax block/);
    if (m) {
      permits = { n: Number(m[1]) };
      continue;
    }
    m = e.match(/^.+: .+ to (\d{4}-\d{2}-\d{2})$/);
    if (m && m[1] > until) until = m[1];
  }
  if (permits?.n) {
    const end = until ? `, the last running to ${MONTHS[Number(until.slice(5, 7)) - 1]} ${until.slice(0, 4)}` : '';
    out.push(`${Words(permits.n)} open loud-work ${plural(permits.n, 'permit')} on this block${end}.`);
  }
  return out;
}

const RULES: Record<Source, (ev: string[], ctx: SourceContext) => string[]> = {
  street, nightlife, building: neighbors, sirens, construction,
};

/** At most two lines of why for one noise source, from its own evidence. */
export function sourceLines(i: Pick<Ingredient, 'name' | 'evidence'>, ctx: SourceContext = {}): string[] {
  const ev = i.evidence ?? [];
  const lines = (RULES[i.name]?.(ev, ctx) ?? []).slice(0, 2);
  if (lines.length) return lines;
  if (ev.length) return [sentence(cleanEvidence(ev[0]))];
  return ['The city data has nothing on this near the building.'];
}

// ---------------------------------------------------------------- the building tiles

export type TileKey = 'address' | 'floor' | 'side' | 'building' | 'windows' | 'walls';

export interface Tile {
  key: TileKey;
  label: string;
  /** False: not on the listing (or not read), shown red. */
  known: boolean;
  lines: string[];
}

export interface TileContext {
  /** True when AI reading was off for this result: no photo was read. */
  aiOff: boolean;
  /** How many photos the reader was sent. */
  photos: number;
}

/** Where a reader field came from: the listing's words, or "Photo N: what it saw". */
function source(f: Field<unknown>): string | null {
  const e = f.evidence[0];
  if (!e) return null;
  if (e.source === 'text') return `From the listing: “${e.quote}”`;
  const n = Number(e.source.split(':')[1]);
  return `Photo ${Number.isFinite(n) ? n + 1 : ''}: ${e.what}`;
}

/** Address, Floor, Side, Building, Windows and Walls: known or not, and the hover lines for each. */
export function tiles(score: Score, fields: ReaderFields, observed: Observed, ctx: TileContext): Tile[] {
  const unit = score.unit;
  const facts = score.building_facts;
  const where = addressLine(score.address.label, score.address.query);
  const floors = [score.range?.loudest_case.floor, score.range?.quietest_case.floor].filter((f): f is number => typeof f === 'number');
  const lo = floors.length ? Math.min(...floors) : null;
  const hi = floors.length ? Math.max(...floors) : null;

  const address: Tile = fields.address.status === 'read'
    ? { key: 'address', label: 'Address', known: true, lines: [where, source(fields.address) ?? 'From the listing.'] }
    : { key: 'address', label: 'Address', known: false, lines: [`Not on the listing. Scored at ${where}.`, 'Ask the broker to confirm the address.'] };

  const floorKnown = unit.floor_from === 'listing';
  const floor: Tile = floorKnown
    ? {
      key: 'floor', label: 'Floor', known: true,
      lines: [`Floor ${unit.floor}${unit.building_floors ? ` of ${unit.building_floors}` : ''}`,
        fields.floor.derived?.from === 'unit' ? `From unit ${fields.floor.derived.unit}: the listing does not state the floor.` : source(fields.floor) ?? 'From the listing.'],
    }
    : {
      key: 'floor', label: 'Floor', known: false,
      lines: [lo !== null && hi !== null && hi > lo
        ? `Not on the listing. Scored across floors ${lo} to ${hi}.`
        : `Not on the listing. Scored at ${unit.floor ? `floor ${unit.floor}, ` : ''}the middle of the building.`, 'Ask the broker which floor.'],
    };

  const sideKnown = unit.side_from === 'listing';
  const side: Tile = sideKnown
    ? { key: 'side', label: 'Side', known: true, lines: [sideLabel(fields.side.status === 'read' ? fields.side.value : unit.side), source(fields.side) ?? 'From the listing.'] }
    : { key: 'side', label: 'Side', known: false, lines: ['Not on the listing. Scored between street side and rear.', 'Ask the broker whether it faces the street.'] };

  const record = [unit.building_floors ? `${unit.building_floors} floors` : null, facts?.yearbuilt ? `built ${facts.yearbuilt}` : null].filter(Boolean).join(', ');
  const building: Tile = record
    ? { key: 'building', label: 'Building', known: true, lines: [`City records: ${record}`, ...(facts?.unitsres ? [`${facts.unitsres} apartments.`] : [])] }
    : { key: 'building', label: 'Building', known: false, lines: ['Not in the city’s lot records.', 'Ask the broker how many floors it has and when it was built.'] };

  // Windows and walls come from the reader's photo observations, which reach the score only after the photo test.
  const photoTile = (key: 'windows' | 'walls', label: string, f: Field<unknown>, labelKey: string): Tile => {
    if (f.status === 'read') return { key, label, known: true, lines: [observedLabel(labelKey, f.value), source(f) ?? '', 'Not scored yet.'].filter(Boolean) };
    const why = ctx.aiOff ? 'Not read: AI reading is off.' : ctx.photos ? 'Not in the photos or the text.' : 'No photos read.';
    return { key, label, known: false, lines: [why, 'Not scored yet.'] };
  };

  return [address, floor, side, building,
    photoTile('windows', 'Windows', observed.windows as Field<unknown>, 'windows'),
    photoTile('walls', 'Walls', observed.wall_material as Field<unknown>, 'wall_material')];
}
