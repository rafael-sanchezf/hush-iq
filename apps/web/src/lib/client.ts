/**
 * The demo's one door to the services. Each piece is live when its URL is set at build time (lib/env.ts) and a
 * replay otherwise, so the page works today and goes live service by service without a code change. A live
 * service that fails, errs or runs past its time is replaced by its stand-in for that run, and the page says so
 * (GO-11).
 */
import { ENV } from './env.ts';
import { mockRead } from './mock/reader.ts';
import { templateVerdict } from './mock/verdict.ts';
import { getScore, scoreSource } from './score.ts';
export { checkCitations } from './cite.ts';
import { fieldTurns, normalizeTurn } from './turns.ts';
import type { Answers, ReadInput, ReaderFields, ReaderResult, ReaderTurn, Score, Services, Verdict, VerdictInput } from './types.ts';


/** How long a live service may take before the page stops waiting and runs its stand-in. */
const READER_TIMEOUT_MS = 50_000;
const VERDICT_TIMEOUT_MS = 30_000;

/** What answered on the last run; `fallback` when the live service failed and the stand-in ran instead. */
const ran: { reader: Services['reader'] | null; verdict: Services['verdict'] | null } = { reader: null, verdict: null };

export function services(): Services {
  return {
    reader: ran.reader ?? (ENV.readerUrl ? 'live' : 'mock'),
    verdict: ran.verdict ?? (ENV.verdictUrl ? 'live' : 'mock'),
    score: scoreSource(),
  };
}

function withTimeout(signal: AbortSignal | undefined, ms: number): AbortSignal {
  const t = AbortSignal.timeout(ms);
  return signal ? AbortSignal.any([signal, t]) : t;
}

/** A 4xx the renter can act on (a listing too short, a bad header): shown, not replaced by the replay. */
class Refused extends Error {}

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
  const r = await fetch(`${ENV.readerUrl}/read`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', accept: 'text/event-stream' },
    body: JSON.stringify(input),
    signal,
  });
  if (!r.ok || !r.body) {
    const body = await r.json().catch(() => null);
    const message = body?.error ?? `The reader answered ${r.status}.`;
    // 408, 413 (a body over the host's cap) and 429 are the host's trouble, not the listing's.
    throw r.status >= 400 && r.status < 500 && ![408, 413, 429].includes(r.status) ? new Refused(message) : new Error(message);
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

/**
 * Read a listing. When the live reader fails, `onFallback` fires (the panel clears its turns) and the replay
 * reads it instead; services() then says `fallback` so the pill and the line under it say what ran.
 */
export async function read(
  input: ReadInput,
  onTurn: (t: ReaderTurn) => void,
  signal?: AbortSignal,
  onFallback?: (why: string) => void,
): Promise<ReaderResult> {
  if (!ENV.readerUrl) {
    ran.reader = 'mock';
    return mockRead(input, onTurn, signal);
  }
  try {
    const r = await liveRead(input, onTurn, withTimeout(signal, READER_TIMEOUT_MS));
    ran.reader = 'live';
    return r;
  } catch (e) {
    if (signal?.aborted || e instanceof Refused) throw e;
    ran.reader = 'fallback';
    onFallback?.((e as Error).name === 'TimeoutError' ? 'timeout' : (e as Error).message);
    return mockRead(input, onTurn, signal);
  }
}

// ---------------------------------------------------------------- score

function sameAnswers(s: Score, a: Answers): boolean {
  const ticks = [...s.answers.ticks].sort().join(',');
  return s.answers.sleep.from === a.sleep_from && s.answers.sleep.until === a.sleep_until
    && s.answers.day_bothers === a.day_bothers && ticks === [...a.bothers].sort().join(',');
}

/** The score for what the reader found and what the renter answered. Reuses the reader's when it matches. */
export async function score(result: ReaderResult, answers: Answers, address?: string, signal?: AbortSignal): Promise<Score> {
  const s = result.score as Score | null;
  if (!address && s?.engine === 'v2' && sameAnswers(s, answers)) return s;
  const where = address ?? s?.address?.query ?? result.location?.label ?? result.fields.address.value;
  if (!where) throw new Error('No address to score.');
  return getScore(where, { floor: result.fields.floor.value, position: result.position }, answers, signal);
}

// ---------------------------------------------------------------- verdict

export async function verdict(input: VerdictInput, signal?: AbortSignal): Promise<Verdict> {
  if (!ENV.verdictUrl) {
    ran.verdict = 'mock';
    await new Promise((r) => setTimeout(r, 350));
    return templateVerdict(input);
  }
  try {
    const r = await fetch(`${ENV.verdictUrl}/verdict`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(input),
      signal: withTimeout(signal, VERDICT_TIMEOUT_MS),
    });
    if (!r.ok) throw new Error(`The verdict writer answered ${r.status}.`);
    const v = (await r.json()) as Verdict;
    ran.verdict = 'live';
    return v;
  } catch (e) {
    if (signal?.aborted) throw e;
    ran.verdict = 'fallback';
    return templateVerdict(input);
  }
}

export type { ReaderFields };
