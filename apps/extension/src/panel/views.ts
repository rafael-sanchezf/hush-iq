/**
 * The panel's pieces, built as plain elements. Wording follows the website's demo (apps/web/src/components/demo)
 * so the two read as one product.
 */
import type { Live } from '../lib/client.ts';
import type { AiInfo, Answers, Bother, Cap, EvidenceRef, Field, Observed, RangeCase, ReaderFields, ReaderTurn, Score, Source } from '../lib/types.ts';
import { BOTHERS, VERDICTS } from '../lib/types.ts';
import { BOTHER_WORDS, SOURCE_WORDS, addressLine, cleanEvidence, forWhom, hourLabel, hoursAsleep, observedLabel, pct, sideLabel, sideWords } from '../lib/words.ts';
import { clear, glyph, h } from './dom.ts';

// ---------------------------------------------------------------- the three questions

const HOURS = Array.from({ length: 24 }, (_, x) => x);
// The strip runs noon to noon so a night's sleep reads as one block.
const STRIP = Array.from({ length: 24 }, (_, i) => (i + 12) % 24);

function asleep(x: number, from: number, until: number): boolean {
  if (from === until) return false;
  return from > until ? x >= from || x < until : from <= x && x < until;
}

const STEPS = 3;

/** The three questions, one screen each: sleep hours, daytime noise, what gets to you. They set the weights, never
 * the facts. One at a time, since all three at once was too much on first open (Rafa, 2026-10-29). */
export function questionsCard(start: Answers, onDone: (a: Answers) => void, done = 'Score this apartment'): HTMLElement {
  let a = { ...start, bothers: [...start.bothers] };
  let step = 0;
  const card = h('section', { class: 'card', 'aria-label': 'Three questions' });
  const draw = () => {
    clear(card);
    const set = (patch: Partial<Answers>) => {
      a = { ...a, ...patch };
      draw();
    };
    const go = (to: number) => {
      step = to;
      draw();
    };
    const toggle = (b: Bother) =>
      set({ bothers: a.bothers.includes(b) ? a.bothers.filter((x) => x !== b) : BOTHERS.filter((x) => x === b || a.bothers.includes(x)) });
    let q: HTMLElement;
    if (step === 0) {
      const n = hoursAsleep(a);
      const picker = (label: string, value: number, key: 'sleep_from' | 'sleep_until') =>
        h('label', { class: 'select' }, h('span', null, label),
          h('select', { onchange: (e: Event) => set({ [key]: Number((e.target as HTMLSelectElement).value) }) },
            HOURS.map((x) => h('option', { value: x, selected: x === value }, hourLabel(x)))));
      q = h('div', { class: 'q' },
        h('div', { class: 'q-title' }, h('span', null, 'When do you sleep?'), h('small', null, `${n} hour${n === 1 ? '' : 's'} asleep`)),
        h('div', { class: 'sleep-pickers' }, picker('Asleep from', a.sleep_from, 'sleep_from'), picker('Until', a.sleep_until, 'sleep_until')),
        h('div', { class: 'clock', 'aria-hidden': 'true' }, STRIP.map((x) => h('i', { class: asleep(x, a.sleep_from, a.sleep_until) ? 'asleep' : null }))),
        h('div', { class: 'clock-labels', 'aria-hidden': 'true' }, ['noon', '6 pm', 'midnight', '6 am', 'noon'].map((t) => h('span', null, t))),
        h('button', { type: 'button', class: 'btn block', onclick: () => go(1) }, 'Next'));
    } else if (step === 1) {
      // One tap answers it and moves on.
      q = h('div', { class: 'q' },
        h('div', { class: 'q-title' }, h('span', { id: 'q-day' }, 'Does noise during the day bother you?')),
        h('div', { class: 'seg', role: 'group', 'aria-labelledby': 'q-day' },
          h('button', { type: 'button', 'aria-pressed': String(a.day_bothers), onclick: () => { a = { ...a, day_bothers: true }; go(2); } }, 'Yes, I’m home'),
          h('button', { type: 'button', 'aria-pressed': String(!a.day_bothers), onclick: () => { a = { ...a, day_bothers: false }; go(2); } }, 'Not really')));
    } else {
      q = h('div', { class: 'q' },
        h('div', { class: 'q-title' }, h('span', { id: 'q-bothers' }, 'What gets to you?'), h('small', null, a.bothers.length ? `${a.bothers.length} ticked` : 'Tick any, or none')),
        h('div', { class: 'chips', role: 'group', 'aria-labelledby': 'q-bothers' },
          BOTHERS.map((b) => h('button', { type: 'button', class: 'chip', 'aria-pressed': String(a.bothers.includes(b)), title: BOTHER_WORDS[b].hint, onclick: () => toggle(b) }, BOTHER_WORDS[b].label))),
        h('p', { class: 'chip-hint' }, 'Each one you tick counts three times as much. Nightlife covers bars, crowds and late talk.'),
        h('button', { type: 'button', class: 'btn block', onclick: () => onDone(a) }, done));
    }
    card.append(
      h('div', { class: 'block-head' },
        h('span', { class: 'eyebrow' }, `Question ${step + 1} of ${STEPS}`),
        step > 0 ? h('button', { type: 'button', class: 'link small', onclick: () => go(step - 1) }, 'Back') : null),
      h('div', { class: 'steps', 'aria-hidden': 'true' }, Array.from({ length: STEPS }, (_, i) => h('i', { class: i <= step ? 'on' : null }))),
      q,
    );
  };
  draw();
  return card;
}

// ---------------------------------------------------------------- the reader's turns

export function turnItem(t: ReaderTurn): HTMLLIElement {
  return h('li', { class: `turn ${t.status ?? 'ok'}` },
    glyph(t.status),
    h('div', { class: 'turn-body' },
      h('div', { class: 'turn-title' }, t.title),
      t.detail ? h('div', { class: 'turn-detail' }, t.detail) : null));
}

// ---------------------------------------------------------------- the verdict

function meter(verdict: Score['verdict'], range: Score['range']): HTMLElement {
  const on = VERDICTS.indexOf(verdict);
  let bracket: HTMLElement | null = null;
  if (range) {
    const a = VERDICTS.indexOf(range.loudest_case.verdict);
    const b = VERDICTS.indexOf(range.quietest_case.verdict);
    const lo = Math.min(a, b);
    const hi = Math.max(a, b);
    if (hi > lo) {
      bracket = h('div', { class: 'meter-range' },
        h('i', { style: `left: calc(${lo} * (100% + 5px) / 5); width: calc(${hi - lo + 1} * (100% + 5px) / 5 - 5px)` }));
    }
  }
  return h('div', { class: 'meter', 'aria-hidden': 'true' },
    h('div', { class: 'meter-steps' }, VERDICTS.map((_, i) => h('span', { class: i === on ? 'on' : null }))),
    bracket,
    h('div', { class: 'meter-ends' }, h('span', null, 'Very loud'), h('span', null, 'Very quiet')));
}

function caseWords(c: RangeCase): string {
  return [c.floor ? `floor ${c.floor}` : null, sideWords(c.side)].filter(Boolean).join(', ');
}

/** One line per source that hit a cap: the strongest cap it set, and whether it changed the verdict. */
function capLines(caps: Cap[]): Cap[] {
  const best = new Map<Source, Cap>();
  for (const c of caps) {
    const prev = best.get(c.source);
    if (!prev || VERDICTS.indexOf(c.cap) < VERDICTS.indexOf(prev.cap) || (c.applied && !prev.applied)) best.set(c.source, c);
  }
  return [...best.values()].sort((a, b) => Number(b.applied) - Number(a.applied));
}

function photoNumber(e: EvidenceRef): number | null {
  const n = Number(e.source.split(':')[1]);
  return Number.isFinite(n) ? n : null;
}

function quoteOf(f: Field<unknown>, photos: string[]): (Node | string)[] | null {
  const e = f.evidence[0];
  if (!e) return null;
  if (e.source === 'text') return [`“${e.quote}”`];
  const n = photoNumber(e);
  const src = n !== null ? photos[n] : undefined;
  return [src ? h('img', { src, alt: '' }) : '', `Photo ${n !== null ? n + 1 : ''}: ${e.what}`];
}

export interface ResultView {
  score: Score;
  fields: ReaderFields;
  observed: Observed;
  answers: Answers;
  reader: Live;
  /** The photos as sent, so `photo:<i>` evidence can show its picture. */
  photos: string[];
  /** The reader's `ai` label: `basic` when rules read it, with the message the panel shows. */
  readerAi: AiInfo | null;
}

export function verdictCard(v: ResultView): HTMLElement {
  const { score, answers, fields } = v;
  const range = score.range;
  const floorQuote = fields.floor.status === 'read' ? quoteOf(fields.floor, v.photos) : null;
  const sideQuote = fields.side.status === 'read' ? quoteOf(fields.side, v.photos) : null;
  const facts = score.building_facts;
  return h('section', { class: 'card verdict', 'aria-label': 'The verdict', 'aria-live': 'polite' },
    h('p', { class: 'addr' }, addressLine(score.address.label, score.address.query)),
    h('h2', { class: 'word' }, score.verdict, h('small', null, 'for Manhattan')),
    meter(score.verdict, range),
    h('p', { class: 'for' }, forWhom(answers), ' ', h('b', null, `Quieter than ${pct(score.quieter_than)} of Manhattan apartments.`)),
    capLines(score.caps).map((c) => h('div', { class: 'note' }, glyph(c.applied ? 'refused' : 'cant_tell'),
      h('span', null, ...(c.applied
        ? [h('b', null, `Held at ${c.cap} by ${SOURCE_WORDS[c.source].title.toLowerCase()}`), `: ${c.why}. Without it the verdict would read ${score.uncapped_verdict}.`]
        : [h('b', null, SOURCE_WORDS[c.source].title), ` is ${c.why.replace(/^you said it bothers you, and it is /, '')}${c.why.startsWith('you said') ? ', and you said it bothers you' : ''}. On its own it would hold the verdict at ${c.cap}.`])))),
    h('div', { class: 'facts' },
      h('div', { class: 'fact' },
        h('span', { class: 'k' }, 'Floor'),
        h('span', { class: 'v' }, score.unit.floor_from === 'listing' ? `Floor ${score.unit.floor}` : score.unit.floor ? `Floor ${score.unit.floor}, expected` : 'Unknown'),
        h('span', { class: 'q' }, ...(score.unit.floor_from === 'listing' && floorQuote ? ['From the listing: ', ...floorQuote] : ['Not in the listing: the building’s middle residential floor.']))),
      h('div', { class: 'fact' },
        h('span', { class: 'k' }, 'Side'),
        h('span', { class: 'v' }, score.unit.side_from === 'listing' ? sideLabel(fields.side.status === 'read' ? fields.side.value : score.unit.side) : 'Can’t tell'),
        h('span', { class: 'q' }, ...(score.unit.side_from === 'listing' && sideQuote ? ['From the listing: ', ...sideQuote] : ['Not in the listing: scored between street side and rear.']))),
      range ? h('div', { class: 'fact' },
        h('span', { class: 'k' }, 'Range'),
        h('span', { class: 'v' }, range.loudest_case.verdict === range.quietest_case.verdict ? `${range.loudest_case.verdict} either way` : `${range.loudest_case.verdict} to ${range.quietest_case.verdict}`),
        h('span', { class: 'q' }, `${range.loudest_case.verdict} at ${caseWords(range.loudest_case)}; ${range.quietest_case.verdict} at ${caseWords(range.quietest_case)}.`)) : null,
      h('div', { class: 'fact' },
        h('span', { class: 'k' }, 'Building'),
        h('span', { class: 'v' }, [score.unit.building_floors ? `${score.unit.building_floors} floors` : null, facts?.yearbuilt ? `built ${facts.yearbuilt}` : null].filter(Boolean).join(', ') || 'Unknown'),
        h('span', { class: 'q' }, [facts?.unitsres ? `${facts.unitsres} apartments` : null, score.unit.ground_floor_commercial ? 'shops or a bar on the ground floor' : null].filter(Boolean).join(', ') || 'From PLUTO, the city’s lot records.'))),
  );
}

export function sourcesCard(score: Score): HTMLElement {
  const sources = [...score.ingredients].sort((a, b) => a.quieter_than - b.quieter_than);
  return h('section', { class: 'card', 'aria-label': 'Source by source' },
    h('div', { class: 'block-head' }, h('h3', null, 'Source by source'), h('span', { class: 'small' }, 'Loudest first')),
    h('div', { class: 'sources' }, sources.map((i) => h('article', { class: 'source' },
      h('div', { class: 'source-top' }, h('h4', null, SOURCE_WORDS[i.name].title), h('span', { class: 'num' }, pct(i.quieter_than))),
      h('p', { class: 'rank-line' }, `Quieter than ${pct(i.quieter_than)} of Manhattan apartments · ${Math.round(i.weight)}% of your verdict`),
      h('div', { class: `rank-bar${i.ticked ? ' ticked' : ''}`, 'aria-hidden': 'true' }, h('i', { style: `width: ${Math.max(2, i.quieter_than)}%` })),
      h('div', { class: 'rank-ends', 'aria-hidden': 'true' }, h('span', null, 'Loudest'), h('span', null, 'Quietest')),
      i.ticked || i.temporary ? h('div', { class: 'tags' }, i.ticked ? h('span', { class: 'pill ink' }, 'Matters to you') : null, i.temporary ? h('span', { class: 'pill' }, 'Temporary') : null) : null,
      i.evidence.length ? h('details', null,
        h('summary', null, `The city data (${i.evidence.length} line${i.evidence.length > 1 ? 's' : ''})`),
        h('ul', null, i.evidence.map((e) => h('li', null, cleanEvidence(e))))) : null))));
}

/** What the reader took from the listing, folded away under the results: open it to see what informed the score.
 * Hidden by default, since a renter does not need it to act (Rafa, 2026-10-29). */
export function informedCard(v: ResultView): HTMLElement {
  const { fields, observed } = v;
  const rows: [string, string, Field<unknown>][] = [
    ['Address', 'address', fields.address],
    ['Unit', 'unit', fields.unit],
    ['Floor', 'floor', fields.floor],
    ['Side', 'side', fields.side],
    ['View', 'view', observed.view],
    ['Windows', 'windows', observed.windows],
    ['AC units', 'ac_units', observed.ac_units],
    ['Walls', 'wall_material', observed.wall_material],
  ];
  const value = (key: string, f: Field<unknown>) =>
    f.status !== 'read' ? 'Can’t tell' : key === 'side' ? sideLabel(f.value as string) : ['address', 'unit', 'floor'].includes(key) ? String(f.value) : observedLabel(key, f.value);
  const who = v.readerAi?.mode === 'basic' || v.reader === 'replay' ? 'Fixed rules read the text, never the photos.' : 'Muse Spark read the listing; each fact shows the line it came from.';
  return h('section', { class: 'card', 'aria-label': 'What informed your Hush score' },
    h('details', { class: 'informed' },
      h('summary', null, 'What informed your Hush score'),
      h('p', { class: 'small' }, who),
      h('div', { class: 'facts' }, rows.map(([k, key, f]) => h('div', { class: 'fact' },
        h('span', { class: 'k' }, k),
        h('span', { class: `v${f.status === 'read' ? '' : ' cant'}` }, value(key, f)),
        h('span', { class: 'q' }, ...(quoteOf(f, v.photos) ?? ['Nothing in the listing says it.']))))),
      h('p', { class: 'small' }, 'Floor and side feed the score. The rest are here to check at a viewing.')));
}

export function fineprint(score: Score): HTMLElement {
  return h('p', { class: 'fine' },
    `Engine v2 against ${score.manhattan.buildings} Manhattan buildings standing for ${score.manhattan.apartments.toLocaleString('en-US')} apartments (sample of ${score.manhattan.as_of}); city data as of ${score.as_of ?? 'today'}. `,
    score.replayed_from === 'v1' ? 'Ranked in this panel from the hosted model’s ingredients until /v2/score is deployed; the numbers match the engine’s own. ' : '',
    'Every number is a rank against Manhattan, not a sound measurement.');
}
