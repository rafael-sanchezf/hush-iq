/**
 * A listing often ends with the agent's phone and email. The reader needs neither, so they are blanked before
 * the renter sees the text, and never sent. Shown as "[phone]" and "[email]" so the renter can tell.
 */
const EMAIL = /\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b/g;
// US numbers: (646) 335-8383, 646-335-8383, 646.335.8383, +1 646 335 8383. Not prices, not years, not ZIPs.
const PHONE = /(?<![\w$])(?:\+?1[\s.-]?)?\(?\b[2-9]\d{2}\)?[\s.-]\d{3}[\s.-]\d{4}\b/g;

export function redactContacts(text: string): { text: string; count: number } {
  let count = 0;
  const out = text
    .replace(EMAIL, () => (count++, '[email]'))
    .replace(PHONE, () => (count++, '[phone]'));
  return { text: out, count };
}
