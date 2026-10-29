/** Plain words for what the engine returns. One place, so the demo, the method page and the docs agree. */
import type { Answers, Bother, Source, VerdictWord } from './types.ts';
import { VERDICTS } from './types.ts';

export const SOURCE_WORDS: Record<Source, { title: string; short: string }> = {
  street: { title: 'Street traffic', short: 'traffic' },
  nightlife: { title: 'Bars and nightlife', short: 'nightlife' },
  building: { title: 'Neighbors', short: 'neighbors' },
  sirens: { title: 'Sirens', short: 'sirens' },
  construction: { title: 'Construction', short: 'construction' },
};

export const BOTHER_WORDS: Record<Bother, { label: string; hint: string }> = {
  traffic: { label: 'Traffic', hint: 'Buses, trucks, horns' },
  sirens: { label: 'Sirens', hint: 'Ambulances, fire, police' },
  neighbors: { label: 'Neighbors', hint: 'Footsteps, music, voices' },
  people: { label: 'Nightlife', hint: 'Bars, crowds, late talk' },
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
