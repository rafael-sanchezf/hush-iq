/**
 * The side panel: the three questions, one at a time, the first time only; then the verdict and the source ranks,
 * with what the reader took from the listing folded away. No written paragraph: Rafa cut it, 2026-10-29.
 *
 * What the page gave stays out of sight. The renter sees it only when it falls short (no address, outside the city,
 * very little text), with a way to fix it (Rafa, 2026-10-29). Nothing leaves the browser until the renter clicks
 * Hush IQ on a listing, or pastes one, and has answered the questions once. Then the text and the photos go to the
 * Hush IQ API (lib/client.ts), never to a model directly; the API holds the keys. In the classmates' build a renter
 * may add their own key, which goes to the same API in a header (lib/byok.ts).
 */
import { keyChanged, loadKey, readerName } from '../lib/byok.ts';
import type { Capture, CaptureMessage } from '../lib/capture-types.ts';
import { SITE_NAMES } from '../lib/capture-types.ts';
import * as client from '../lib/client.ts';
import { CONFIG, REPO_URL, load, loadAnswers, saveAnswers } from '../lib/config.ts';
import { extract } from '../lib/mock/extract.ts';
import { checkPlace, sameBuilding } from '../lib/nyc.ts';
import { inlinePhotos } from '../lib/photos.ts';
import { redactContacts } from '../lib/redact.ts';
import type { Answers, ReadInput, ReaderResult, ReaderTurn, Score } from '../lib/types.ts';
import { DEFAULT_ANSWERS, addressLine, forWhom } from '../lib/words.ts';
import { clear, glyph, h } from './dom.ts';
import type { ResultView } from './views.ts';
import { fineprint, informedCard, questionsCard, sourcesCard, turnItem, verdictCard } from './views.ts';

const app = document.getElementById('app')!;
const modePill = document.getElementById('mode')!;

let answers: Answers | null = null;
let capture: Capture | null = null;
let text = '';
let photoOn: boolean[] = [];
let run: AbortController | null = null;
let lastCaptureId = '';

function show(...nodes: (Node | null)[]): void {
  clear(app);
  for (const n of nodes) if (n) app.append(n);
  window.scrollTo({ top: 0 });
}

function stop(): void {
  run?.abort();
  run = null;
}

// ---------------------------------------------------------------- the header's one status

/** Whose model reads when AI reading is on: Muse Spark, or the provider of the renter's own key. */
const modelName = () => (__BYOK__ && readerName()) || 'Muse Spark';

async function refreshMode(): Promise<void> {
  if (!CONFIG.ai) {
    modePill.textContent = 'AI off';
    modePill.className = 'pill';
    modePill.title = 'AI reading is off in settings: fixed rules read the listing. The scores are the same.';
    return;
  }
  const s = await client.services();
  const live = s.reader === 'live';
  modePill.textContent = live ? 'Live' : 'Replay';
  modePill.className = `pill${live ? ' ink' : ''}`;
  modePill.title = live
    ? `${modelName()} reads the listing through ${CONFIG.apiBase}.`
    : 'The live reader is not hosted yet, so fixed rules stand in for the model. The scores are real, from the hosted engine.';
}

// ---------------------------------------------------------------- welcome

function welcome(error?: string): void {
  stop();
  const paste = h('textarea', { rows: 7, placeholder: 'Paste the listing: address, floor, description.' });
  show(
    h('section', { class: 'hero' },
      h('h1', null, 'How loud is this apartment, for the way you sleep?'),
      h('p', null, 'Hush IQ reads the listing you have open and ranks the building against Manhattan, source by source, from eight city datasets.')),
    error ? h('div', { class: 'note warn' }, glyph('refused'), h('span', null, error)) : null,
    h('section', { class: 'card' },
      h('ol', { class: 'how' },
        h('li', null, 'Open a listing on StreetEasy, Zillow, Apartments.com or Craigslist.'),
        h('li', null, 'Click ', h('img', { class: 'toolbar-icon', src: 'icons/icon-32.png', alt: '' }), ' Hush IQ in the toolbar. It reads that page, and only when you click.'),
        h('li', null, 'Answer three quick questions the first time, and get the verdict.'))),
    h('section', { class: 'card' },
      h('details', { class: 'paste' },
        h('summary', null, 'Paste a listing instead'),
        paste,
        h('button', {
          type: 'button', class: 'btn block',
          onclick: () => {
            const t = paste.value.trim();
            if (t) start({ url: '', host: '', site: 'paste', title: 'Your paste', text: t, photos: [], postal: null, selection: false, captured_at: new Date().toISOString() });
          },
        }, 'Read this')),
      h('p', { class: 'small' }, 'Or select a listing’s text on any page, right-click, and choose “Score this with Hush IQ”.')),
  );
}

function readingPage(): void {
  stop();
  show(h('section', { class: 'card' }, h('div', { class: 'spinner' }, glyph('working'), h('span', null, 'Reading the page…'))));
}

// ---------------------------------------------------------------- a capture: check it, ask once, score

/** Under this much text a page capture likely missed the listing (a paste is the renter's own choice). */
const MIN_TEXT = 150;

interface Gap { title: string; body: string; address?: boolean; blocks?: boolean }

/** What keeps this capture from scoring well, or null when it is enough. Null means the renter never sees it. */
function gap(t: string, c: Capture): Gap | null {
  const place = checkPlace(t, c.postal ?? null);
  if (place.inNyc === false) {
    return { title: 'Outside New York City', body: `${place.why} Hush IQ scores apartments in the five boroughs only.`, blocks: true };
  }
  if (!extract(t).geocode) {
    return { title: 'No address found', address: true,
      body: `${c.site === 'other' ? 'This may not be a listing page. ' : ''}Hush IQ could not find the building’s street address here. Add it if you know it.` };
  }
  if (c.site !== 'paste' && t.trim().length < MIN_TEXT) {
    return { title: 'Only a little of this page was read', body: 'The floor or the side may be missing. Check the text below, or paste the listing instead.' };
  }
  return null;
}

function start(c: Capture): void {
  stop();
  capture = { ...c, text: redactContacts(c.text).text };
  text = capture.text;
  photoOn = capture.photos.map(() => true);
  const g = gap(text, capture);
  if (g) return fixCard(g);
  proceed();
}

function proceed(): void {
  if (!answers) return ask();
  void score();
}

function ask(): void {
  stop();
  show(
    questionsCard(answers ?? { ...DEFAULT_ANSWERS }, async (a) => {
      answers = a;
      await saveAnswers(a);
      void score();
    }),
    h('p', { class: 'small' }, `Asked once and kept on this computer. Scoring sends the listing${capture?.photos.length && CONFIG.ai ? ' and its photos' : ''} to the Hush IQ API; nothing is stored.`),
  );
}

/** The failsafe: what was read, shown only when it falls short or the renter asks to check it. */
function fixCard(g: Gap | null): void {
  stop();
  const c = capture;
  if (!c) return welcome();
  const area = h('textarea', { rows: 10, 'aria-label': 'What was read', oninput: (e: Event) => (text = (e.target as HTMLTextAreaElement).value) });
  area.value = text;
  const input = g?.address ? h('input', { type: 'text', placeholder: '310 West 47th Street, Manhattan', 'aria-label': 'The building’s address' }) : null;
  const go = () => {
    const a = input?.value.trim();
    if (a) text = `Address: ${a}\n\n${text}`;
    const again = a ? null : gap(text, c);
    if (again?.blocks) return fixCard(again);
    proceed();
  };
  const source = c.site === 'paste' ? 'Your paste' : c.selection ? 'Your selection' : `Read from ${SITE_NAMES[c.site] === 'this page' ? c.host || 'this page' : SITE_NAMES[c.site]}`;
  show(
    h('section', { class: 'card' },
      h('div', { class: 'block-head' }, h('span', { class: 'eyebrow' }, source), h('button', { type: 'button', class: 'link small', onclick: () => welcome() }, 'Start over')),
      g ? h('div', { class: `note${g.blocks ? ' warn' : ''}` }, glyph(g.blocks ? 'refused' : 'cant_tell'), h('span', null, h('b', null, `${g.title}. `), g.body)) : null,
      input,
      h('details', { class: 'paste', open: !g?.address }, h('summary', null, 'What was read'), area, h('p', { class: 'small' }, 'Trim anything not about this apartment.')),
      g?.blocks ? null : h('button', { type: 'button', class: 'btn block', onclick: go }, g ? 'Continue' : 'Score this apartment')),
  );
}

// ---------------------------------------------------------------- the run: read, score, write

function stopCard(title: string, body: (Node | string)[], extra?: HTMLElement | null): void {
  show(
    h('section', { class: 'card' },
      h('h2', { style: 'font-size: 22px' }, title),
      h('p', { class: 'muted' }, ...body),
      extra ?? null,
      h('div', { class: 'actions' },
        h('button', { type: 'button', class: 'btn ghost small', onclick: () => fixCard(null) }, 'Check what was read'),
        h('button', { type: 'button', class: 'btn ghost small', onclick: () => welcome() }, 'Start over'))),
    traceDetails(),
  );
}

let turns: ReaderTurn[] = [];

function traceDetails(open = false): HTMLElement | null {
  if (!turns.length) return null;
  return h('section', { class: 'card' },
    h('details', { class: 'trace', open },
      h('summary', null, `How the reader got here (${turns.length} step${turns.length > 1 ? 's' : ''})`),
      h('ol', { class: 'turns' }, turns.map(turnItem))));
}

function outside(why: string): void {
  stopCard('Outside New York City', [why ? `${why} ` : '', 'Hush IQ scores apartments in the five boroughs only, against the city’s own data.']);
}

function noAddress(): void {
  const input = h('input', { type: 'text', placeholder: '310 West 47th Street, Manhattan', 'aria-label': 'The building’s address' });
  const add = h('button', {
    type: 'button', class: 'btn block',
    onclick: () => {
      const a = input.value.trim();
      if (!a) return;
      text = `Address: ${a}\n\n${text}`;
      void score();
    },
  }, 'Score with this address');
  stopCard('No address in this listing', [
    'What was read has no street address, so there is no building to score. Listings often hold it back until you ask. If you know it, add it here; it goes in as the first line of the text.',
  ], h('div', { style: 'display: grid; gap: 8px' }, input, add));
}

async function score(): Promise<void> {
  stop();
  const ctl = new AbortController();
  run = ctl;
  const signal = ctl.signal;
  const a = answers ?? DEFAULT_ANSWERS;
  turns = [];

  const place = checkPlace(text, capture?.postal ?? null);
  if (place.inNyc === false) return outside(place.why);

  // One line of progress; the reader's own steps stay out of sight (they show only if it stops).
  const status = h('span', null, 'Reading the listing…');
  show(
    h('section', { class: 'card' }, h('div', { class: 'spinner' }, glyph('working'), status)),
    h('button', { type: 'button', class: 'btn ghost block', onclick: () => { stop(); welcome(); } }, 'Stop'),
  );

  const kept = (capture?.photos ?? []).filter((_, i) => photoOn[i]);
  const svc = await client.services();
  const input: ReadInput = { text, photos: [], answers: a };
  let sent: string[] = kept;
  // The rules reader reads text only, so with AI reading off the photos stay in the browser.
  if (!CONFIG.ai) {
    sent = [];
  } else if (svc.reader === 'live' && kept.length) {
    status.textContent = 'Getting the photos…';
    const got = await inlinePhotos(kept, signal);
    input.photos = got.photos;
    if (got.photo_urls.length) input.photo_urls = got.photo_urls;
    sent = kept.filter((u) => !got.photo_urls.includes(u)).concat(got.photo_urls);
    status.textContent = 'Reading the listing…';
  } else if (kept.length) {
    input.photo_urls = kept;
  }

  const onTurn = (t: ReaderTurn) => {
    if (!signal.aborted) turns.push(t);
  };

  let result: ReaderResult;
  let via: client.Live;
  try {
    ({ result, via } = await client.read(input, onTurn, signal));
  } catch (e) {
    if (signal.aborted) return;
    return stopCard('The reader stopped', [(e as Error).message]);
  }
  if (signal.aborted) return;
  status.textContent = 'Scoring the building…';

  if (result.needs?.includes('address') || (!result.score && result.fields.address.status !== 'read')) return noAddress();
  if (result.needs?.includes('nyc')) return outside(result.notes?.[0] ?? '');
  const found = (result.score as Score | null)?.address?.label ?? result.location?.label ?? '';
  if (via === 'live' && result.fields.address.value && found && !sameBuilding(result.fields.address.value, found)) {
    return outside(`The closest New York City match was ${addressLine(found)}, not “${result.fields.address.value}”.`);
  }

  let s: Score;
  try {
    s = await client.score(result, a, signal);
  } catch (e) {
    if (signal.aborted) return;
    return stopCard('Could not score this building', [(e as Error).message]);
  }
  if (signal.aborted) return;
  await showResult(result, s, via, sent, signal);
}

// ---------------------------------------------------------------- the verdict

async function showResult(result: ReaderResult, first: Score, reader: client.Live, photos: string[], signal: AbortSignal): Promise<void> {
  const v: ResultView = {
    score: first, fields: result.fields, observed: result.observed,
    answers: answers ?? DEFAULT_ANSWERS, reader, photos, readerAi: result.ai ?? null,
  };
  const slot = { verdict: h('div'), sources: h('div'), fine: h('div') };
  const draw = () => {
    slot.verdict.replaceChildren(verdictCard(v));
    slot.sources.replaceChildren(sourcesCard(v.score));
    slot.fine.replaceChildren(fineprint(v.score));
  };

  const tapsSlot = h('div');
  let rescoring = 0;
  const change = () => {
    tapsSlot.replaceChildren(questionsCard(v.answers, async (a) => {
      tapsSlot.replaceChildren();
      const mine = ++rescoring;
      answers = a;
      v.answers = a;
      await saveAnswers(a);
      app.classList.add('updating');
      try {
        const s = await client.score(result, a, signal);
        if (mine !== rescoring || signal.aborted) return;
        v.score = s;
        draw();
      } catch (e) {
        slot.fine.replaceChildren(h('p', { class: 'fine' }, `Could not re-score: ${(e as Error).message}`));
      } finally {
        if (mine === rescoring) app.classList.remove('updating');
      }
    }, 'Update the score'));
    tapsSlot.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  draw();
  const basic = result.ai?.mode === 'basic' && result.ai.message;
  show(
    basic ? h('div', { class: 'note' }, glyph('cant_tell'), h('span', null, result.ai!.message!)) : null,
    tapsSlot,
    slot.verdict,
    slot.sources,
    informedCard(v),
    h('div', { class: 'actions' },
      h('button', { type: 'button', class: 'btn ghost small', onclick: change }, 'Change my answers'),
      h('button', { type: 'button', class: 'btn ghost small', onclick: () => fixCard(null) }, 'Check what was read')),
    slot.fine,
  );
}

// ---------------------------------------------------------------- what the service worker hands over

function handle(msg: CaptureMessage | undefined): void {
  if (!msg || msg.id === lastCaptureId) return;
  if (!msg.ok && msg.error === 'reading') return readingPage();
  lastCaptureId = msg.id;
  if (!msg.ok) return welcome(msg.error);
  start(msg.capture);
}

async function init(): Promise<void> {
  await load();
  if (__BYOK__) await loadKey();
  answers = await loadAnswers();
  document.getElementById('settings')!.addEventListener('click', () => chrome.runtime.openOptionsPage());
  (document.getElementById('repo') as HTMLAnchorElement).href = REPO_URL;
  void refreshMode();

  const { capture: msg } = await chrome.storage.session.get('capture');
  if (msg) handle(msg as CaptureMessage);
  else welcome();

  chrome.storage.session.onChanged.addListener((changes) => {
    if (changes.capture?.newValue) handle(changes.capture.newValue as CaptureMessage);
  });
  chrome.storage.local.onChanged.addListener(async (changes) => {
    if (changes.apiBase || changes.mode || changes.ai || (__BYOK__ && keyChanged(changes))) {
      await load();
      if (__BYOK__) await loadKey();
      client.forget();
      void refreshMode();
    }
    if (changes.answers && !changes.answers.newValue) answers = null;
  });
}

void init();
