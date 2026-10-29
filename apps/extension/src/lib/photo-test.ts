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

/** The listing's address on its site, without share tokens and tracking. */
function linkOf(url: string): string {
  try {
    const u = new URL(url);
    return u.origin + u.pathname;
  } catch {
    return url;
  }
}

async function originalBytes(url: string): Promise<string | null> {
  try {
    const r = await fetch(url, { credentials: 'omit', signal: AbortSignal.timeout(15000) });
    const blob = r.ok ? await r.blob() : null;
    if (!blob || !READER_TYPES.includes(blob.type)) return null;
    return await new Promise<string>((resolve, reject) => {
      const fr = new FileReader();
      fr.onload = () => resolve(String(fr.result));
      fr.onerror = () => reject(fr.error);
      fr.readAsDataURL(blob);
    });
  } catch {
    return null;
  }
}

export interface Saved { folder: string; already: boolean; photos: number; missed: number }

export async function saveForPhotoTest(c: Capture, text: string): Promise<Saved> {
  const urls = c.photos.slice(0, READER_MAX_PHOTOS);
  const photos = (await Promise.all(urls.map(originalBytes))).filter((p): p is string => !!p);
  const r = await fetch(`${CONFIG.apiBase}/photo-test/save`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ url: linkOf(c.url), text, photos, photo_urls: urls, site: c.site, title: c.title }),
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error ?? `the local server answered ${r.status}`);
  return { folder: body.folder, already: !!body.already, photos: photos.length, missed: urls.length - photos.length };
}
