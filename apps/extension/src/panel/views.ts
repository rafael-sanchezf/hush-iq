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

function asleep(x: number, from: number, until: number): boolean {
  if (from === until) return false;
  return from > until ? x >= from || x < until : from <= x && x < until;
}

/** The hours the strip shows: evening to late morning first, which holds nearly every night's sleep, and the full
 * day, noon to noon, on request (Rafa, 2026-10-29). `labels` are hour marks, as offsets from `from`. */
interface StripView { from: number; hours: number; labels: number[] }
const NIGHT_VIEW: StripView = { from: 19, hours: 16, labels: [0, 4, 8, 12, 16] };
const DAY_VIEW: StripView = { from: 12, hours: 24, labels: [0, 6, 12, 18, 24] };

/** Does every hour asleep fall inside this view? */
function fits(v: StripView, from: number, until: number): boolean {
  for (let x = 0; x < 24; x++) {
    if (asleep(x, from, until) && (x - v.from + 24) % 24 >= v.hours) return false;
  }
  return true;
}

/** Sleep hours by dragging: press at bedtime, drag to wake-up. Hours snap to the marks between cells. Arrow keys
 * move the wake-up hour, and with Shift the bedtime. Calls `onChange` on every move, without redrawing the card. */
function sleepStrip(start: Answers, onChange: (from: number, until: number) => void): HTMLElement {
  let from = start.sleep_from;
  let until = start.sleep_until;
  let full = !fits(NIGHT_VIEW, from, until);
  const wrap = h('div', { class: 'sleep' });
  const render = () => {
    const view = full ? DAY_VIEW : NIGHT_VIEW;
    const hourAt = (b: number) => (view.from + b) % 24;
    const cells = Array.from({ length: view.hours }, () => h('i'));
    const paint = () => cells.forEach((c, i) => c.classList.toggle('asleep', asleep(hourAt(i), from, until)));
    const bar = h('div', {
      class: 'clock drag', role: 'group', tabindex: 0, 'aria-label': 'Hours asleep: drag from bedtime to wake-up',
      style: `grid-template-columns: repeat(${view.hours}, 1fr)`,
    }, cells);
    const commit = (f: number, u: number) => {
      from = f;
      until = u;
      paint();
      onChange(from, until);
    };
    const mark = (e: PointerEvent) => {
      const r = bar.getBoundingClientRect();
      return Math.max(0, Math.min(view.hours, Math.round(((e.clientX - r.left) / r.width) * view.hours)));
    };
    let anchor: number | null = null;
    bar.addEventListener('pointerdown', (e: PointerEvent) => {
      anchor = mark(e);
      bar.setPointerCapture(e.pointerId);
    });
    bar.addEventListener('pointermove', (e: PointerEvent) => {
      if (anchor === null) return;
      const b = mark(e);
      if (b === anchor) return;
      const lo = Math.min(anchor, b);
      const hi = Math.min(Math.max(anchor, b), lo + 23);   // a full turn would read as no sleep at all
      commit(hourAt(lo), hourAt(hi));
    });
    const end = () => (anchor = null);
    bar.addEventListener('pointerup', end);
    bar.addEventListener('pointercancel', end);
    bar.addEventListener('keydown', (e: KeyboardEvent) => {
      const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
      if (!step) return;
      e.preventDefault();
      const f = e.shiftKey ? (from + step + 24) % 24 : from;
      const u = e.shiftKey ? until : (until + step + 24) % 24;
      if (f !== u) commit(f, u);
    });
    paint();
    wrap.replaceChildren(
      bar,
      h('div', { class: 'clock-labels drag', 'aria-hidden': 'true' },
        view.labels.map((b) => h('span', { style: `left: ${(100 * b) / view.hours}%` }, hourLabel(hourAt(b))))),
      h('div', { class: 'sleep-foot' },
        h('span', { class: 'small' }, 'Press at bedtime, drag to when you wake.'),
        h('button', {
          type: 'button', class: `icon-btn more${full ? ' open' : ''}`,
          title: full ? 'Show evening and night' : 'Show full day', 'aria-label': full ? 'Show evening and night' : 'Show full day',
          onclick: () => {
            full = !full;
            render();
          },
        }, '›')),
    );
  };
  render();
  return wrap;
}

const STEPS = 3;

/** The three questions, one screen each: sleep hours, daytime noise, what gets to you. They set the weights, never
 * the facts. One at a time, since all three at once was too much on first open (Rafa, 2026-10-29). */
export function questionsCard(start: Answers, onDone: (a: Answers) => void, done = 'Score this apartment', onCancel?: () => void): HTMLElement {
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
      const readout = h('small');
      const say = () => {
        const n = hoursAsleep(a);
        readout.textContent = `${hourLabel(a.sleep_from)} to ${hourLabel(a.sleep_until)}, ${n} hour${n === 1 ? '' : 's'}`;
      };
      say();
      q = h('div', { class: 'q' },
        h('div', { class: 'q-title' }, h('span', null, 'When do you typically sleep?'), readout),
        sleepStrip(a, (from, until) => {
          a = { ...a, sleep_from: from, sleep_until: until };
          say();
        }),
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
        step > 0 ? h('button', { type: 'button', class: 'link small', onclick: () => go(step - 1) }, 'Back')
          : onCancel ? h('button', { type: 'button', class: 'link small', onclick: onCancel }, 'Cancel') : null),
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

// ---------------------------------------------------------------- icons

/** Line icons, 24 by 24, drawn in the current text colour. */
const ICONS: Record<string, string> = {
  address: '<path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/>',
  floor: '<path d="M4 20h4v-4h4v-4h4V8h4"/><path d="M4 4h16"/>',
  side: '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M12 4v16M4 12h16"/>',
  building: '<path d="M5 21V5a1 1 0 0 1 1-1h8a1 1 0 0 1 1 1v16"/><path d="M15 10h3a1 1 0 0 1 1 1v10M3 21h18M9 8h2M9 12h2M9 16h2"/>',
  street: '<path d="M3 13l2-6h14l2 6v5H3z"/><path d="M7 18v2M17 18v2M3 13h18"/><path d="M7 15.5h.01M17 15.5h.01"/>',
  sirens: '<path d="M7 18v-6a5 5 0 0 1 10 0v6"/><path d="M5 21h14v-3H5z"/><path d="M12 3v2M4.2 6.2l1.4 1.4M19.8 6.2l-1.4 1.4"/>',
  neighbors: '<circle cx="9" cy="8" r="3"/><path d="M3 20a6 6 0 0 1 12 0"/><path d="M16 5a3 3 0 0 1 0 6M21 20a6 6 0 0 0-4-5.6"/>',
  nightlife: '<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
  construction: '<path d="M2 18h20"/><path d="M4 18v-2a8 8 0 0 1 16 0v2"/><path d="M10 9V5h4v4"/>',
  sleep: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
  day: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  bothers: '<path d="M6 9a6 6 0 1 1 12 0c0 3-2 4-3 5.5S14 18 12 19.5 8 20 8 18"/><path d="M9.5 9a2.5 2.5 0 0 1 5 0c0 1.5-1.5 2-1.5 3"/>',
};

/** An icon tile. `missing` makes it glow red: the listing does not say this. */
function icon(name: string, missing = false): HTMLSpanElement {
  const tile = h('span', { class: `ico${missing ? ' missing' : ''}`, 'aria-hidden': 'true' });
  tile.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${ICONS[name]}</svg>`;
  return tile;
}

// ---------------------------------------------------------------- the result

/** The score alone: the word, where it sits from very loud to very quiet, and the rank (Rafa, 2026-10-29). */
export function scoreCard(v: ResultView): HTMLElement {
  const { score } = v;
  return h('section', { class: 'card verdict', 'aria-label': 'Your Hush score', 'aria-live': 'polite' },
    h('h2', { class: 'word' }, score.verdict, h('small', null, 'for Manhattan')),
    meter(score.verdict, score.range),
    h('p', { class: 'for' }, h('b', null, `Quieter than ${pct(score.quieter_than)} of Manhattan apartments.`)));
}

/** One row: an icon, what it is, what we used, and a line on where it came from. */
function row(ico: HTMLElement, k: string, v: string, note?: (Node | string)[] | string | null, extra?: (Node | null)[]): HTMLElement {
  return h('div', { class: 'shaped-row' }, ico,
    h('div', { class: 'shaped-body' },
      h('span', { class: 'k' }, k),
      h('span', { class: 'v' }, v),
      note ? h('span', { class: 'q' }, ...(Array.isArray(note) ? note : [note])) : null,
      ...(extra ?? [])));
}

function group(title: string, ...rows: (Node | null)[]): HTMLElement {
  return h('div', { class: 'shaped-group' }, h('h4', { class: 'eyebrow' }, title), ...rows);
}

/** What informed the score, grouped: what the listing said (red where it is silent), the building, the noise
 * around it, and the renter's own answers. Only what the score uses; nothing else from the page. */
export function shapedCard(v: ResultView, on: { answers: () => void; fix: () => void }): HTMLElement {
  const { score, fields, answers } = v;
  const unit = score.unit;
  const range = score.range;
  const rangeLine = range
    ? range.loudest_case.verdict === range.quietest_case.verdict
      ? `${range.loudest_case.verdict} either way.`
      : `So the score is a range: ${range.loudest_case.verdict} at ${caseWords(range.loudest_case)}, ${range.quietest_case.verdict} at ${caseWords(range.quietest_case)}.`
    : '';
  const floorOk = unit.floor_from === 'listing';
  const sideOk = unit.side_from === 'listing';
  const quote = (f: Field<unknown>) => (f.status === 'read' ? quoteOf(f, v.photos) : null);
  const facts = score.building_facts;

  const caps = new Map(capLines(score.caps).map((c) => [c.source, c]));
  const sources = [...score.ingredients].sort((a, b) => a.quieter_than - b.quieter_than).map((i) => {
    const c = caps.get(i.name);
    return h('div', { class: 'shaped-row' }, icon(i.name === 'building' ? 'neighbors' : i.name),
      h('div', { class: 'shaped-body' },
        h('div', { class: 'source-top' }, h('span', { class: 'v' }, SOURCE_WORDS[i.name].title), h('span', { class: 'num' }, pct(i.quieter_than))),
        h('span', { class: 'q' }, `Quieter than ${pct(i.quieter_than)} of Manhattan · ${Math.round(i.weight)}% of your score`),
        h('div', { class: `rank-bar${i.ticked ? ' ticked' : ''}`, 'aria-hidden': 'true' }, h('i', { style: `width: ${Math.max(2, i.quieter_than)}%` })),
        c ? h('span', { class: 'q cap' }, c.applied ? `Holds your score at ${c.cap}.` : `Loud enough on its own to hold it at ${c.cap}.`) : null,
        i.ticked || i.temporary ? h('div', { class: 'tags' }, i.ticked ? h('span', { class: 'pill ink' }, 'Matters to you') : null, i.temporary ? h('span', { class: 'pill' }, 'Temporary') : null) : null,
        i.evidence.length ? h('details', null,
          h('summary', null, `The city data (${i.evidence.length})`),
          h('ul', null, i.evidence.map((e) => h('li', null, cleanEvidence(e))))) : null));
  });

  return h('section', { class: 'card shaped', 'aria-label': 'What informed your Hush score' },
    h('h3', null, 'What informed your Hush score'),
    group('From the listing',
      row(icon('address', fields.address.status !== 'read'), 'Address', addressLine(score.address.label, score.address.query),
        quote(fields.address) ?? 'Not on the listing: found from the city’s records.'),
      row(icon('floor', !floorOk), 'Floor',
        floorOk ? `Floor ${unit.floor}${unit.building_floors ? ` of ${unit.building_floors}` : ''}` : 'Not on the listing',
        floorOk
          ? fields.floor.derived?.from === 'unit' ? `From unit ${fields.floor.derived.unit}: the listing does not state the floor.` : quote(fields.floor)
          : `Scored at the middle floor${unit.floor ? `, ${unit.floor}` : ''}. ${rangeLine}`),
      row(icon('side', !sideOk), 'Side', sideOk ? sideLabel(fields.side.status === 'read' ? fields.side.value : unit.side) : 'Not on the listing',
        sideOk ? quote(fields.side) : `Scored between street side and rear.${floorOk ? ` ${rangeLine}` : ''}`),
      h('button', { type: 'button', class: 'link small', onclick: on.fix }, 'Something wrong? Fix what it read')),
    group('The building',
      row(icon('building'), 'From city records',
        [unit.building_floors ? `${unit.building_floors} floors` : null, facts?.yearbuilt ? `built ${facts.yearbuilt}` : null].filter(Boolean).join(', ') || 'Unknown',
        [facts?.unitsres ? `${facts.unitsres} apartments` : null, unit.ground_floor_commercial ? 'shops or a bar on the ground floor' : null].filter(Boolean).join(', ') || null)),
    group('Noise around it, loudest first', ...sources),
    group('You',
      row(icon('sleep'), 'Asleep', `${hourLabel(answers.sleep_from)} to ${hourLabel(answers.sleep_until)}`, 'Each hour asleep counts three times an hour awake.'),
      row(icon('day'), 'Daytime noise', answers.day_bothers ? 'Bothers you' : 'Does not bother you'),
      row(icon('bothers'), 'What gets to you', answers.bothers.length ? answers.bothers.map((b) => BOTHER_WORDS[b].label).join(', ') : 'Nothing ticked',
        answers.bothers.length ? 'Each counts three times as much.' : null),
      h('button', { type: 'button', class: 'link small', onclick: on.answers }, 'Change my answers')),
  );
}

export function fineprint(score: Score): HTMLElement {
  return h('p', { class: 'fine' },
    `Engine v2 against ${score.manhattan.buildings} Manhattan buildings standing for ${score.manhattan.apartments.toLocaleString('en-US')} apartments (sample of ${score.manhattan.as_of}); city data as of ${score.as_of ?? 'today'}. `,
    score.replayed_from === 'v1' ? 'Ranked in this panel from the hosted model’s ingredients until /v2/score is deployed; the numbers match the engine’s own. ' : '',
  );
}
