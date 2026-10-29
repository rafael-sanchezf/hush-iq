/**
 * The panel's one door to the Hush IQ API. Adapted from the website (apps/web/src/lib/client.ts): the same
 * reader stream, score and verdict calls, with the API base and the mode from the options page (lib/config.ts).
 *
 * In `auto` mode each service is live when the API has it and replayed when it does not: a `HEAD` on the route
 * answers 404 while it is missing and 405 once it exists (FastAPI), so nothing is sent to a route that is not
 * there. The replay is labelled as such wherever it shows.
 */
import { CONFIG } from './config.ts';
import { mockRead } from './mock/reader.ts';
import { templateVerdict } from './mock/verdict.ts';
import { getScore, scoreSource } from './score.ts';
import { fieldTurns, normalizeTurn } from './turns.ts';
import type { Answers, ReadInput, ReaderResult, ReaderTurn, Score, Verdict, VerdictInput } from './types.ts';
export { checkCitations } from './cite.ts';

export type Live = 'live' | 'replay';

const probed = new Map<string, Promise<boolean>>();

/** Does the API have this route? Cached per API base for the life of the panel. */
function hasRoute(path: string): Promise<boolean> {
  const key = `${CONFIG.apiBase}${path}`;
  let p = probed.get(key);
  if (!p) {
    p = fetch(key, { method: 'HEAD', signal: AbortSignal.timeout(5000) })
      .then((r) => r.status !== 404)
      .catch(() => false);
    probed.set(key, p);
  }
  return p;
}

async function useLive(path: string): Promise<boolean> {
  if (CONFIG.mode === 'replay') return false;
  if (CONFIG.mode === 'live') return true;
  return hasRoute(path);
}

export async function services(): Promise<{ reader: Live; verdict: Live; score: 'v2' | 'v1-replay' }> {
  const [r, v] = await Promise.all([useLive('/read'), useLive('/verdict')]);
  return { reader: r ? 'live' : 'replay', verdict: v ? 'live' : 'replay', score: scoreSource() };
}

export function forget(): void {
  probed.clear();
}

// ---------------------------------------------------------------- reader

/** Server-sent events from a POST body: `event:` and `data:` lines, a blank line ends each event. */
async function* sse(body: ReadableStream<Uint8Array>): AsyncGenerator<{ event: string; data: string }> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (value) buf += decoder.decode(value, { stream: !done });
    let cut: number;
    while ((cut = buf.search(/\r?\n\r?\n/)) >= 0) {
      const block = buf.slice(0, cut);
      buf = buf.slice(cut).replace(/^\r?\n\r?\n/, '');
      let event = 'message';
      const data: string[] = [];
      for (const line of block.split(/\r?\n/)) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
      }
      if (data.length) yield { event, data: data.join('\n') };
    }
    if (done) return;
  }
}

async function liveRead(input: ReadInput, onTurn: (t: ReaderTurn) => void, signal?: AbortSignal): Promise<ReaderResult> {
  const r = await fetch(`${CONFIG.apiBase}/read`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', accept: 'text/event-stream' },
    body: JSON.stringify(input),
    signal,
  });
  if (!r.ok || !r.body) {
    const body = await r.json().catch(() => null);
    throw new Error(body?.error ?? `The reader answered ${r.status}.`);
  }
  let n = 0;
  for await (const { event, data } of sse(r.body)) {
    const parsed = JSON.parse(data);
    if (event === 'turn') onTurn(normalizeTurn(parsed, n++));
    else if (event === 'result') {
      // The live reader streams its tool steps; what it read is in the result. Show it in the panel too.
      for (const t of fieldTurns(parsed as ReaderResult, n++)) onTurn(t);
      return parsed as ReaderResult;
    }
    else if (event === 'error') throw new Error(parsed.error ?? parsed.message ?? 'The reader stopped.');
  }
  throw new Error('The reader closed the stream without a result.');
}

export async function read(input: ReadInput, onTurn: (t: ReaderTurn) => void, signal?: AbortSignal): Promise<{ result: ReaderResult; via: Live }> {
  if (await useLive('/read')) return { result: await liveRead(input, onTurn, signal), via: 'live' };
  return { result: await mockRead(input, onTurn, signal), via: 'replay' };
}

// ---------------------------------------------------------------- score

function sameAnswers(s: Score, a: Answers): boolean {
  const ticks = [...s.answers.ticks].sort().join(',');
  return s.answers.sleep.from === a.sleep_from && s.answers.sleep.until === a.sleep_until
    && s.answers.day_bothers === a.day_bothers && ticks === [...a.bothers].sort().join(',');
}

/** The score for what the reader found and what the renter answered. Reuses the reader's when it matches. */
export async function score(result: ReaderResult, answers: Answers, signal?: AbortSignal): Promise<Score> {
  const s = result.score as Score | null;
  if (s?.engine === 'v2' && sameAnswers(s, answers)) return s;
  const where = s?.address?.query ?? result.location?.label ?? result.fields.address.value;
  if (!where) throw new Error('No address to score.');
  return getScore(where, { floor: result.fields.floor.value, position: result.position }, answers, signal);
}

// ---------------------------------------------------------------- verdict

export async function verdict(input: VerdictInput, signal?: AbortSignal): Promise<{ verdict: Verdict; via: Live }> {
  if (!(await useLive('/verdict'))) {
    await new Promise((r) => setTimeout(r, 300));
    return { verdict: templateVerdict(input), via: 'replay' };
  }
  const r = await fetch(`${CONFIG.apiBase}/verdict`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(input),
    signal,
  });
  if (!r.ok) throw new Error(`The verdict writer answered ${r.status}.`);
  return { verdict: (await r.json()) as Verdict, via: 'live' };
}
