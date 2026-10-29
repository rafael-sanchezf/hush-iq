/**
 * The replay reader's rules for pasted listing text. Every field it reads carries the exact span of the text
 * it came from; anything it cannot find is "can't tell". Adjectives are collected so the reader can say it
 * ignored them.
 */
import type { Field, Observed, ReaderFields } from '../types.ts';

const STREET_TYPES = 'Street|St|Avenue|Ave|Place|Pl|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Terrace|Ter|Square|Sq|Parkway|Pkwy|Court|Ct';
const ORDINAL_AVE = 'First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth|Ninth|Tenth|Eleventh|Twelfth';
const ADDRESS = new RegExp(
  `\\b\\d{1,5}(?:-\\d{1,4})?\\s+(?:` +
    `(?:(?:East|West|North|South|E|W|N|S)\\.?\\s+)?(?:\\d{1,3}(?:st|nd|rd|th)?|[A-Z][A-Za-z']*(?:\\s+[A-Z][A-Za-z']*){0,2})\\s+(?:${STREET_TYPES})\\b\\.?` +
    `|Broadway\\b|Bowery\\b|Avenue\\s+[A-D]\\b|(?:${ORDINAL_AVE})\\s+Avenue\\b)`,
);
const BOROUGH = /^,\s*(New York|Manhattan|Brooklyn|Queens|Bronx|The Bronx|Staten Island)\b/;
const UNIT = /(?:\bApt\.?|\bApartment|\bUnit|#)\s?([0-9]{1,3}[A-Z]{0,2}|[A-Z]{1,2}[0-9]{0,3})\b/;

const FLOOR_WORDS: Record<string, number> = {
  ground: 1, first: 1, second: 2, third: 3, fourth: 4, fifth: 5, sixth: 6, seventh: 7, eighth: 8, ninth: 9,
  tenth: 10, eleventh: 11, twelfth: 12,
};
const FLOOR_PATTERNS: [RegExp, (m: RegExpMatchArray) => number][] = [
  [/\b(ground|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth)[ -]floor\b/i, (m) => FLOOR_WORDS[m[1].toLowerCase()]],
  [/\b(\d{1,2})(?:st|nd|rd|th)[ -](?:floor|fl\b\.?)/i, (m) => Number(m[1])],
  [/\bfloor\s+(\d{1,2})\b/i, (m) => Number(m[1])],
];

const LOOK = '(?:fac(?:es|ing)|overlook(?:s|ing)?|looks? out (?:on|onto|over))';
const FRONT = [
  new RegExp(`\\b${LOOK}\\s+(?:the\\s+)?(?:street|avenue|(?:(?:East|West|E|W)\\.?\\s+)?\\d{1,3}(?:st|nd|rd|th)\\s+(?:Street|St)\\b|[A-Z][a-z]+\\s+(?:Avenue|Ave|Street|St)\\b)`, 'i'),
  /\b(?:street|front)[- ]facing\b/i,
  /\bfront (?:unit|apartment)\b/i,
];
const REAR = [
  new RegExp(`\\b${LOOK}\\s+(?:the\\s+|a\\s+)?(?:back|rear|courtyard|garden|yard|backyard|interior)\\b`, 'i'),
  /\b(?:rear|back|courtyard)[- ]facing\b/i,
  /\brear (?:unit|apartment)\b/i,
  /\bback of the building\b/i,
];

const VIEW = /\b(?:views? of|overlook(?:s|ing)|looks? out (?:on|onto|over))\s+([^.,;\n]+)/i;
const WINDOWS = /\b(?:floor-to-ceiling windows|(?:double|triple)[- ]pane(?:d)? windows|casement windows|bay windows?|(?:[A-Za-z]+\s){0,2}windows? in the (?:bedroom|living room|kitchen))/i;
const AC = /\b(?:through[- ](?:the[- ])?wall (?:air conditioners?|AC|A\/C)(?: units?)?|window (?:AC|A\/C|air conditioners?|air conditioning)(?: units?)?|central (?:air|AC|A\/C)|ductless (?:mini[- ])?splits?|PTAC units?)(?:\s+in each \w+)?/i;
const WALLS = /\b(?:exposed brick(?: walls?)?|brick walls?|concrete (?:walls?|ceilings?|construction)|plaster walls?)/i;

const ADJECTIVES = /\b(quiet|peaceful|serene|tranquil|calm|charming|sunny|bright|sun-drenched|sun-filled|cozy|stunning|gorgeous|spacious|oversized|lovely|beautiful|bustling|vibrant|lively|classic)\b/gi;

const cantTell = <T,>(): Field<T> => ({ value: null, status: 'cant_tell', evidence: [] });
const read = <T,>(value: T, quote: string): Field<T> => ({ value, status: 'read', evidence: [{ source: 'text', quote }] });
const plain = (s: string) => s.replace(ADJECTIVES, '').replace(/\s{2,}/g, ' ').trim().toLowerCase();

export interface Extraction {
  fields: ReaderFields;
  observed: Observed;
  position: 'front' | 'rear' | 'unknown';
  geocode: string | null;
  sideConflict: [string, string] | null;
  ignored: string[];
}

export function extract(text: string): Extraction {
  // Address, with the borough when the listing gives it right after the street.
  let address: Field<string> = cantTell();
  let geocode: string | null = null;
  const a = ADDRESS.exec(text);
  if (a && a.index !== undefined) {
    const street = a[0].replace(/\.$/, '');
    const after = text.slice(a.index + a[0].length);
    const b = BOROUGH.exec(after);
    const quote = text.slice(a.index, a.index + a[0].length + (b ? b[0].length : 0)).replace(/\.$/, '');
    address = read(quote, quote);
    const borough = b?.[1] ?? 'New York';
    geocode = `${street}, ${borough === 'The Bronx' ? 'Bronx' : borough}`;
  }

  const u = UNIT.exec(text);
  const unit: Field<string> = u ? read(u[1], u[0]) : cantTell();

  let floor: Field<number> = cantTell();
  for (const [re, val] of FLOOR_PATTERNS) {
    const m = text.match(re);
    if (m) {
      floor = read(val(m), m[0]);
      break;
    }
  }

  const firstMatch = (res: RegExp[]) => res.map((re) => text.match(re)).find(Boolean) ?? null;
  const f = firstMatch(FRONT);
  const r = firstMatch(REAR);
  let side: Field<'front' | 'rear'> = cantTell();
  let sideConflict: [string, string] | null = null;
  if (f && r) sideConflict = [f[0], r[0]];
  else if (f) side = read('front', f[0]);
  else if (r) side = read('rear', r[0]);

  const v = text.match(VIEW);
  const w = text.match(WINDOWS);
  const ac = text.match(AC);
  const wall = text.match(WALLS);
  const observed: Observed = {
    view: v ? read(plain(v[1]), v[0].trim()) : cantTell(),
    windows: w ? read(plain(w[0]), w[0]) : cantTell(),
    ac_units: ac ? read(plain(ac[0]), ac[0]) : cantTell(),
    wall_material: wall ? read(plain(wall[0]), wall[0]) : cantTell(),
  };

  const ignored = [...new Set([...text.matchAll(ADJECTIVES)].map((m) => m[0]))];
  return {
    fields: { address, unit, floor, side },
    observed,
    position: side.status === 'read' && side.value ? side.value : 'unknown',
    geocode,
    sideConflict,
    ignored,
  };
}
