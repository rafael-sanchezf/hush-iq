/**
 * Bring your own key, in the classmates' build only (`npm run build:byok` sets __BYOK__). Every use of this file sits
 * behind `if (__BYOK__)`, so the judged build (`npm run build`) bundles none of it; tests/bundle.test.ts checks.
 *
 * The renter's key for Meta, OpenAI or Anthropic:
 * - lives in chrome.storage.local, never sync, which uploads to the Google account;
 * - leaves the browser only in the X-HushIQ-* headers of a request to the configured API base, over https, or plain
 *   http to this machine's own loopback for a local server, where it crosses no network. keyHeaders() is the gate;
 * - is never logged, and scrub() blanks it out of any text the server sends back before the panel shows it.
 */
import { CONFIG } from './config.ts';

export type Provider = 'meta' | 'openai' | 'anthropic';

export interface OwnKey {
  provider: Provider;
  key: string;
  /** Blank for the server's default for that provider. */
  model: string;
}

export const PROVIDERS: Record<Provider, { name: string; reader: string; keyPage: string | null }> = {
  meta: { name: 'Meta', reader: 'Muse Spark', keyPage: null },
  openai: { name: 'OpenAI', reader: 'OpenAI', keyPage: 'https://platform.openai.com/api-keys' },
  anthropic: { name: 'Anthropic (Claude)', reader: 'Claude', keyPage: 'https://platform.claude.com/settings/keys' },
};

const STORE = 'ownKey';

/** The saved key for this page; loadKey() fills it. */
export const OWN: { key: OwnKey | null } = { key: null };

export async function loadKey(): Promise<OwnKey | null> {
  const got = (await chrome.storage.local.get(STORE))[STORE] as Partial<OwnKey> | undefined;
  OWN.key = got && typeof got.key === 'string' && got.key && got.provider && got.provider in PROVIDERS
    ? { provider: got.provider, key: got.key, model: typeof got.model === 'string' ? got.model : '' }
    : null;
  return OWN.key;
}

export async function saveKey(k: OwnKey): Promise<void> {
  const clean: OwnKey = { provider: k.provider, key: k.key.trim(), model: k.model.trim() };
  await chrome.storage.local.set({ [STORE]: clean });
  OWN.key = clean;
}

export async function removeKey(): Promise<void> {
  await chrome.storage.local.remove(STORE);
  OWN.key = null;
}

export function keyChanged(changes: Record<string, unknown>): boolean {
  return STORE in changes;
}

/** A pasted string that could be a key: one token, long enough. The provider decides the rest. */
export function looksLikeKey(s: string): boolean {
  return /^\S{16,}$/.test(s.trim());
}

/** The first three and last four characters, the way the providers show their own keys. */
export function mask(key: string): string {
  const k = key.trim();
  return k.length < 16 ? '••••' : `${k.slice(0, 3)}…${k.slice(-4)}`;
}

const LOOPBACK = /^(localhost|127\.0\.0\.1|\[::1\])$/;

/** May the key go to this URL? Only to the configured API base, and only over https (or to this machine). */
export function keyMayGo(url: string): boolean {
  let u: URL;
  let base: URL;
  try {
    u = new URL(url);
    base = new URL(CONFIG.apiBase);
  } catch {
    return false;
  }
  if (u.origin !== base.origin) return false;
  return u.protocol === 'https:' || (u.protocol === 'http:' && LOOPBACK.test(u.hostname));
}

/** The provider, key and model headers for a request to `url`, or none when the key may not go there. */
export function keyHeaders(url: string, k: OwnKey | null = OWN.key): Record<string, string> {
  if (!k?.key || !keyMayGo(url)) return {};
  const h: Record<string, string> = { 'X-HushIQ-Provider': k.provider, 'X-HushIQ-Key': k.key };
  if (k.model) h['X-HushIQ-Model'] = k.model;
  return h;
}

/** Text with the key blanked out. The server promises never to echo it; this holds if it ever does. */
export function scrub(text: string, k: OwnKey | null = OWN.key): string {
  return k?.key ? text.split(k.key).join('[your key]') : text;
}

/** Whose model reads, when the renter has a key saved. */
export function readerName(): string | null {
  return OWN.key ? PROVIDERS[OWN.key.provider].reader : null;
}

/** POST /key-check: the server asks the provider for its free models list, so no tokens are spent. */
export async function checkKey(k: OwnKey): Promise<{ ok: boolean; message: string }> {
  const url = `${CONFIG.apiBase}/key-check`;
  if (!keyMayGo(url)) {
    return { ok: false, message: 'Your key goes over https only, and the Hush IQ API address above is not https.' };
  }
  let r: Response;
  try {
    r = await fetch(url, { method: 'POST', headers: keyHeaders(url, k), signal: AbortSignal.timeout(15000) });
  } catch {
    return { ok: false, message: `Could not reach ${CONFIG.apiBase}.` };
  }
  if (r.status === 404) return { ok: false, message: 'This Hush IQ API cannot check keys yet (no POST /key-check).' };
  const body = (await r.json().catch(() => null)) as { ok?: boolean; message?: string } | null;
  const ok = r.ok && body?.ok === true;
  const said = typeof body?.message === 'string' ? scrub(body.message, k) : '';
  return { ok, message: said || (ok ? `The ${PROVIDERS[k.provider].name} key works.` : `The key check answered ${r.status}.`) };
}
