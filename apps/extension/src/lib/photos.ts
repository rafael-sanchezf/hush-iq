/**
 * The reader takes photos as JPEG data URLs (services/agent/CONTRACT.md). A listing's photos live on the listing
 * site's image host. The extension may read the listing sites' own hosts and zillowstatic.com (StreetEasy's and
 * Zillow's photos); any other host works when it allows cross-origin reads, and the rest go as `photo_urls`.
 * Downscaled to 1280 px on the long side, as the website does with uploads.
 */
const LONG_SIDE = 1280;
const MAX_INLINE = 8;

export async function toDataUrl(url: string, signal?: AbortSignal): Promise<string> {
  const r = await fetch(url, { signal, mode: 'cors', credentials: 'omit' });
  if (!r.ok) throw new Error(String(r.status));
  const bitmap = await createImageBitmap(await r.blob());
  const scale = Math.min(1, LONG_SIDE / Math.max(bitmap.width, bitmap.height));
  const canvas = new OffscreenCanvas(Math.round(bitmap.width * scale), Math.round(bitmap.height * scale));
  canvas.getContext('2d')!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  const blob = await canvas.convertToBlob({ type: 'image/jpeg', quality: 0.82 });
  return await new Promise<string>((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(String(fr.result));
    fr.onerror = () => reject(fr.error);
    fr.readAsDataURL(blob);
  });
}

/** Data URLs for the photos that could be read here, in order, and the URLs of the rest. */
export async function inlinePhotos(urls: string[], signal?: AbortSignal): Promise<{ photos: string[]; photo_urls: string[] }> {
  const head = urls.slice(0, MAX_INLINE);
  const got = await Promise.all(head.map((u) => {
    const t = AbortSignal.timeout(6000);
    const s = signal ? AbortSignal.any([signal, t]) : t;
    return toDataUrl(u, s).catch(() => null);
  }));
  const photos: string[] = [];
  const photo_urls: string[] = [];
  head.forEach((u, i) => (got[i] ? photos.push(got[i]!) : photo_urls.push(u)));
  photo_urls.push(...urls.slice(MAX_INLINE));
  return { photos, photo_urls };
}
