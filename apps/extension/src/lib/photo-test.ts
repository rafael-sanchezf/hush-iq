/**
 * Testing only: the Save button that files the open listing for the photo test (HIQ-47), in place of pasting its
 * text and copying each photo by hand into the labeler. It shows only when the panel talks to the local dev server
 * (dev/serve_all.py), which writes the next numbered folder in ~/Documents/hush-iq/photo_test, outside git.
 *
 * As the eval session asked (2026-10-29): the same photos, in the same order, that the extension sends the reader
 * (12 at most), in their original bytes, fetched here in the renter's own browser from the page they are looking
 * at, so the server never contacts a listing site. HEIC and AVIF are left out: the reader refuses them.
 */
import type { Capture } from './capture-types.ts';
import { CONFIG } from './config.ts';

export const canSave = (): boolean => /^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/.test(CONFIG.apiBase);

const READER_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/gif'];
const READER_MAX_PHOTOS = 12;
const READER_MAX_BYTES = 8 * 1024 * 1024;

/** The listing's address on its site, without share tokens and tracking. */
function linkOf(url: string): string {
  try {
    const u = new URL(url);
    return u.origin + u.pathname;
  } catch {
    return url;
  }
}

type Got = { data: string } | { skip: 'format' | 'size' | 'fetch' };

async function originalBytes(url: string): Promise<Got> {
  try {
    const r = await fetch(url, { credentials: 'omit', signal: AbortSignal.timeout(15000) });
    const blob = r.ok ? await r.blob() : null;
    if (!blob) return { skip: 'fetch' };
    if (!READER_TYPES.includes(blob.type)) return { skip: 'format' };   // HEIC and AVIF: the reader refuses them
    if (blob.size > READER_MAX_BYTES) return { skip: 'size' };
    const data = await new Promise<string>((resolve, reject) => {
      const fr = new FileReader();
      fr.onload = () => resolve(String(fr.result));
      fr.onerror = () => reject(fr.error);
      fr.readAsDataURL(blob);
    });
    return { data };
  } catch {
    return { skip: 'fetch' };
  }
}

export interface Saved { folder: string; already: boolean; photos: number; skipped: Record<'format' | 'size' | 'fetch', number> }

export async function saveForPhotoTest(c: Capture, text: string): Promise<Saved> {
  const urls = c.photos.slice(0, READER_MAX_PHOTOS);
  const got = await Promise.all(urls.map(originalBytes));
  const kept = urls.map((u, i) => [u, got[i]] as const).filter((x): x is readonly [string, { data: string }] => 'data' in x[1]);
  const skipped = { format: 0, size: 0, fetch: 0 };
  for (const g of got) if ('skip' in g) skipped[g.skip] += 1;
  const r = await fetch(`${CONFIG.apiBase}/photo-test/save`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      url: linkOf(c.url), text, site: c.site, title: c.title, captured_at: c.captured_at,
      photos: kept.map(([, g]) => g.data), photo_urls: kept.map(([u]) => u), version: chrome.runtime.getManifest().version,
    }),
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error ?? `the local server answered ${r.status}`);
  return { folder: body.folder, already: !!body.already, photos: kept.length, skipped };
}
