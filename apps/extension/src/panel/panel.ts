/**
 * The side panel: what was read, the three taps, the reader's turns live, then the verdict.
 *
 * Nothing leaves the browser until the renter presses "Score this apartment". Then the text they kept and the
 * photos they kept go to the Hush IQ API (lib/client.ts), never to a model directly; the API holds the keys.
 */
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
import { fineprint, hearCard, sawCard, sourcesCard, tapsCard, turnItem, verdictCard, workingItem } from './views.ts';

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

async function refreshMode(): Promise<void> {
  const s = await client.services();
  const live = s.reader === 'live';
  modePill.textContent = live ? 'Live' : 'Replay';
  modePill.className = `pill${live ? ' ink' : ''}`;
  modePill.title = live
    ? `The listing reader and verdict writer answer at ${CONFIG.apiBase}.`
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
        h('li', null, 'Check what it read, answer three taps once, and get the verdict.'))),
    h('section', { class: 'card' },
      h('details', { class: 'paste' },
        h('summary', null, 'Paste a listing instead'),
        paste,
        h('button', {
          type: 'button', class: 'btn block',
          onclick: () => {
            const t = paste.value.trim();
            if (t) review({ url: '', host: '', site: 'paste', title: 'Your paste', text: t, photos: [], postal: null, selection: false, captured_at: new Date().toISOString() });
          },
        }, 'Read this')),
      h('p', { class: 'small' }, 'Or select a listing’s text on any page, right-click, and choose “Score this with Hush IQ”.')),
  );
}

function readingPage(): void {
  stop();
  show(h('section', { class: 'card' }, h('div', { class: 'spinner' }, glyph('working'), h('span', null, 'Reading the page…'))));
}

// ---------------------------------------------------------------- review: what was read, trimmed by the renter

function placeNotes(t: string, c: Capture | null): HTMLElement[] {
  const out: HTMLElement[] = [];
  const place = checkPlace(t, c?.postal ?? null);
  if (place.inNyc === false) {
    out.push(h('div', { class: 'note warn' }, glyph('refused'), h('span', null, h('b', null, 'Outside New York City. '), `${place.why} Hush IQ scores apartments in the five boroughs only.`)));
  } else if (!extract(t).geocode) {
    out.push(h('div', { class: 'note' }, glyph('cant_tell'), h('span', null, h('b', null, 'No street address found yet. '),
      c?.site === 'other' ? 'This may not be a listing. ' : '', 'If you know the building, add it to the top of the text.')));
  }
  return out;
}

function review(c: Capture): void {
  stop();
  const blanked = redactContacts(c.text);
  capture = { ...c, text: blanked.text };
  c = capture;
  text = c.text;
  photoOn = c.photos.map(() => true);
  let draft: Answers = answers ?? { ...DEFAULT_ANSWERS };
  let editing = !answers;

  const notes = h('div', { style: 'display: grid; gap: 8px' }, placeNotes(text, c));
  const count = h('span', null);
  const setCount = () => (count.textContent = `${text.length.toLocaleString('en-US')} characters`);
  setCount();
  let t: number | undefined;
  const area = h('textarea', {
    rows: 12, 'aria-label': 'The listing text',
    oninput: (e: Event) => {
      text = (e.target as HTMLTextAreaElement).value;
      setCount();
      clearTimeout(t);
      t = window.setTimeout(() => notes.replaceChildren(...placeNotes(text, c)), 400);
      go.disabled = !text.trim();
    },
  });
  area.value = text;

  const photos = c.photos.length
    ? h('div', null,
      h('div', { class: 'photos' }, c.photos.map((src, i) => {
        const b: HTMLButtonElement = h('button', {
          type: 'button', class: 'photo', 'aria-pressed': 'true', title: 'Click to leave this photo out',
          onclick: () => {
            photoOn[i] = !photoOn[i];
            b.setAttribute('aria-pressed', String(photoOn[i]));
            photoNote.textContent = photoLine();
          },
        }, h('img', { src, alt: `Listing photo ${i + 1}`, loading: 'lazy', referrerpolicy: 'no-referrer' }), h('span', { class: 'n' }, String(i + 1)));
        return b;
      })),
      h('p', { class: 'small', style: 'margin-top: 6px' }))
    : null;
  const photoLine = () => {
    const n = photoOn.filter(Boolean).length;
    return `${n} of ${c.photos.length} photo${c.photos.length > 1 ? 's' : ''} kept. Click one to leave it out.`;
  };
  const photoNote = photos?.lastElementChild as HTMLElement | undefined ?? h('p');
  photoNote.textContent = photoLine();

  const you = h('div');
  const drawYou = () => {
    you.replaceChildren(editing
      ? tapsCard(draft, (a) => (draft = a))
      : h('div', { class: 'card you' }, h('span', null, forWhom(answers!)), h('button', { type: 'button', class: 'link', onclick: () => { editing = true; drawYou(); } }, 'Change')));
  };
  drawYou();

  const go = h('button', {
    type: 'button', class: 'btn block', disabled: !text.trim(),
    onclick: async () => {
      if (editing || !answers) {
        answers = draft;
        await saveAnswers(draft);
      }
      void score();
    },
  }, 'Score this apartment');

  const source = c.site === 'paste' ? 'Your paste' : c.selection ? 'Your selection' : `Read from ${SITE_NAMES[c.site] === 'this page' ? c.host || 'this page' : SITE_NAMES[c.site]}`;
  show(
    h('section', { class: 'card' },
      h('div', { class: 'block-head' }, h('span', { class: 'eyebrow' }, source), h('button', { type: 'button', class: 'link small', onclick: () => welcome() }, 'Start over')),
      c.site !== 'paste' ? h('div', { class: 'src' }, h('span', { class: 'title' }, c.title), c.host ? h('span', { class: 'host' }, c.host) : null) : null,
      notes,
      h('div', null,
        h('label', { class: 'q-title', for: 'listing-text' }, h('span', null, 'What it read'), h('small', null, 'Trim anything not about this apartment')),
        area,
        h('div', { class: 'count' }, count, h('span', null, blanked.count ? `${blanked.count} phone or email blanked` : 'Facts only: adjectives are ignored'))),
      photos),
    you,
    go,
    h('p', { class: 'small' }, `Pressing it sends this text${c.photos.length ? ' and the photos you kept' : ''} to the Hush IQ API to score. Nothing is stored.`),
  );
  area.id = 'listing-text';
}

// ---------------------------------------------------------------- the run: read, score, write

function stopCard(title: string, body: (Node | string)[], extra?: HTMLElement | null): void {
  show(
    h('section', { class: 'card' },
      h('h2', { style: 'font-size: 22px' }, title),
      h('p', { class: 'muted' }, ...body),
      extra ?? null,
      h('div', { class: 'actions' },
        h('button', { type: 'button', class: 'btn ghost small', onclick: () => capture && review({ ...capture, text }) }, 'Back to the text'),
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

  const list = h('ol', { class: 'turns', 'aria-live': 'polite' });
  const working = workingItem('Reading the listing…');
  list.append(working);
  const head = h('div', { class: 'block-head' }, h('h3', null, 'The reader'), h('span', { class: 'pill' }, h('span', { class: 'dot' }), 'Working'));
  const sub = h('p', { class: 'small' });
  show(
    h('section', { class: 'card' }, head, sub, list),
    h('button', { type: 'button', class: 'btn ghost block', onclick: () => { stop(); capture ? review({ ...capture, text }) : welcome(); } }, 'Stop'),
  );

  const kept = (capture?.photos ?? []).filter((_, i) => photoOn[i]);
  const svc = await client.services();
  sub.textContent = svc.reader === 'live'
    ? 'Muse Spark reads the listing through the Hush IQ API. Each step shows as it happens.'
    : 'Replay: fixed rules stand in for Muse Spark until the live reader is hosted. The score is real.';
  const input: ReadInput = { text, photos: [], answers: a };
  let sent: string[] = kept;
  if (svc.reader === 'live' && kept.length) {
    working.querySelector('.turn-title')!.textContent = 'Getting the photos…';
    const got = await inlinePhotos(kept, signal);
    input.photos = got.photos;
    if (got.photo_urls.length) input.photo_urls = got.photo_urls;
    sent = kept.filter((u) => !got.photo_urls.includes(u)).concat(got.photo_urls);
    working.querySelector('.turn-title')!.textContent = 'Reading the listing…';
  } else if (kept.length) {
    input.photo_urls = kept;
  }

  const onTurn = (t: ReaderTurn) => {
    if (signal.aborted) return;
    turns.push(t);
    list.insertBefore(turnItem(t), working);
    working.scrollIntoView({ block: 'nearest' });
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
  working.remove();

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
    score: first, verdict: null, dropped: 0, fields: result.fields, observed: result.observed,
    answers: answers ?? DEFAULT_ANSWERS, reader, writer: 'replay', photos,
  };
  const slot = { verdict: h('div'), hear: h('div'), sources: h('div'), fine: h('div') };
  const draw = () => {
    slot.verdict.replaceChildren(verdictCard(v));
    slot.hear.replaceChildren(hearCard(v));
    slot.sources.replaceChildren(sourcesCard(v.score));
    slot.fine.replaceChildren(fineprint(v.score));
  };
  const write = async () => {
    v.verdict = null;
    slot.hear.replaceChildren(hearCard(v));
    try {
      const got = await client.verdict({ score: v.score, answers: v.answers, fields: v.fields }, signal);
      const checked = client.checkCitations(got.verdict);
      v.verdict = checked.verdict;
      v.dropped = checked.dropped;
      v.writer = got.via;
    } catch (e) {
      if (signal.aborted) return;
      slot.hear.replaceChildren(h('section', { class: 'card' }, h('h3', null, 'What you’ll hear'), h('p', { class: 'muted' }, `The verdict writer did not answer: ${(e as Error).message}`)));
      return;
    }
    if (!signal.aborted) slot.hear.replaceChildren(hearCard(v));
  };

  const tapsSlot = h('div');
  let rescoring = 0;
  const change = () => {
    tapsSlot.replaceChildren(tapsCard(v.answers, async (a) => {
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
        await write();
      } catch (e) {
        slot.fine.replaceChildren(h('p', { class: 'fine' }, `Could not re-score: ${(e as Error).message}`));
      } finally {
        if (mine === rescoring) app.classList.remove('updating');
      }
    }, 'Your answers'));
    tapsSlot.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  draw();
  show(
    tapsSlot,
    slot.verdict,
    slot.hear,
    slot.sources,
    sawCard(v),
    traceDetails(),
    h('div', { class: 'actions' },
      h('button', { type: 'button', class: 'btn ghost small', onclick: change }, 'Change my answers'),
      h('button', { type: 'button', class: 'btn ghost small', onclick: () => capture && review({ ...capture, text }) }, 'Back to the text')),
    slot.fine,
  );
  await write();
}

// ---------------------------------------------------------------- what the service worker hands over

function handle(msg: CaptureMessage | undefined): void {
  if (!msg || msg.id === lastCaptureId) return;
  if (!msg.ok && msg.error === 'reading') return readingPage();
  lastCaptureId = msg.id;
  if (!msg.ok) return welcome(msg.error);
  review(msg.capture);
}

async function init(): Promise<void> {
  await load();
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
    if (changes.apiBase || changes.mode) {
      await load();
      client.forget();
      void refreshMode();
    }
    if (changes.answers && !changes.answers.newValue) answers = null;
  });
}

void init();
