/**
 * Photos are sent to the reader as JPEG data URLs, downscaled in the browser so a phone upload stays small: eight
 * at 1024 px come to about 2.5 MB, under the host's 4.5 MB request cap (HIQ-143).
 */
export const MAX_PHOTOS = 8;
const LONG_SIDE = 1024;

export async function toDataUrl(file: File): Promise<string> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, LONG_SIDE / Math.max(bitmap.width, bitmap.height));
  const w = Math.round(bitmap.width * scale);
  const h = Math.round(bitmap.height * scale);
  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  canvas.getContext('2d')!.drawImage(bitmap, 0, 0, w, h);
  bitmap.close();
  return canvas.toDataURL('image/jpeg', 0.82);
}
