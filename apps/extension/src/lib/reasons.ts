/**
 * The why behind each noise source and each building tile in "What informed your Hush score", at most two plain
 * lines each (Rafa's design of 2026-10-29, HIQ-140).
 *
 * Built by rules from the engine's own evidence: `score.ingredients[].evidence`, `building_facts` and `unit`, plus
 * the reader's fields for the tiles. No model writes these, so they read the same with AI reading on or off, and
 * they say only what the evidence holds. A street is "a bus or truck route" because the city's street file says so,
 * never "heavy truck volume".
 *
 * Each source draws first on its engine v2 upgrade's sentences (packages/model/upgrades/*.md: traffic counts, buses,
 * truck routes; late-night complaint nights and outdoor dining; apartments per floor; street permits and night-work
 * variances; emergency trips routed past the block), joined to the frozen model's lines they belong with, loudest
 * facts first, two lines at most. Without an upgrade sentence a source falls back to the frozen lines alone.
 * A line in a shape this file does not know is skipped; when nothing for a source parses, its first line is shown
 * as the city data has it.
 *
 * Where /v2/score carries the upgrades' numbers (engine V12: `ingredients[].numbers`, and `routes` for sirens), the
 * numbers win over the sentences: vehicles, buses and truck share; complaint nights and outdoor dining; apartments
 * per floor; active street work and night-work variances; emergency trips on the nearest and the busiest street.
 * Names, kinds and how a count was made are only in the sentences, so those still come from there.
 */
import type { Field, Ingredient, Observed, ReaderFields, Score, SirenRoutes, SlotValue, Source, StepNumber } from './types.ts';
import { addressLine, cleanEvidence, observedLabel, sideLabel } from './words.ts';

// ---------------------------------------------------------------- the level word

export type Level = 'Loud' | 'Average' | 'Quiet';

/**
 * A source's rank in thirds of Manhattan, as a share of Manhattan apartments this one is quieter than: under a third
 * is Loud, a third to two thirds is Average, two thirds and over is Quiet. The card passes the objective rank
 * (`objectiveRank`), so the word is the same for every renter.
 */
export function level(quieterThan: number): Level {
  return quieterThan < 100 / 3 ? 'Loud' : quieterThan < 200 / 3 ? 'Average' : 'Quiet';
}

/**
 * The rank the bars show (Rafa, 2026-10-29): the building's typical apartment, all 24 hours equal, the same for every
 * renter (`block_quieter_than`, display only). The renter's answers, floor and side shape only the roll-up score.
 * A score without it (the hosted API until it serves /v2/score, and the replay of v1) falls back to `quieter_than`.
 */
export function objectiveRank(i: Pick<Ingredient, 'quieter_than' | 'block_quieter_than'>): { rank: number; objective: boolean } {
  return typeof i.block_quieter_than === 'number' && Number.isFinite(i.block_quieter_than)
    ? { rank: i.block_quieter_than, objective: true }
    : { rank: i.quieter_than, objective: false };
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

/**
 * A city street name the way the engine's upgrades write it, so the two can be matched: "W  47 ST" reads
 * "West 47th St", "ESSEX ST" reads "Essex St". A word with no vowel, like FDR, stays in capitals.
 */
export function streetName(raw: string): string {
  const toks = raw.trim().split(/\s+/);
  return toks.map((w, i) => {
    const up = w.toUpperCase();
    if (/^\d+$/.test(w)) {
      const n = Number(w);
      return `${n}${n % 100 >= 10 && n % 100 <= 20 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[n % 10] ?? 'th'}`;
    }
    if ((up === 'E' || up === 'W') && i === 0 && /^\d+$/.test(toks[1] ?? '')) return up === 'E' ? 'East' : 'West';
    if (STREET_ABBR[up]) return STREET_ABBR[up];
    if (w.length === 1 || !/[AEIOUY]/i.test(w)) return up;
    return up.charAt(0) + up.slice(1).toLowerCase();
  }).join(' ');
}

const sameStreet = (a: string, b: string) => a.toLowerCase() === b.toLowerCase();

/** A count a renter can read, rounded the way the engine's upgrades round theirs: to 100 from 1,000, 10 from 100, 5 from 20. */
export function roundCount(v: number): string {
  if (v >= 1000) return (Math.round(v / 100) * 100).toLocaleString('en-US');
  if (v >= 100) return String(Math.round(v / 10) * 10);
  if (v >= 20) return String(Math.round(v / 5) * 5);
  return String(Math.round(v));
}

/** What /v2/score says about a source in numbers, when it says it (engine V12). */
interface Facts {
  numbers: Record<string, StepNumber>;
  routes: SirenRoutes | null;
}

/** A step's value: a number, one slot of a per-slot value, or the sum of named counts. Null when it is not there. */
function num(f: Facts, key: string, slot?: keyof SlotValue): number | null {
  const v = f.numbers[key]?.value;
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  if (!v || typeof v !== 'object') return null;
  if (slot) return typeof (v as SlotValue)[slot] === 'number' ? (v as SlotValue)[slot] : null;
  const parts = Object.values(v).filter((x): x is number => typeof x === 'number');
  return parts.length ? parts.reduce((a, b) => a + b, 0) : null;
}

/** The radius a step's label names ("Street-work sites within 100 m"), or the given default. */
const radiusOf = (f: Facts, key: string, d: number) => Number(f.numbers[key]?.label.match(/within (\d+) m/)?.[1] ?? d);

/** The first two of a source's candidate lines, in the order given: loudest facts first. */
const firstTwo = (...lines: (string | null | undefined | false)[]) => lines.filter((l): l is string => Boolean(l)).slice(0, 2);

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

// ---------------------------------------------------------------- one source

/** Context the evidence lines do not carry. */
export interface SourceContext {
  /** PLUTO counts commercial units in the building: shops or a bar on the ground floor. */
  groundFloorCommercial?: boolean;
}

function street(ev: string[], _ctx: SourceContext, f: Facts): string[] {
  const streets: { name: string; lanes: number; route: boolean; m: number }[] = [];
  let complaints = '';
  let volume: { name: string; day: string; night: string; how: string } | null = null;
  let buses: { day: string; night: string | null } | null = null;
  let trucks: { label: string; share: string | null } | null = null;
  let plain = '';
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
      continue;
    }
    // The street upgrade (packages/model/upgrades/street.md): counts, buses and truck routes on the main street.
    m = e.match(/^NYC DOT counted about ([\d,]+) vehicles an hour on (.+) by day and about ([\d,]+) an hour at night \((\d{4}) count\)\.$/);
    if (m) {
      volume = { name: m[2], day: m[1], night: m[3], how: `, counted by the city in ${m[4]}` };
      continue;
    }
    m = e.match(/^(.+) has no count on this block; the nearest count on the same street, (\d+) m away, and similar streets suggest about ([\d,]+) vehicles an hour by day and ([\d,]+) at night\.$/);
    if (m) {
      volume = { name: m[1], day: m[3], night: m[4], how: `, estimated from a count ${m[2]} m along the street` };
      continue;
    }
    m = e.match(/^(.+) has no traffic count; streets like it carry about ([\d,]+) vehicles an hour by day and ([\d,]+) at night\.$/);
    if (m) {
      volume = { name: m[1], day: m[2], night: m[3], how: ', estimated from streets like it' };
      continue;
    }
    m = e.match(/^About ([\d,]+) buses an hour pass on .+ in the day(?: and ([\d,]+) at night)?\.$/);
    if (m) {
      buses = { day: m[1], night: m[2] ?? null };
      continue;
    }
    m = e.match(/^.+ is (a local truck route|a through truck route)(?:; about (\d+) in 100 daytime vehicles are trucks)?\.$/);
    if (m) {
      trucks = { label: m[1], share: m[2] ?? null };
      continue;
    }
    if (/^.+ is a footpath or bike path with no motor traffic\.$/.test(e) || /^No street lies within \d+ m of this point/.test(e)) plain = e;
  }
  // The street that matters most: the most lanes, a bus or truck route counting as one more, then the nearest.
  const main = [...streets].sort((a, b) => b.lanes + Number(b.route) - (a.lanes + Number(a.route)) || a.m - b.m)[0];
  const describe = (st: typeof main, m = st.m) => `${st.name}, ${words(st.lanes)} ${plural(st.lanes, 'lane')}, ${metres(m)} away`;
  // The numbers, when /v2/score has them, for the street the upgrade scored: the one its sentence names, or else the
  // street in the city's file nearest the distance it gives.
  const day = num(f, 'vehicles_per_hour', 'day');
  const dist = num(f, 'distance');
  if (day !== null) {
    const night = num(f, 'vehicles_per_hour', 'night');
    const near = dist !== null ? [...streets].sort((a, b) => Math.abs(a.m - dist) - Math.abs(b.m - dist))[0] : main;
    volume = { name: volume?.name ?? near?.name ?? 'The main street', day: roundCount(day), night: night !== null ? roundCount(night) : '', how: volume?.how ?? '' };
  }
  const busDay = num(f, 'buses_per_hour', 'day');
  if (busDay !== null) {
    const busNight = num(f, 'buses_per_hour', 'night');
    buses = busDay >= 1 ? { day: roundCount(busDay), night: busNight !== null && busNight >= 1 ? roundCount(busNight) : null } : null;
  }
  const share = num(f, 'truck_share', 'day');
  if (share !== null && share >= 1) trucks = { label: trucks?.label ?? '', share: String(Math.round(share)) };
  const counted = volume
    ? (() => {
      const st = streets.find((x) => sameStreet(x.name, volume!.name));
      return `${st ? describe(st, dist ?? st.m) : volume.name}: about ${volume.day} vehicles an hour by day${volume.night ? ` and ${volume.night} at night` : ''}${volume.how}.`;
    })()
    : null;
  const heavy = buses || trucks
    ? sentence([
      buses ? `about ${buses.day} buses an hour by day${buses.night ? ` and ${buses.night} at night` : ''}` : null,
      trucks ? [trucks.label, trucks.share ? `about ${trucks.share} in 100 daytime vehicles trucks` : ''].filter(Boolean).join(', ') : null,
    ].filter(Boolean).join('; '))
    : null;
  return firstTwo(
    counted ?? (main ? `${describe(main)}${main.route ? ', a bus or truck route' : ''}.` : null),
    plain,
    heavy,
    complaints,
  );
}

function nightlife(ev: string[], ctx: SourceContext, f: Facts): string[] {
  let venues: { n: number; within: string; kinds: string } | null = null;
  let nearest: { kind: string; m: number } | null = null;
  let complaints = '';
  let nights = '';
  let cafes = '';
  let cafeNear = '';
  let cafeClose = '';
  let none = '';
  for (const e of ev) {
    let m = e.match(/^(\d+) licensed venues within (\d+) m(?:: (.+))?$/);
    if (m) {
      // "4 bars, 14 restaurants, 6 venues" reads "4 bars, 14 restaurants and 6 other venues".
      const kinds = (m[3] ?? '').split(/,\s*/).filter(Boolean).map((k) => k.replace(/^(\d+) venues?$/, (_, n) => `${n} other ${Number(n) === 1 ? 'venue' : 'venues'}`));
      venues = { n: Number(m[1]), within: m[2], kinds: kinds.length > 1 ? `${kinds.slice(0, -1).join(', ')} and ${kinds[kinds.length - 1]}` : kinds.join('') };
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
      complaints = `${n ? n : 'no'} party or music ${plural(n, 'complaint')} within ${m[2]} m in ${span(Number(m[3]))}${n && late !== null ? `, ${late} of them 10 pm to 5 am` : ''}`;
      continue;
    }
    // The local-businesses upgrade (packages/model/upgrades/nightlife.md): nights with late complaints, outdoor dining.
    m = e.match(/^Neighbors reported a party, music or loud talking within (\d+) m on (\d+) of the last (\d+) nights between 10 pm and 5 am\.$/);
    if (m) {
      nights = `party, music or loud talking reported within ${m[1]} m on ${m[2]} of the last ${m[3]} nights, 10 pm to 5 am`;
      continue;
    }
    m = e.match(/^(\d+) licensed sidewalk or roadway dining spots? within (\d+) m \(nearest (\d+) m\); outdoor tables close at (\d+ [ap]m)\.$/);
    if (m) {
      cafes = `${m[1]} outdoor dining ${plural(Number(m[1]), 'spot')}, the nearest ${m[3]} m away, open until ${m[4]}`;
      cafeNear = m[3];
      cafeClose = m[4];
      continue;
    }
    if (/^No outdoor dining, bar-style licence or reported late-night noise within \d+ m\.$/.test(e)) none = e;
  }
  const count = venues
    ? venues.n
      ? `${venues.n} licensed ${plural(venues.n, 'place')} within ${venues.within} m${venues.kinds ? `: ${venues.kinds}` : ''}`
      : `no licensed bars or restaurants within ${venues.within} m`
    : '';
  const places = ctx.groundFloorCommercial
    ? `Shops or a bar on this building’s ground floor${count ? `; ${count}` : ''}.`
    : nearest && venues?.n
      ? `${cap(article(nearest.kind))} ${metres(nearest.m)} away is the nearest of ${count}.`
      : count
        ? sentence(count)
        : nearest
          ? `${cap(article(nearest.kind))} ${metres(nearest.m)} away.`
          : null;
  // Numbers first: nights a year with a late complaint (the 10 pm to 5 am slot), and outdoor dining by count.
  const lateNights = num(f, 'complaint_nights', 'night');
  if (lateNights !== null) {
    const r = radiusOf(f, 'complaint_nights', 150);
    nights = lateNights >= 0.5
      ? `party, music or loud-talking complaints within ${r} m on about ${Math.round(lateNights)} ${plural(Math.round(lateNights), 'night')} a year, 10 pm to 5 am`
      : `almost no nights with a late complaint within ${r} m`;
  }
  const outdoor = num(f, 'cafes');
  if (outdoor !== null) {
    cafes = outdoor >= 1
      ? `${outdoor} outdoor dining ${plural(outdoor, 'spot')} within ${radiusOf(f, 'cafes', 150)} m${cafeNear ? `, the nearest ${cafeNear} m away` : ''}${cafeClose ? `, open until ${cafeClose}` : ''}`
      : '';
  }
  const late = nights || cafes ? sentence([nights || complaints, cafes].filter(Boolean).join('; ')) : complaints ? sentence(complaints) : null;
  return firstTwo(places, late, none);
}

function neighbors(ev: string[], _ctx: SourceContext, f: Facts): string[] {
  let complaints = '';
  let built = '';
  let perFloor = '';
  let type = '';
  let shortStays = '';
  let kind: string | null = null;
  for (const e of ev) {
    let m = e.match(/^(\d+) residential noise complaints to 311 at this building in (\d+) months, (\d+) units: .+?(?: \(([^()]+ \d+(?:, [^()]+ \d+)*)\))?$/);
    if (m) {
      const n = Number(m[1]);
      complaints = `${n ? n : 'No'} noise ${plural(n, 'complaint')} about neighbors at this building in ${span(Number(m[2]))}, across ${m[3]} apartments`;
      kind = n ? topKind(m[4]) : null;
      continue;
    }
    m = e.match(/^built (\d{4})(?:: (.+))?$/);
    if (m) {
      built = `built ${m[1]}${m[2] ? `, ${m[2].replace(/[.\s]*$/, '')}` : ''}`;
      continue;
    }
    // The neighbors upgrade (packages/model/upgrades/building.md): apartments per floor, the building type's rate.
    m = e.match(/^About (one|\d+) apartments? (?:per floor|share each floor)\.$/);
    if (m) {
      perFloor = m[1] === 'one' ? 'about one apartment per floor' : `about ${m[1]} apartments share each floor`;
      continue;
    }
    m = e.match(/^Buildings of this type \((.+?)\) average (.+?) per 100 apartments a year; the Manhattan average is (.+?)\.$/);
    if (m) {
      type = `${m[1]} average ${m[2]} per 100 apartments a year, against ${m[3]} for Manhattan`;
      continue;
    }
    m = e.match(/^(\d+) whole-apartment short-term rentals? \(under 30 nights\) listed within about (\d+) m\.$/);
    if (m) shortStays = `${m[1]} short-term ${plural(Number(m[1]), 'rental')} listed within about ${m[2]} m`;
  }
  const upf = num(f, 'upf');
  if (upf !== null) {
    const typical = num(f, 'upf_typical');
    perFloor = upf < 1.5 ? 'about one apartment per floor' : `about ${Math.round(upf)} apartments share each floor`;
    if (typical !== null && Math.round(typical) !== Math.round(upf)) perFloor += `, against ${Math.round(typical)} in a typical Manhattan building`;
  }
  const stays = num(f, 'str_n');
  if (stays !== null) shortStays = stays >= 1 ? `${stays} short-term ${plural(stays, 'rental')} listed within about ${radiusOf(f, 'str_n', 150)} m` : '';
  return firstTwo(
    // With the building type's rate to compare against, that comparison says more than the commonest complaint.
    complaints ? sentence(type ? `${complaints}; ${type}` : `${complaints}${kind ? `, most often ${kind}` : ''}`) : type ? sentence(type) : null,
    perFloor || built ? sentence([perFloor, built].filter(Boolean).join('; ')) : null,
    shortStays ? sentence(shortStays) : null,
  );
}

/**
 * The sirens upgrade's own sentences, as packages/model/noise_score/upgrades/sirens.py writes them: trips a day on
 * this block by kind, or almost none and the busiest street within 300 m. /v2/score carries these sentences, not the
 * upgrade's numeric steps, so the busiest street is known only when the block itself is quiet.
 */
interface Routes {
  ambulance: number | null;
  /** Set when the upgrade says most of those ambulance trips head to a hospital this far away. */
  hospitalM: number | null;
  fire: number | null;
  quiet: boolean;
  busiest: { within: string; n: number } | null;
}

function routesOf(ev: string[]): Routes | null {
  const r: Routes = { ambulance: null, hospitalM: null, fire: null, quiet: false, busiest: null };
  let any = false;
  for (const e of ev) {
    let m = e.match(/^About (\d+) ambulance trips? a day pass(?:es)? on this block(?:, most heading to a hospital about (\d+) m away)?\.$/);
    if (m) {
      r.ambulance = Number(m[1]);
      r.hospitalM = m[2] ? Number(m[2]) : null;
      any = true;
      continue;
    }
    m = e.match(/^About (\d+) fire engine runs? a day uses? it(?: too)?\.$/);
    if (m) {
      r.fire = Number(m[1]);
      any = true;
      continue;
    }
    if (/^Almost no ambulance or fire engine trips pass this block\.$/.test(e)) {
      r.quiet = true;
      any = true;
      continue;
    }
    m = e.match(/^The busiest street within (\d+) m carries about (\d+) emergency trips a day\.$/);
    if (m) r.busiest = { within: m[1], n: Number(m[2]) };
  }
  return any ? r : null;
}

function routeLine(r: Routes): string {
  if (r.quiet) {
    return `Almost no ambulance or fire engine trips on this block${r.busiest ? `; about ${r.busiest.n} a day on the busiest street within ${r.busiest.within} m` : ''}.`;
  }
  const kinds = [
    r.ambulance !== null ? `${r.ambulance} ambulance ${plural(r.ambulance, 'trip')}` : null,
    r.fire !== null ? `${r.fire} fire engine ${plural(r.fire, 'run')}` : null,
  ].filter(Boolean);
  const toHospital = r.hospitalM !== null && r.fire === null ? `, most heading to a hospital about ${r.hospitalM} m away` : '';
  return `About ${kinds.join(' and ')} a day on this block${toHospital}.`;
}

/** The routes as numbers (engine V12): trips a day on the nearest street, then the busiest street within reach. */
function routeNumbers(r: SirenRoutes): string | null {
  if (!r.covered) return null;
  const ns = r.nearest_street;
  const total = ns ? ns.fire_per_day + ns.ambulance_per_day + ns.transport_per_day : 0;
  const b = r.busiest_street;
  const busiest = b && b.trips_per_day >= 0.5 && !(ns && b.name && ns.name === b.name)
    ? `; about ${roundCount(b.trips_per_day)} on ${b.name ?? 'the busiest street'}, the busiest within ${r.radius_m} m`
    : '';
  if (!ns || total < 0.5) return `Almost no emergency trips on ${ns?.name ?? 'this block'}${busiest}.`;
  const ambulances = ns.ambulance_per_day + ns.transport_per_day;
  const mostly = ambulances >= (2 / 3) * total ? ', most of them ambulances' : ns.fire_per_day >= (2 / 3) * total ? ', most of them fire engines' : '';
  return `About ${roundCount(total)} emergency trips a day on ${ns.name ?? 'this block'}${mostly}${busiest}.`;
}

function sirens(ev: string[], _ctx: SourceContext, f: Facts): string[] {
  if (f.routes) {
    const near = (['firehouse', 'hospital'] as const)
      .map((k) => (f.routes!.nearest[k] ? { kind: k, m: f.routes!.nearest[k]!.m } : null))
      .filter((p): p is { kind: 'firehouse' | 'hospital'; m: number } => Boolean(p))
      .sort((a, b) => a.m - b.m);
    const stations = near.length ? sentence(near.map((p) => `${article(p.kind)} ${metres(p.m)} away`).join(' and ')) : null;
    return firstTwo(routeNumbers(f.routes), stations);
  }
  return sirenSentences(ev);
}

function sirenSentences(ev: string[]): string[] {
  let total: { n: number; within: string } | null = null;
  const places: { kind: string; m: number }[] = [];
  let nearby = '';
  for (const e of ev) {
    let m = e.match(/^(\d+) emergency facilit(?:y|ies) within (\d+) m/);
    if (m) {
      total = { n: Number(m[1]), within: m[2] };
      continue;
    }
    m = e.match(/^.+ \(([a-z ]+)\), .+, ([\d.]+) m$/);
    if (m) {
      places.push({ kind: m[1], m: Number(m[2]) });
      continue;
    }
    if (/^Nearby: .+\.$/.test(e)) nearby = e;
  }
  places.sort((a, b) => a.m - b.m);
  const out: string[] = [];

  const routes = routesOf(ev);
  if (routes) {
    out.push(routeLine(routes));
    // With room left, the nearest firehouse and hospital: the stations those trips start from or head to.
    const fire = places.find((p) => p.kind === 'firehouse');
    const hospital = routes.hospitalM === null || routes.fire !== null ? places.find((p) => p.kind === 'hospital') : undefined;
    const near = [fire, hospital].filter((p): p is { kind: string; m: number } => Boolean(p)).sort((a, b) => a.m - b.m);
    if (near.length) out.push(sentence(near.map((p) => `${article(p.kind)} ${metres(p.m)} away`).join(' and ')));
    else if (nearby) out.push(nearby);
    return out;
  }

  // No route sentence: the stations' distances alone.
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

function construction(ev: string[], _ctx: SourceContext, f: Facts): string[] {
  let complaints = '';
  let block: { n: number; kinds: string } | null = null;
  let until = '';
  let street = '';
  let night = '';
  let sites = '';
  let none = '';
  let streetKind = '';
  let streetWhere = '';
  let nightWhere = '';
  for (const e of ev) {
    let m = e.match(/^(\d+) construction noise complaints within (\d+) m in (\d+) months(?: \((.+)\))?$/);
    if (m) {
      const n = Number(m[1]);
      const top = n ? topKind(m[4])?.replace(/^construction (before or after hours)$/, 'work $1') : null;
      complaints = `${n ? n : 'No'} construction noise ${plural(n, 'complaint')} within ${m[2]} m in ${span(Number(m[3]))}${top ? `, most often ${top}` : ''}.`;
      continue;
    }
    m = e.match(/^(\d+) unexpired loud-work permits? on this tax block(?:: (.+))?$/);
    if (m) {
      block = { n: Number(m[1]), kinds: (m[2] ?? '').split(/,\s*/).map((k) => k.replace(/\s+\d+$/, '').toLowerCase()).filter(Boolean).join(', ') };
      continue;
    }
    m = e.match(/^.+: .+ to (\d{4}-\d{2}-\d{2})$/);
    if (m) {
      if (m[1] > until) until = m[1];
      continue;
    }
    // The construction upgrade (packages/model/upgrades/construction.md): street permits, night-work variances.
    m = e.match(/^A (.+) permit is active ((?:on a block )?(?:within 10 m|\d+ m away))\.$/);
    if (m) {
      street = `a ${m[1]} permit is active ${m[2]}`;
      streetKind = m[1];
      streetWhere = m[2];
      continue;
    }
    m = e.match(/^An after-hours variance (within 10 m|\d+ m away) allowed night work on (\d+) nights in the past year(?:, with (\d+) more scheduled)?\.$/);
    if (m) {
      night = `Night work allowed on ${m[2]} nights in the past year by an after-hours variance ${m[1]}${m[3] ? `, with ${m[3]} more scheduled` : ''}.`;
      nightWhere = m[1];
      continue;
    }
    m = e.match(/^(\d+) street-work sites within (\d+) m in the past year(?:, (\d+) with night hours in the permit)?\.$/);
    if (m) {
      sites = `${m[1]} street-work ${plural(Number(m[1]), 'site')} within ${m[2]} m in the past year${m[3] ? `, ${m[3]} with night hours` : ''}.`;
      continue;
    }
    if (/^No DOT street-work permits or after-hours variances within \d+ m/.test(e)) none = e;
  }
  // Numbers first: street work active now and in the past year, night-work variances; kinds and places from the text.
  const active = num(f, 'street_active');
  const total = num(f, 'street_sites');
  const r = radiusOf(f, 'street_sites', 100);
  if (active !== null && active >= 1) {
    street = `${words(active)} street-work ${plural(active, 'site')} active within ${r} m${streetKind ? `, the nearest a ${streetKind} permit ${streetWhere}` : ''}`;
  } else if (active !== null) {
    street = '';
  }
  if (total !== null) {
    const nightSites = num(f, 'street_night_sites');
    sites = total >= 1 ? `${total} street-work ${plural(total, 'site')} within ${r} m in the past year${nightSites ? `, ${nightSites} with night hours` : ''}.` : '';
  }
  const ahvNights = num(f, 'ahv_nights');
  const ahvSites = num(f, 'ahv_sites');
  if (ahvNights !== null) {
    const by = ahvSites === 1 && nightWhere ? `an after-hours variance ${nightWhere}` : `${words(ahvSites ?? 0)} after-hours ${plural(ahvSites ?? 0, 'variance')} within ${radiusOf(f, 'ahv_sites', r)} m`;
    night = ahvNights >= 1 ? `Night work allowed on ${ahvNights} ${plural(ahvNights, 'night')} in the past year by ${by}.` : '';
  }
  const end = until ? `, the last running to ${MONTHS[Number(until.slice(5, 7)) - 1]} ${until.slice(0, 4)}` : '';
  const permits = block?.n ? `${words(block.n)} open loud-work ${plural(block.n, 'permit')} on this block${block.kinds ? ` (${block.kinds})` : ''}${end}` : '';
  // Active permits first, by kind and distance; then night work, the complaints, and street work in the past year.
  return firstTwo(
    street || permits ? sentence([street, permits].filter(Boolean).join('; ')) : null,
    night,
    complaints,
    sites,
    none,
  );
}

const RULES: Record<Source, (ev: string[], ctx: SourceContext, f: Facts) => string[]> = {
  street, nightlife, building: neighbors, sirens, construction,
};

/** At most two lines of why for one noise source, from its own evidence. */
export function sourceLines(i: Pick<Ingredient, 'name' | 'evidence' | 'numbers' | 'routes'>, ctx: SourceContext = {}): string[] {
  const ev = i.evidence ?? [];
  const facts: Facts = { numbers: i.numbers ?? {}, routes: i.routes ?? null };
  const lines = (RULES[i.name]?.(ev, ctx, facts) ?? []).slice(0, 2);
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
