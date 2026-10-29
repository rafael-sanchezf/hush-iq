/**
 * Testing only: the Save button that files the open listing for the photo test (eval/photo_test, HIQ-47), in place
 * of pasting its text and copying each photo by hand into the labeler. It shows only when the panel talks to the
 * local dev server (dev/serve_all.py), which writes the next numbered folder. The photos are fetched here, in the
 * renter's own browser, from the page they are looking at; the server only writes files.
 */
import type { Capture } from './capture-types.ts';
import { CONFIG } from './config.ts';
import { toDataUrl } from './photos.ts';

export const canSave = (): boolean => /^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/.test(CONFIG.apiBase);

/** The listing's address on its site, without share tokens and tracking. */
function linkOf(url: string): string {
  try {
    const u = new URL(url);
    return u.origin + u.pathname;
  } catch {
    return url;
  }
}

export interface Saved { folder: string; photos: number; missed: number }

export async function saveForPhotoTest(c: Capture, text: string): Promise<Saved> {
  const got = await Promise.all(c.photos.map((u) => toDataUrl(u, AbortSignal.timeout(15000)).catch(() => null)));
  const photos = got.filter((p): p is string => !!p);
  const r = await fetch(`${CONFIG.apiBase}/photo-test/save`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ link: linkOf(c.url), text, photos, site: c.site, title: c.title }),
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error ?? `the local server answered ${r.status}`);
  return { folder: body.folder, photos: photos.length, missed: c.photos.length - photos.length };
}
