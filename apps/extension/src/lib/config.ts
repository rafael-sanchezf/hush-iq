/**
 * The extension's settings and the renter's three taps, in chrome.storage.local. The website fixes its service
 * URLs at build time (apps/web/src/lib/env.ts); the extension reads them here, set on the options page.
 *
 * - `apiBase`: one origin for every Hush IQ call: `POST /read`, `POST /verdict`, `GET /v2/score`, `GET /v1/score`.
 *   The build's default is the hosted API; the manifest's one host permission is that origin.
 * - `mode`: `auto` uses the live reader and verdict writer when the API has them and replays them otherwise;
 *   `replay` always replays; `live` never does, so a missing service is an error you can see.
 * - `aiMode`: when a model reads a listing (Rafa, 2026-10-29: browsing means scoring many listings fast, so AI reading
 *   is a power-up, not the default). `ask`: fixed rules score every listing in about a second and a button reads one
 *   with AI on request; `always`: every listing is read with AI; `off`: no model is ever called.
 * - `ai`: whether a run reads with AI unless told otherwise, `aiMode === 'always'`; sent as `X-HushIQ-AI` on `/read`
 *   and `/verdict` (lib/ai.ts). Off, the services run their rules reader and template writer.
 *
 * No model key is here. The judged build has none at all; the classmates' build keeps the renter's own key apart,
 * in lib/byok.ts, which the judged build never bundles.
 */
import type { Answers } from './types.ts';

declare const __API_BASE__: string;
export const DEFAULT_API_BASE: string = typeof __API_BASE__ === 'string' ? __API_BASE__ : 'https://hush-iq-api.vercel.app';
export const REPO_URL = 'https://github.com/rafael-sanchezf/hush-iq';

export type Mode = 'auto' | 'replay' | 'live';
export type AiMode = 'ask' | 'always' | 'off';
export const AI_MODES: AiMode[] = ['ask', 'always', 'off'];

export interface Settings {
  apiBase: string;
  mode: Mode;
  aiMode: AiMode;
  ai: boolean;
}

export const DEFAULT_SETTINGS: Settings = { apiBase: DEFAULT_API_BASE, mode: 'auto', aiMode: 'ask', ai: false };

export const trimUrl = (s: string | undefined) => (s ?? '').trim().replace(/\/+$/, '');

/** The live settings for this page; `load()` fills them from storage. */
export const CONFIG: Settings = { ...DEFAULT_SETTINGS };

export async function load(): Promise<Settings> {
  const got = await chrome.storage.local.get(['apiBase', 'mode', 'aiMode', 'ai']);
  CONFIG.apiBase = trimUrl(got.apiBase as string | undefined) || DEFAULT_API_BASE;
  CONFIG.mode = (['auto', 'replay', 'live'] as Mode[]).includes(got.mode as Mode) ? (got.mode as Mode) : 'auto';
  // Before the three modes there was one switch, `ai`: off stays off; on becomes the new default, AI on request.
  CONFIG.aiMode = AI_MODES.includes(got.aiMode as AiMode) ? (got.aiMode as AiMode) : got.ai === false ? 'off' : 'ask';
  CONFIG.ai = CONFIG.aiMode === 'always';
  return { ...CONFIG };
}

export async function save(s: Partial<Settings>): Promise<void> {
  const next: Partial<Settings> = { ...s };
  if (next.aiMode !== undefined) next.ai = next.aiMode === 'always';
  if (next.apiBase !== undefined) next.apiBase = trimUrl(next.apiBase) || DEFAULT_API_BASE;
  await chrome.storage.local.set(next);
  Object.assign(CONFIG, next);
}

// ---------------------------------------------------------------- the three taps, kept so a returning renter skips them

export async function loadAnswers(): Promise<Answers | null> {
  const { answers } = await chrome.storage.local.get('answers');
  const a = answers as Answers | undefined;
  if (!a || typeof a.sleep_from !== 'number' || typeof a.sleep_until !== 'number' || !Array.isArray(a.bothers)) return null;
  return { sleep_from: a.sleep_from, sleep_until: a.sleep_until, day_bothers: Boolean(a.day_bothers), bothers: a.bothers };
}

export function saveAnswers(a: Answers): Promise<void> {
  return chrome.storage.local.set({ answers: a });
}

export function forgetAnswers(): Promise<void> {
  return chrome.storage.local.remove('answers');
}
