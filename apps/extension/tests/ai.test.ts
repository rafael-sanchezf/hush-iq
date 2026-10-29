// The AI switch and the renter's own key, through the real client (src/lib/client.ts) against a fake API: which
// headers go where, what runs when the switch is off and the services are out of reach, and that the key reaches
// neither the console nor an error message. The client is bundled here with esbuild, as the build does.
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, beforeEach, test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const root = fileURLToPath(new URL('..', import.meta.url));
const tmp = mkdtempSync(join(tmpdir(), 'hush-iq-ai-'));
after(() => rmSync(tmp, { recursive: true, force: true }));

const API = 'https://api.example.test';
const KEY = 'sk-test-FAKE0123456789abcdefFAKE';

async function bundle(byok: boolean) {
  const outfile = join(tmp, `client-${byok}.mjs`);
  await build({
    stdin: {
      contents: [
        "export * as client from './src/lib/client.ts';",
        "export * as byok from './src/lib/byok.ts';",
        "export { CONFIG } from './src/lib/config.ts';",
        "export { warm } from './src/lib/score.ts';",
      ].join('\n'),
      resolveDir: root,
      loader: 'ts',
    },
    bundle: true,
    format: 'esm',
    platform: 'neutral',
    outfile,
    define: { __API_BASE__: JSON.stringify(API), __BYOK__: String(byok) },
    logLevel: 'error',
  });
  return import(outfile);
}

// ---------------------------------------------------------------- a browser, as far as the client needs one

const store = new Map<string, unknown>();
(globalThis as any).chrome = {
  storage: {
    local: {
      get: async (keys: string | string[]) =>
        Object.fromEntries((typeof keys === 'string' ? [keys] : keys).filter((k) => store.has(k)).map((k) => [k, store.get(k)])),
      set: async (o: Record<string, unknown>) => Object.entries(o).forEach(([k, v]) => store.set(k, v)),
      remove: async (k: string) => store.delete(k),
    },
  },
};

interface Call { url: string; method: string; headers: Record<string, string> }
let calls: Call[] = [];
let answer: (url: URL, method: string) => Response | Promise<Response>;

globalThis.fetch = (async (input: string | URL, init: RequestInit = {}) => {
  const url = String(input);
  calls.push({ url, method: init.method ?? 'GET', headers: Object.fromEntries(new Headers(init.headers).entries()) });
  return answer(new URL(url), init.method ?? 'GET');
}) as typeof fetch;

const said: string[] = [];
for (const level of ['log', 'info', 'warn', 'error', 'debug', 'trace'] as const) {
  const real = console[level];
  console[level] = (...args: unknown[]) => {
    said.push(args.map((a) => (a instanceof Error ? `${a.message} ${a.stack}` : typeof a === 'string' ? a : JSON.stringify(a))).join(' '));
    if (level !== 'debug') real.apply(console, args);
  };
}

// ---------------------------------------------------------------- the fake API

const field = (value: unknown, quote?: string) => quote
  ? { value, status: 'read', evidence: [{ source: 'text', quote }] }
  : { value: null, status: 'cant_tell', evidence: [] };
const FIELDS = {
  address: field('310 West 47th Street', '310 West 47th Street'),
  unit: field(null),
  floor: field(4, '4th floor'),
  side: field(null),
};
const MODEL_AI = { mode: 'model', provider: 'meta', model: 'muse-spark-1.3', key: 'house', reason: null, message: null };
const RESULT = { fields: FIELDS, position: 'unknown', observed: {}, score: null, trace: [], status: 'complete', mode: 'live', ai: MODEL_AI };
const SCORE = JSON.parse(readFileSync(join(root, 'tests/fixtures/v2-full-w47.json'), 'utf8'));
const VERDICT = { evidence: [{ id: 'E1', text: 'A line.' }], sentences: [{ text: 'A sentence.', cites: ['E1'] }], writer: 'muse-spark-1.3', ai: MODEL_AI };
const TEXT = '310 West 47th Street, Manhattan. One bedroom on the 4th floor.';
const ANSWERS = { sleep_from: 23, sleep_until: 7, day_bothers: false, bothers: [] };

const sse = (event: string, data: unknown) => new Response(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`, { headers: { 'content-type': 'text/event-stream' } });
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

/** A healthy API: both services hosted, v2 score not yet, key check passes. */
function healthy(url: URL, method: string): Response {
  if (method === 'HEAD') return new Response(null, { status: 405 });
  if (url.pathname === '/read') return sse('result', RESULT);
  if (url.pathname === '/verdict') return json(VERDICT);
  if (url.pathname === '/key-check') return json({ ok: true, provider: 'openai', message: 'The key works.' });
  return json({ detail: 'Not Found' }, 404);
}

const judged = await bundle(false);
const classmates = await bundle(true);

beforeEach(async () => {
  calls = [];
  answer = healthy;
  store.clear();
  for (const m of [judged, classmates]) {
    m.CONFIG.apiBase = API;
    m.CONFIG.mode = 'auto';
    m.CONFIG.ai = true;
    m.client.forget();
    await m.byok.removeKey();
  }
});

const hushHeaders = (c: Call) => Object.keys(c.headers).filter((h) => h.startsWith('x-hushiq-'));
const to = (path: string) => (c: Call) => c.method === 'POST' && new URL(c.url).pathname === path;

async function readAndWrite(m: typeof judged) {
  const { result } = await m.client.read({ text: TEXT, photos: [], answers: ANSWERS }, () => {});
  const { verdict } = await m.client.verdict({ score: SCORE, answers: ANSWERS, fields: FIELDS });
  return { result, verdict };
}

// ---------------------------------------------------------------- the switch, in every build

test('AI on: /read and /verdict say so, and nothing else carries an X-HushIQ header', async () => {
  await readAndWrite(judged);
  assert.equal(calls.find(to('/read'))?.headers['x-hushiq-ai'], 'on');
  assert.equal(calls.find(to('/verdict'))?.headers['x-hushiq-ai'], 'on');
  for (const c of calls.filter((c) => !to('/read')(c) && !to('/verdict')(c))) assert.deepEqual(hushHeaders(c), [], c.url);
  for (const c of calls) assert.ok(!('x-hushiq-key' in c.headers));
});

test('AI off: the services are called with off and their basic result is shown as it comes', async () => {
  judged.CONFIG.ai = false;
  const basic = { ...MODEL_AI, mode: 'basic', provider: null, model: null, key: null, reason: 'switched_off', message: 'AI reading is off.' };
  answer = (url, method) => method === 'POST' && url.pathname === '/read' ? sse('result', { ...RESULT, ai: basic }) : healthy(url, method);
  const { result } = await readAndWrite(judged);
  assert.equal(calls.find(to('/read'))?.headers['x-hushiq-ai'], 'off');
  assert.equal(calls.find(to('/verdict'))?.headers['x-hushiq-ai'], 'off');
  assert.equal(result.ai.message, 'AI reading is off.');
});

test('AI off and the services out of reach: the rules reader and template run here, labelled basic', async () => {
  judged.CONFIG.ai = false;
  answer = (url, method) => {
    if (method === 'HEAD') return new Response(null, { status: 405 });
    if (url.pathname === '/read') throw new TypeError('fetch failed');
    if (url.pathname === '/verdict') return json({ error: 'busy' }, 503);
    return json({ detail: 'Not Found' }, 404); // no /v2/score: the recorded v1 ingredients for this address replay
  };
  const { result, verdict } = await readAndWrite(judged);
  assert.equal(result.ai.mode, 'basic');
  assert.equal(result.ai.reason, 'switched_off');
  assert.equal(result.fields.floor.value, 4);
  assert.equal(verdict.writer, 'template');
  assert.equal(verdict.ai.mode, 'basic');
});

test('AI on and the reader out of reach: an error to show, not a silent fallback', async () => {
  answer = (url, method) => method === 'POST' && url.pathname === '/read' ? json({ error: 'down' }, 502) : healthy(url, method);
  await assert.rejects(judged.client.read({ text: TEXT, photos: [], answers: ANSWERS }, () => {}), /down/);
});

test('warming the score sends the address alone, once, with no AI or key header', async () => {
  await saveKey(classmates);
  classmates.warm('245 West 54th Street, Manhattan');
  classmates.warm('245 West 54th Street, Manhattan');
  classmates.warm('310 West 47th Street, Manhattan'); // recorded: never sent
  await new Promise((r) => setTimeout(r, 20));
  const sent = calls.filter((c) => c.url.includes('/score'));
  assert.equal(sent.length, 1);
  const u = new URL(sent[0].url);
  assert.equal(u.origin, API);
  assert.equal(u.pathname, '/v2/score');
  assert.deepEqual([...u.searchParams.keys()], ['address']);
  assert.deepEqual(hushHeaders(sent[0]), []);
});

// ---------------------------------------------------------------- the renter's own key, classmates' build only

async function saveKey(m: typeof classmates, base = API) {
  m.CONFIG.apiBase = base;
  await m.byok.saveKey({ provider: 'openai', key: KEY, model: 'gpt-test' });
}

test('own key: provider, key and model go to /read, /verdict and /key-check on the API base, and nowhere else', async () => {
  await saveKey(classmates);
  const { result } = await readAndWrite(classmates);
  await classmates.client.score(result, ANSWERS); // GET /v2/score: no model, no key
  const check = await classmates.byok.checkKey(classmates.byok.OWN.key);
  assert.ok(check.ok);

  const carried = calls.filter((c) => 'x-hushiq-key' in c.headers);
  assert.deepEqual(carried.map((c) => new URL(c.url).pathname).sort(), ['/key-check', '/read', '/verdict']);
  for (const c of carried) {
    assert.equal(new URL(c.url).origin, API);
    assert.equal(c.headers['x-hushiq-key'], KEY);
    assert.equal(c.headers['x-hushiq-provider'], 'openai');
    assert.equal(c.headers['x-hushiq-model'], 'gpt-test');
  }
  assert.ok(calls.some((c) => new URL(c.url).pathname === '/v2/score'));
  for (const c of calls) assert.ok(!c.url.includes(KEY), 'the key is never in a URL');
});

test('own key: never over plain http to another machine, never to another origin', async () => {
  await saveKey(classmates, 'http://api.example.test');
  await readAndWrite(classmates);
  assert.ok(calls.length > 0);
  for (const c of calls) assert.ok(!('x-hushiq-key' in c.headers), c.url);
  const before = calls.length;
  const check = await classmates.byok.checkKey(classmates.byok.OWN.key);
  assert.equal(check.ok, false);
  assert.equal(calls.length, before, 'no key check is sent over http');

  classmates.CONFIG.apiBase = API;
  assert.equal(classmates.byok.keyMayGo('https://other.example.test/read'), false);
  assert.equal(classmates.byok.keyMayGo(`${API}/read`), true);
  classmates.CONFIG.apiBase = 'http://localhost:8000';
  assert.equal(classmates.byok.keyMayGo('http://localhost:8000/read'), true, 'this machine, for a local server');
});

test('the judged build sends no key even when one is in storage', async () => {
  store.set('ownKey', { provider: 'openai', key: KEY, model: '' });
  await readAndWrite(judged);
  for (const c of calls) assert.deepEqual(hushHeaders(c).filter((h) => h !== 'x-hushiq-ai'), [], c.url);
});

test('the key reaches neither the console nor an error message, even when the server echoes it', async () => {
  await saveKey(classmates);
  said.length = 0;
  const echo = `Incorrect API key provided: ${KEY}.`;
  const errors: string[] = [];

  answer = (url, method) => method === 'POST' && url.pathname === '/read' ? json({ error: echo }, 401) : healthy(url, method);
  await classmates.client.read({ text: TEXT, photos: [], answers: ANSWERS }, () => {}).catch((e: Error) => errors.push(e.message));

  answer = (url, method) => method === 'POST' && url.pathname === '/read' ? sse('error', { error: echo }) : healthy(url, method);
  await classmates.client.read({ text: TEXT, photos: [], answers: ANSWERS }, () => {}).catch((e: Error) => errors.push(e.message));

  answer = (url, method) => method === 'POST' && url.pathname === '/verdict' ? json({ error: echo }, 500) : healthy(url, method);
  await classmates.client.verdict({ score: SCORE, answers: ANSWERS, fields: FIELDS }).catch((e: Error) => errors.push(e.message));

  answer = (url, method) => method === 'POST' && url.pathname === '/key-check' ? json({ ok: false, provider: 'openai', message: echo }, 401) : healthy(url, method);
  const check = await classmates.byok.checkKey(classmates.byok.OWN.key);
  errors.push(check.message);

  answer = () => { throw new TypeError(`connect failed ${KEY}`); };
  classmates.client.forget();
  errors.push((await classmates.byok.checkKey(classmates.byok.OWN.key)).message);

  assert.equal(errors.length, 5);
  for (const m of errors) assert.ok(!m.includes(KEY), m);
  assert.ok(errors.some((m) => m.includes('[your key]')), 'an echoed key shows as a blank');
  for (const line of said) assert.ok(!line.includes(KEY), line);
  assert.equal(classmates.byok.mask(KEY), 'sk-…FAKE');
});
