/**
 * The score for an address, a unit and the renter's answers, in the `/v2/score` shape. Adapted from the website
 * (apps/web/src/lib/score.ts); the API base comes from the options page instead of the build.
 *
 * `/v2/score` first. When it is not deployed (404), the frozen model's ingredients come from `/v1/score` at a
 * facade-neutral unit and engine v2's ranking is replayed here (lib/replay/v2.ts). The website's four sample
 * buildings are recorded (lib/mock/fixtures), so they score without the network. Ingredients are cached per
 * address, so a changed answer re-scores at once.
 */
import { CONFIG } from './config.ts';
import type { Baseline, Unit, V1Response } from './replay/v2.ts';
import { scoreFromV1 } from './replay/v2.ts';
import type { Answers, Score } from './types.ts';

import bedford from './mock/fixtures/bedford.v1.json';
import claremont from './mock/fixtures/claremont.v1.json';
import ludlow from './mock/fixtures/ludlow.v1.json';
import w47 from './mock/fixtures/w47.v1.json';
import manhattan from './replay/manhattan.json';

const RECORDED: Record<string, V1Response> = {};
for (const [keys, doc] of [
  [['140 claremont ave', '140 claremont avenue'], claremont],
  [['310 west 47th street', '310 w 47th st', '310 west 47th st', '310 w 47th street'], w47],
  [['158 bedford ave', '158 bedford avenue'], bedford],
  [['140 ludlow st', '140 ludlow street'], ludlow],
] as const) {
  for (const k of keys) RECORDED[k] = doc as unknown as V1Response;
}

function recorded(address: string): V1Response | undefined {
  const street = address.toLowerCase().split(',')[0].replace(/\s+/g, ' ').replace(/\.$/, '').trim();
  return RECORDED[street];
}

const baseline = manhattan as unknown as Baseline;
const v1Cache = new Map<string, Promise<V1Response>>();
let v2Missing = false;

export class ScoreError extends Error {}

async function fetchJson(url: string, signal?: AbortSignal): Promise<{ status: number; body: unknown }> {
  const r = await fetch(url, { signal, headers: { accept: 'application/json' } });
  let body: unknown = null;
  try {
    body = await r.json();
  } catch {
    body = null;
  }
  return { status: r.status, body };
}

function v1Ingredients(address: string, signal?: AbortSignal): Promise<V1Response> {
  const hit = recorded(address);
  if (hit) return Promise.resolve(hit);
  const key = `${CONFIG.apiBase} ${address.trim().toLowerCase()}`;
  let p = v1Cache.get(key);
  if (!p) {
    const q = new URLSearchParams({ address, position: 'front' });
    p = fetchJson(`${CONFIG.apiBase}/v1/score?${q}`, signal).then(({ status, body }) => {
      if (status !== 200) {
        const detail = (body as { detail?: string } | null)?.detail;
        throw new ScoreError(detail ? `The score API could not find that address: ${detail}` : `The score API answered ${status}.`);
      }
      return body as V1Response;
    });
    p.catch(() => v1Cache.delete(key));
    v1Cache.set(key, p);
  }
  return p;
}

export function scoreSource(): 'v2' | 'v1-replay' {
  return v2Missing ? 'v1-replay' : 'v2';
}

const warmed = new Set<string>();

/**
 * Starts the city-data pulls for an address on the API before the reader asks for them. A first score of a building
 * takes 1 to 6 seconds on the server and a second one, under any spelling, about a tenth of a second, because the
 * pulls are cached by place. The live reader spends its first model turns reading before it scores, so a request
 * sent as the run starts finishes in that time. Only the address goes, to the same API the listing goes to; the
 * answer is not used.
 */
export function warm(address: string): void {
  const key = `${CONFIG.apiBase} ${address.trim().toLowerCase()}`;
  if (warmed.has(key) || recorded(address)) return;
  warmed.add(key);
  const path = v2Missing ? '/v1/score' : '/v2/score';
  void fetch(`${CONFIG.apiBase}${path}?${new URLSearchParams({ address })}`, { headers: { accept: 'application/json' } })
    .then((r) => r.body?.cancel())
    .catch(() => warmed.delete(key));
}

export async function getScore(address: string, unit: Unit, answers: Answers, signal?: AbortSignal): Promise<Score> {
  if (!v2Missing) {
    const q = new URLSearchParams({
      address,
      position: unit.position,
      sleep_from: String(answers.sleep_from),
      sleep_until: String(answers.sleep_until),
      day_bothers: String(answers.day_bothers),
    });
    if (unit.floor !== null) q.set('floor', String(unit.floor));
    if (answers.bothers.length) q.set('bothers', answers.bothers.join(','));
    try {
      const { status, body } = await fetchJson(`${CONFIG.apiBase}/v2/score?${q}`, signal);
      if (status === 200 && (body as Score | null)?.engine === 'v2') return body as Score;
      if (status === 404) v2Missing = true;
      else if (status === 502) throw new ScoreError((body as { detail?: string } | null)?.detail ?? 'The city data did not answer.');
    } catch (e) {
      if (e instanceof ScoreError || (e as Error).name === 'AbortError') throw e;
      v2Missing = true;
    }
  }
  const v1 = await v1Ingredients(address, signal);
  return scoreFromV1(v1, unit, answers, baseline);
}
