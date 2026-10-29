/** Plain words for what the engine returns. One place, so the demo, the method page and the docs agree. */
import type { Answers, Bother, Source, VerdictWord } from './types.ts';
import { VERDICTS } from './types.ts';

export const SOURCE_WORDS: Record<Source, { title: string; short: string }> = {
  street: { title: 'Street traffic', short: 'traffic' },
  nightlife: { title: 'Local businesses', short: 'local businesses' },
  building: { title: 'Neighbors', short: 'neighbors' },
  sirens: { title: 'Sirens', short: 'sirens' },
  construction: { title: 'Construction', short: 'construction' },
};

export const BOTHER_WORDS: Record<Bother, { label: string; hint: string }> = {
  traffic: { label: 'Traffic', hint: 'Buses, trucks, horns' },
  sirens: { label: 'Sirens', hint: 'Ambulances, fire, police' },
  neighbors: { label: 'Neighbors', hint: 'Footsteps, music, voices' },
  people: { label: 'Local businesses', hint: 'Bars, restaurants, theatres, crowds' },
  construction: { label: 'Construction', hint: 'Jackhammers, early crews' },
};

export const DEFAULT_ANSWERS: Answers = { sleep_from: 23, sleep_until: 7, day_bothers: true, bothers: [] };

export function hourLabel(h: number): string {
  if (h === 0) return 'midnight';
  if (h === 12) return 'noon';
  return h < 12 ? `${h} am` : `${h - 12} pm`;
}

export function sleepLabel(a: Pick<Answers, 'sleep_from' | 'sleep_until'>): string {
  return `${hourLabel(a.sleep_from)} to ${hourLabel(a.sleep_until)}`;
}

export function hoursAsleep(a: Pick<Answers, 'sleep_from' | 'sleep_until'>): number {
  return (a.sleep_until - a.sleep_from + 24) % 24;
}

export function listWords(items: string[]): string {
  if (items.length <= 1) return items.join('');
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
}

/** "For someone asleep 11 pm to 7 am, bothered by sirens." */
export function forWhom(a: Answers): string {
  const parts = [`For someone asleep ${sleepLabel(a)}`];
  if (a.bothers.length) parts.push(`bothered by ${listWords(a.bothers.map((b) => BOTHER_WORDS[b].label.toLowerCase()))}`);
  if (!a.day_bothers) parts.push('who does not mind daytime noise');
  return parts.join(', ') + '.';
}

export function verdictIndex(v: VerdictWord): number {
  return VERDICTS.indexOf(v);
}

export function pct(n: number): string {
  return `${Math.round(n)}%`;
}

export function ordinal(n: number): string {
  const s = ['th', 'st', 'nd', 'rd'];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

export function sideWords(side: 'front' | 'rear' | 'unknown'): string {
  return side === 'front' ? 'street side' : side === 'rear' ? 'rear' : 'side unknown';
}

/** "140 CLAREMONT AVENUE, New York, NY, USA" reads "140 Claremont Avenue, New York, NY". */
export function addressLine(label?: string, query?: string): string {
  const raw = (label || query || '').replace(/, USA$/, '');
  return raw.replace(/^([^,]+)/, (street) =>
    street.toLowerCase().replace(/\b([a-z])/g, (c) => c.toUpperCase()).replace(/\b(\d+)(St|Nd|Rd|Th)\b/g, (_, d, s) => d + s.toLowerCase()),
  );
}

const SIDE_WORDS: Record<string, string> = { street: 'Street side', rear: 'Rear', courtyard: 'Courtyard', corner: 'Corner', front: 'Street side' };

/** The reader's side value in words: "Street side", "Courtyard". */
export function sideLabel(side: string | null | undefined): string {
  return (side && SIDE_WORDS[side]) || 'Can’t tell';
}

const VIEW_WORDS: Record<string, string> = {
  street: 'The street', courtyard: 'A courtyard', rear_yards: 'Rear yards', airshaft: 'An airshaft', park: 'A park', water: 'Water', skyline: 'The skyline',
};
const AC_WORDS: Record<string, string> = { window: 'Window units', through_wall: 'Through-wall units', split: 'Ductless split', central: 'Central air' };

/** What the reader saw, typed as services/agent/CONTRACT.md types it, in words. */
export function observedLabel(key: string, value: unknown): string {
  if (value == null) return 'Can’t tell';
  if (key === 'windows' && typeof value === 'object') {
    const w = value as { floor_to_ceiling?: boolean; operable?: boolean | null };
    const open = w.operable === true ? ', they open' : w.operable === false ? ', fixed glass' : '';
    return `${w.floor_to_ceiling ? 'Floor-to-ceiling' : 'Standard windows'}${open}`;
  }
  const s = String(value);
  if (key === 'view') return VIEW_WORDS[s] ?? s;
  if (key === 'ac_units') return AC_WORDS[s] ?? s;
  return s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, ' ');
}

/**
 * A city-data line as the renter reads it. A liquor license's legal name is rarely the bar's and is sometimes a
 * person's, so "nearest loud: SOME LLC (bar), 139 LUDLOW ST, 18 m" reads "nearest loud: a bar at 139 LUDLOW ST, 18 m",
 * as the verdict writer does.
 */
export function cleanEvidence(line: string): string {
  return line.replace(/^nearest loud: .+? \(([a-z ]+)\), (.+)$/, (_, kind: string, rest: string) => `nearest loud: a ${kind} at ${rest}`);
}
