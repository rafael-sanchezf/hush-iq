/**
 * Is this listing in New York City? The score only knows the five boroughs, and the city's geocoder answers
 * every query with its nearest NYC match: "123 Main St, Boston, MA 02129" comes back as 190C Main Street in the
 * Bronx. So the extension checks twice: before scoring, on what the listing says (state, ZIP, town), and after,
 * that the building the geocoder found carries the listing's house number and street.
 */

/** NYC ZIP codes by prefix. 110 and 115 are mostly Nassau County; only Glen Oaks (11004, 11005) is Queens. */
export function nycZip(zip: string): boolean {
  const n = Number(zip);
  if (!/^\d{5}$/.test(zip)) return false;
  if (n >= 10001 && n <= 10282) return true; // Manhattan
  if (n >= 10301 && n <= 10314) return true; // Staten Island
  if (n >= 10451 && n <= 10475) return true; // Bronx
  if (n === 11004 || n === 11005) return true; // Glen Oaks, Queens
  if (n >= 11101 && n <= 11120) return true; // Long Island City, Queens
  if (n >= 11201 && n <= 11256) return true; // Brooklyn
  if (n >= 11351 && n <= 11499) return true; // Queens
  if (n >= 11690 && n <= 11697) return true; // the Rockaways, Queens
  return false;
}

const STATES = 'AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY';
const STATE_NAMES = 'New Jersey|Connecticut|Pennsylvania|Massachusetts|California|Florida|Illinois|Texas';
/** Towns around the city that listing sites file under "New York" searches. */
const NEAR_NOT_NYC = /\b(Jersey City|Hoboken|Weehawken|Union City|West New York|North Bergen|Fort Lee|Edgewater|Newark|Bayonne|Yonkers|New Rochelle|Mount Vernon|White Plains|Hempstead|Long Beach|Great Neck|Valley Stream|Garden City|Westchester|Stamford|Greenwich)\b/;
const NYC_PLACES = /\b(New York|Manhattan|Brooklyn|Bronx|Queens|Staten Island|Long Island City|Astoria|Flushing|Jamaica|Forest Hills|Jackson Heights|Ridgewood|Sunnyside|Woodside|Elmhurst|Bayside|Rego Park|Kew Gardens|Far Rockaway|Harlem|Williamsburg|Bushwick|Greenpoint|Park Slope)\b/i;

export interface NycCheck {
  /** true: the listing says NYC; false: it says somewhere else; null: it does not say. */
  inNyc: boolean | null;
  why: string;
}

export interface Postal {
  street: string | null;
  locality: string | null;
  region: string | null;
  postal_code: string | null;
}

/** What the listing says about where it is. The first address-like line wins, as the reader reads it. */
export function checkPlace(text: string, postal: Postal | null = null): NycCheck {
  if (postal?.region && !/^(NY|New York)$/i.test(postal.region.trim())) {
    return { inNyc: false, why: `The page lists it in ${postal.region}.` };
  }
  if (postal?.postal_code) {
    const zip = postal.postal_code.trim().slice(0, 5);
    if (/^\d{5}$/.test(zip)) {
      return nycZip(zip) ? { inNyc: true, why: `ZIP ${zip}` } : { inNyc: false, why: `ZIP ${zip} is outside the five boroughs.` };
    }
  }
  // "City, ST 12345" anywhere in the text.
  const m = new RegExp(`,\\s*(${STATES}|NY)\\.?\\s+(\\d{5})(?:-\\d{4})?\\b`).exec(text);
  if (m) {
    if (m[1] !== 'NY') return { inNyc: false, why: `The listing says ${m[1]} ${m[2]}.` };
    return nycZip(m[2]) ? { inNyc: true, why: `ZIP ${m[2]}` } : { inNyc: false, why: `ZIP ${m[2]} is outside the five boroughs.` };
  }
  const st = new RegExp(`,\\s*(${STATES})\\b(?!\\s*\\d)`).exec(text);
  if (st && !NYC_PLACES.test(text.slice(Math.max(0, st.index - 40), st.index))) return { inNyc: false, why: `The listing says ${st[1]}.` };
  const name = new RegExp(`\\b(${STATE_NAMES})\\b`).exec(text);
  const near = NEAR_NOT_NYC.exec(text);
  if ((name || near) && !NYC_PLACES.test(text)) return { inNyc: false, why: `The listing says ${(near ?? name)![1]}.` };
  if (postal?.locality && NYC_PLACES.test(postal.locality)) return { inNyc: true, why: postal.locality };
  return { inNyc: null, why: '' };
}

const ORD: Record<string, string> = { first: '1', second: '2', third: '3', fourth: '4', fifth: '5', sixth: '6', seventh: '7', eighth: '8', ninth: '9', tenth: '10', eleventh: '11', twelfth: '12' };
const WORDS: Record<string, string> = {
  street: 'st', st: 'st', avenue: 'ave', ave: 'ave', av: 'ave', place: 'pl', pl: 'pl', road: 'rd', rd: 'rd', boulevard: 'blvd', blvd: 'blvd',
  drive: 'dr', dr: 'dr', lane: 'ln', ln: 'ln', terrace: 'ter', ter: 'ter', square: 'sq', sq: 'sq', parkway: 'pkwy', pkwy: 'pkwy', court: 'ct', ct: 'ct',
  east: 'e', e: 'e', west: 'w', w: 'w', north: 'n', n: 'n', south: 's', s: 's',
};

/** "310 West 47th Street" and "310 W 47 ST" both read `{number: "310", words: ["w", "47", "st"]}`. */
export function streetKey(line: string): { number: string; words: string[] } | null {
  const street = line.split(',')[0].toLowerCase().replace(/[.#]/g, ' ');
  const m = /^\s*(\d+[a-z]?)(?:-\d+)?\s+(.+)$/.exec(street);
  if (!m) return null;
  const words = m[2].split(/\s+/).filter(Boolean)
    .map((w) => ORD[w] ?? w.replace(/^(\d+)(st|nd|rd|th)$/, '$1'))
    .map((w) => WORDS[w] ?? w)
    .filter((w) => !/^(apt|unit|fl|floor|ph)$/.test(w));
  return { number: m[1].replace(/[a-z]$/, ''), words };
}

/**
 * Did the geocoder find the building the listing names? Same house number, and every word of the listing's
 * street name (apart from E/W and the street type) is in the found one.
 */
export function sameBuilding(listing: string, found: string): boolean {
  const a = streetKey(listing);
  const b = streetKey(found);
  if (!a || !b) return true; // nothing to compare: trust the geocoder, as the website does
  if (a.number !== b.number) return false;
  const core = (ws: string[]) => ws.filter((w) => !/^(e|w|n|s|st|ave|pl|rd|blvd|dr|ln|ter|sq|pkwy|ct)$/.test(w));
  const need = core(a.words);
  const have = new Set(core(b.words));
  return need.length === 0 || need.every((w) => have.has(w));
}
