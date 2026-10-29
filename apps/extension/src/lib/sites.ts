/**
 * The listing sites the extension works on. Its icon is live and its panel opens only on these; anywhere else the
 * icon greys out and an open panel closes, and it comes back when the renter returns to the listing's tab
 * (Rafa, 2026-10-29). A host covers its subdomains (newyork.craigslist.org).
 */
export const SITE_HOSTS = ['streeteasy.com', 'zillow.com', 'apartments.com', 'craigslist.org'] as const;

/** Match patterns for the manifest's host permissions and the right-click menu; `*.` also matches the bare host. */
export const SITE_PATTERNS = SITE_HOSTS.map((h) => `https://*.${h}/*`);

export function supported(url: string | undefined): boolean {
  if (!url) return false;
  try {
    const u = new URL(url);
    return u.protocol === 'https:' && SITE_HOSTS.some((h) => u.hostname === h || u.hostname.endsWith(`.${h}`));
  } catch {
    return false;
  }
}

/** The same listing page: host and path. Query and hash are left out, since galleries and map moves change them. */
export function samePage(a: string | undefined, b: string | undefined): boolean {
  try {
    const x = new URL(a ?? '');
    const y = new URL(b ?? '');
    return x.hostname === y.hostname && x.pathname.replace(/\/+$/, '') === y.pathname.replace(/\/+$/, '');
  } catch {
    return false;
  }
}
