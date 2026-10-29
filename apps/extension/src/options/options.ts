/** The options page: where the API lives, AI reading on or off, live or replay, and the stored taps. */
import { DEFAULT_SETTINGS, forgetAnswers, load, loadAnswers, save, trimUrl } from '../lib/config.ts';
import { ownKeyCard } from './own-key.ts';
import type { Mode } from '../lib/config.ts';
import { forWhom } from '../lib/words.ts';

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const base = $<HTMLInputElement>('apiBase');
const ai = $<HTMLInputElement>('ai');
const status = $('status');

function radios(): HTMLInputElement[] {
  return [...document.querySelectorAll<HTMLInputElement>('input[name="mode"]')];
}

async function fill(): Promise<void> {
  const s = await load();
  base.value = s.apiBase;
  ai.checked = s.ai;
  for (const r of radios()) r.checked = r.value === s.mode;
  const a = await loadAnswers();
  $('answers').textContent = a ? forWhom(a) : 'Not answered yet. The panel asks the first time you score a listing.';
  $('forget').toggleAttribute('disabled', !a);
}

$('save').addEventListener('click', async () => {
  const url = trimUrl(base.value);
  try {
    const u = new URL(url);
    if (u.protocol !== 'https:' && !/^(localhost|127\.0\.0\.1)$/.test(u.hostname)) throw new Error('https only');
  } catch {
    status.textContent = 'That is not an https address (http works for localhost only).';
    return;
  }
  const mode = (radios().find((r) => r.checked)?.value ?? 'auto') as Mode;
  await save({ apiBase: url, mode, ai: ai.checked });
  status.textContent = 'Saved. The panel uses it from the next listing.';
});

$('reset').addEventListener('click', async () => {
  await save(DEFAULT_SETTINGS);
  await fill();
  status.textContent = 'Back to the hosted API, AI reading on, live when hosted.';
});

$('forget').addEventListener('click', async () => {
  await forgetAnswers();
  await fill();
  status.textContent = 'Forgotten. The panel will ask again.';
});

// The classmates' build only: the judged build has no own-key settings, not even hidden ones.
if (__BYOK__) void ownKeyCard().then((card) => $('ai-card').after(card));

void fill();
