/**
 * The panel's pieces, built as plain elements. Wording follows the website's demo (apps/web/src/components/demo)
 * so the two read as one product.
 */
import type { Live } from '../lib/client.ts';
import type { AiInfo, Answers, Bother, Cap, Observed, ReaderFields, ReaderTurn, Score, Source } from '../lib/types.ts';
import { BOTHERS, VERDICTS } from '../lib/types.ts';
import type { Tile } from '../lib/reasons.ts';
import { level, objectiveRank, sourceLines, tiles } from '../lib/reasons.ts';
import { BOTHER_WORDS, SOURCE_WORDS, hourLabel, hoursAsleep, pct } from '../lib/words.ts';
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
        h('p', { class: 'chip-hint' }, 'Each one you tick counts three times as much. Local businesses covers bars, restaurants, theatres and crowds.'),
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

/** One line per source that hit a cap: the strongest cap it set, and whether it changed the verdict. */
function capLines(caps: Cap[]): Cap[] {
  const best = new Map<Source, Cap>();
  for (const c of caps) {
    const prev = best.get(c.source);
    if (!prev || VERDICTS.indexOf(c.cap) < VERDICTS.indexOf(prev.cap) || (c.applied && !prev.applied)) best.set(c.source, c);
  }
  return [...best.values()].sort((a, b) => Number(b.applied) - Number(a.applied));
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
  /** AI reading is one press away for this result (AI on request, a live reader, not read with AI yet). */
  canPowerUp?: boolean;
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

/** "71%", or "52 to 71%" when an open floor or side spreads the rank across the range's two cases. */
function rankWords(score: Score): string {
  const r = score.range;
  if (!r) return pct(score.quieter_than);
  const a = Math.round(r.loudest_case.quieter_than);
  const b = Math.round(r.quietest_case.quieter_than);
  return a === b ? pct(score.quieter_than) : `${Math.min(a, b)} to ${pct(Math.max(a, b))}`;
}

/** The score alone: the word, where it sits from very loud to very quiet, and the rank (Rafa, 2026-10-29). */
export function scoreCard(v: ResultView): HTMLElement {
  const { score } = v;
  return h('section', { class: 'card verdict', 'aria-label': 'Your Hush score', 'aria-live': 'polite' },
    h('h2', { class: 'word' }, score.verdict, h('small', null, 'for Manhattan')),
    meter(score.verdict, score.range),
    h('p', { class: 'for' }, h('b', null, `Quieter than ${rankWords(score)} of Manhattan apartments.`)));
}

// ---------------------------------------------------------------- what informed the score (HIQ-140)

let tipSeq = 0;
let tipsWired = false;

/** Close every open hover card; a click anywhere else does it too. */
function closeTips(except?: Element): void {
  for (const t of document.querySelectorAll('.tipped.open')) {
    if (t !== except) {
      t.classList.remove('open');
      t.querySelector('[aria-expanded]')?.setAttribute('aria-expanded', 'false');
    }
  }
}

/**
 * A row or tile with a hover card. The card opens on hover, on keyboard focus, and on click or tap; Escape closes
 * it. The target gets a tabindex and `aria-describedby` pointing at the card, so a screen reader reads the why too.
 */
function tipped(target: HTMLElement, lines: string[], more: (string | null)[] = [], align: 'start' | 'end' = 'start', lead = false): HTMLElement {
  if (!tipsWired) {
    tipsWired = true;
    document.addEventListener('click', (e) => closeTips((e.target as Element).closest?.('.tipped') ?? undefined));
  }
  const id = `why-${++tipSeq}`;
  const rest = more.filter((m): m is string => Boolean(m));
  const card = h('div', { class: `tip${align === 'end' ? ' end' : ''}`, id, role: 'tooltip' },
    lines.map((l, i) => h('p', { class: lead && i === 0 ? 'tip-main' : 'tip-why' }, l)),
    rest.length ? h('div', { class: 'tip-more' }, rest.map((m) => h('p', null, m))) : null);
  const wrap = h('div', { class: 'tipped' }, target, card);
  target.tabIndex = 0;
  target.setAttribute('role', 'button');
  target.setAttribute('aria-expanded', 'false');
  target.setAttribute('aria-describedby', id);
  const toggle = () => {
    const open = !wrap.classList.contains('open');
    closeTips(wrap);
    wrap.classList.toggle('open', open);
    target.setAttribute('aria-expanded', String(open));
  };
  target.addEventListener('click', toggle);
  target.addEventListener('keydown', (e: KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      toggle();
    } else if (e.key === 'Escape') {
      wrap.classList.remove('open');
      target.setAttribute('aria-expanded', 'false');
      target.blur();
    }
  });
  return wrap;
}

/**
 * One noise source: icon, name, its level word, the rank bar, and the tag when it matters to the renter. The bar and
 * the word show the objective rank (lib/reasons.ts objectiveRank); the renter's own rank and weight sit in the hover.
 */
function sourceRow(i: Score['ingredients'][number], score: Score, cap: Cap | undefined): HTMLElement {
  const { rank, objective } = objectiveRank(i);
  const word = level(rank);
  const row = h('div', { class: 'src-row', 'aria-label': `${SOURCE_WORDS[i.name].title}: ${word}` },
    icon(i.name === 'building' ? 'neighbors' : i.name),
    h('div', { class: 'src-body' },
      h('div', { class: 'src-top' },
        h('span', { class: 'v' }, SOURCE_WORDS[i.name].title),
        h('span', { class: `lvl ${word.toLowerCase()}` }, word)),
      h('div', { class: `rank-bar${i.ticked ? ' ticked' : ''}`, 'aria-hidden': 'true' }, h('i', { style: `width: ${Math.max(2, rank)}%` })),
      i.ticked ? h('div', { class: 'tags' }, h('span', { class: 'pill ink' }, 'Matters to you')) : null));
  return tipped(row, sourceLines(i, { groundFloorCommercial: score.unit.ground_floor_commercial }), [
    objective ? `The building’s typical apartment, all hours alike: quieter than ${pct(rank)} of Manhattan.` : null,
    `For your floor, side and hours: quieter than ${pct(i.quieter_than)} · ${Math.round(i.weight)}% of your score.`,
    cap ? (cap.applied ? `Holds your score at ${cap.cap}.` : `Loud enough on its own to hold it at ${cap.cap}.`) : null,
    i.temporary ? 'Temporary: it ends when the work does.' : null,
  ]);
}

/** One building tile: a single word, a green check when known, a red question mark when the listing is silent. */
function tileView(t: Tile, i: number): HTMLElement {
  const el = h('div', { class: `tile${t.known ? '' : ' missing'}`, 'aria-label': `${t.label}: ${t.known ? 'known' : 'not on the listing'}` },
    h('span', { class: 'mark', 'aria-hidden': 'true' }, t.known ? '✓' : '?'),
    h('span', null, t.label));
  return tipped(el, t.lines, [], i % 2 ? 'end' : 'start', true);
}

/**
 * What informed the score, to Rafa's design of 2026-10-29: the noise around the building, loudest first, then six
 * one-word tiles for what the listing said about the apartment. Each row and tile keeps its why in a hover card,
 * built by rules from the engine's evidence (lib/reasons.ts), so it reads the same with AI reading on or off.
 */
export function shapedCard(v: ResultView, on: { answers: () => void; fix: () => void }): HTMLElement {
  const { score } = v;
  const caps = new Map(capLines(score.caps).map((c) => [c.source, c]));
  const sources = [...score.ingredients].sort((a, b) => objectiveRank(a).rank - objectiveRank(b).rank);
  const aiOff = v.readerAi?.mode === 'basic';
  const grid = tiles(score, v.fields, v.observed, { aiOff, photos: aiOff ? 0 : v.photos.length, canPowerUp: v.canPowerUp });
  return h('section', { class: 'card shaped', 'aria-label': 'What informed your Hush score' },
    h('h3', null, 'What informed your Hush score'),
    h('div', { class: 'shaped-group' },
      h('h4', { class: 'eyebrow' }, 'Noise around it, loudest first'),
      h('div', { class: 'src-list' }, sources.map((i) => sourceRow(i, score, caps.get(i.name))))),
    h('div', { class: 'shaped-group' },
      h('h4', { class: 'eyebrow' }, 'Building parameters affecting noise'),
      h('div', { class: 'tiles' }, grid.map(tileView))),
    h('div', { class: 'shaped-links' },
      h('button', { type: 'button', class: 'link small', onclick: on.fix }, 'Something wrong? Fix what it read'),
      h('button', { type: 'button', class: 'link small', onclick: on.answers }, 'Change my answers')),
  );
}

export function fineprint(score: Score): HTMLElement {
  return h('p', { class: 'fine' },
    `Engine v2 against ${score.manhattan.buildings} Manhattan buildings standing for ${score.manhattan.apartments.toLocaleString('en-US')} apartments (sample of ${score.manhattan.as_of}); city data as of ${score.as_of ?? 'today'}. `,
    score.replayed_from === 'v1' ? 'Ranked in this panel from the hosted model’s ingredients until /v2/score is deployed; the numbers match the engine’s own. ' : '',
  );
}
