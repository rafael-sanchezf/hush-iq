/**
 * What the extension reads from the listing the renter has open. Injected into that one tab by
 * `chrome.scripting.executeScript` after a click (activeTab), so it must stand alone: no imports, no outer
 * variables, everything it needs declared inside the function.
 *
 * It reads only what the page shows: the address line, the facts line, the description, the features, and the
 * listing's photo URLs. Light hints for StreetEasy, Zillow, Apartments.com and Craigslist say where those live;
 * any other page falls back to its largest block of readable text. The renter sees and trims the result before
 * anything is sent.
 */
import type { Capture } from './lib/capture-types.ts';

export function captureListing(maxChars: number, maxPhotos: number): Capture {
  type Site = Capture['site'];
  const host = location.hostname.replace(/^www\./, '');
  const site: Site = /(^|\.)streeteasy\.com$/.test(host) ? 'streeteasy'
    : /(^|\.)zillow\.com$/.test(host) ? 'zillow'
    : /(^|\.)apartments\.com$/.test(host) ? 'apartments'
    : /(^|\.)craigslist\.org$/.test(host) ? 'craigslist'
    : 'other';

  // ------------------------------------------------------------ text helpers
  const NOISE = 'script,style,noscript,template,svg,iframe,nav,footer,header,aside,form,button,[role=navigation],[role=banner],[role=contentinfo],[aria-hidden=true],[hidden]';
  const visible = (el: Element): boolean => {
    const r = (el as HTMLElement).getBoundingClientRect?.();
    if (!r || (r.width === 0 && r.height === 0)) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== 'hidden' && cs.display !== 'none';
  };
  const textOf = (el: Element | null): string => {
    if (!el) return '';
    const t = (el as HTMLElement).innerText ?? el.textContent ?? '';
    return t.replace(/ /g, ' ').replace(/[ \t]+/g, ' ').replace(/ *\n */g, '\n').replace(/\n{3,}/g, '\n\n').trim();
  };
  const first = (selectors: string[]): Element | null => {
    for (const s of selectors) {
      for (const el of document.querySelectorAll(s)) if (visible(el) && textOf(el)) return el;
    }
    return null;
  };
  const all = (selectors: string[]): Element[] => {
    const out: Element[] = [];
    for (const s of selectors) for (const el of document.querySelectorAll(s)) if (visible(el) && textOf(el) && !out.some((o) => o.contains(el) || el.contains(o))) out.push(el);
    return out;
  };
  // Buttons and links that only steer the page ("Show more", "Contact agent") are not listing text.
  const CHROME_LINE = /^(show (more|less|full description)|read (more|less)|see (more|less|all.*)|view (more|all.*)|contact( agent| owner| property)?|request (a )?tour|message|save|share|hide|report|apply now|check availability|email|call|back to (top|search)|next|previous|\d+ ?\/ ?\d+|·)$/i;
  const clean = (t: string): string => t.split('\n').map((l) => l.trim()).filter((l) => l && !CHROME_LINE.test(l)).join('\n');

  // ------------------------------------------------------------ structured data the page publishes
  type Obj = Record<string, unknown>;
  const ld: Obj[] = [];
  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const walk = (x: unknown) => {
        if (Array.isArray(x)) x.forEach(walk);
        else if (x && typeof x === 'object') {
          ld.push(x as Obj);
          const g = (x as Obj)['@graph'];
          if (g) walk(g);
          for (const k of ['mainEntity', 'itemOffered', 'containsPlace', 'about']) if ((x as Obj)[k]) walk((x as Obj)[k]);
        }
      };
      walk(JSON.parse(s.textContent || 'null'));
    } catch {
      /* a page's broken JSON-LD is not our problem */
    }
  }
  let postal: Capture['postal'] = null;
  for (const o of ld) {
    const a = o.address as Obj | string | undefined;
    if (a && typeof a === 'object' && (a.streetAddress || a.postalCode)) {
      postal = {
        street: String(a.streetAddress ?? '') || null,
        locality: String(a.addressLocality ?? '') || null,
        region: String(a.addressRegion ?? '') || null,
        postal_code: String(a.postalCode ?? '') || null,
      };
      break;
    }
  }
  const meta = (p: string) => document.querySelector(`meta[property="${p}"],meta[name="${p}"]`)?.getAttribute('content')?.trim() || '';

  // ------------------------------------------------------------ site hints
  interface Hint { title: string[]; address: string[]; facts: string[]; body: string[]; photos: string[] }
  const HINTS: Record<Site, Hint | null> = {
    streeteasy: {
      title: ['[data-testid="homeAddress"]', 'h1'],
      address: ['[data-testid="address"]', '[data-testid="homeAddress"]', 'h1'],
      facts: ['[data-testid="priceInfo"]', '[data-testid="propertyDetails"]', '[data-testid="buildingSummaryList"]', '[data-testid^="rentalListingSpec"]'],
      body: ['[data-testid="about-section"]', '[data-testid="home-features-section"]', '[data-testid="building-amenities-section"]', '[data-testid="about-building-section"]', '[data-testid="description"]'],
      photos: ['[data-testid="slide-image"]', '[data-testid*="carousel"] img', '[class*="Carousel"] img', '[class*="Gallery"] img'],
    },
    zillow: {
      title: ['h1'],
      address: ['[data-testid="home-details-summary"] h1', '[data-testid="address"]', 'h1'],
      facts: ['[data-testid="price"]', '[data-testid="bed-bath-sqft-facts"]', '[data-testid="bed-bath-beyond"]', '[data-testid="home-details-summary"]'],
      body: ['[data-testid="description"]', '[class*="Description"]', '[data-testid="facts-and-features"]', '[data-testid="category-group"]', '[class*="FactsAndFeatures"]', '[data-testid="building-amenities"]'],
      photos: ['[data-testid*="media"] img', '[data-testid*="hollywood"] img', '[class*="media-stream"] img', 'picture img'],
    },
    apartments: {
      title: ['#propertyName', 'h1'],
      address: ['.propertyAddressContainer', '#propertyAddressRow', '.propertyAddress', 'h1 + div'],
      facts: ['#priceBedBathAreaInfoWrapper', '.priceBedRangeInfo', '#pricingView .pricingGridItem'],
      body: ['#descriptionSection', '.descriptionSection', '#amenitiesSection', '.amenitiesSection', '#feesSection'],
      photos: ['#carouselSection img', '.aspectRatioImage img', '.carouselContent img', '#photoGallery img'],
    },
    craigslist: {
      title: ['#titletextonly', '.postingtitletext', 'h1'],
      address: ['.mapaddress', '.postingtitletext small'],
      facts: ['.attrgroup', '.mapAndAttrs .attrgroup', '.price'],
      body: ['#postingbody'],
      photos: ['#thumbs a', '.gallery .swipe img', '.slide img', '.gallery img', 'figure img'],
    },
    other: null,
    paste: null,
  };

  const parts: string[] = [];
  const add = (t: string) => {
    const c = clean(t);
    if (c && !parts.some((p) => p.includes(c))) parts.push(c);
  };
  const hint = HINTS[site];
  if (hint) {
    const title = first(hint.title);
    add(textOf(title));
    const addr = first(hint.address);
    if (addr && addr !== title) add(textOf(addr));
    for (const el of all(hint.facts)) add(textOf(el));
    for (const el of all(hint.body)) add(textOf(el));
  }
  // The structured address goes in only when the visible text has no street line, and it says where it is from.
  if (postal?.street && !parts.join('\n').includes(postal.street)) {
    add(`Address on the page: ${[postal.street, postal.locality, [postal.region, postal.postal_code].filter(Boolean).join(' ')].filter(Boolean).join(', ')}`);
  }

  // Any page, and any hinted page whose layout changed: the largest block of readable text.
  if (parts.join('\n').length < 280) {
    const root = document.querySelector('main, [role=main], article') ?? document.body;
    const clone = root.cloneNode(true) as Element;
    clone.querySelectorAll(NOISE).forEach((n) => n.remove());
    let best: Element = root;
    let bestScore = 0;
    for (const el of root.querySelectorAll('article, section, main, div')) {
      if (!visible(el) || el.closest(NOISE)) continue;
      const t = textOf(el);
      if (t.length < 200) continue;
      const paras = el.querySelectorAll('p, li').length;
      const links = [...el.querySelectorAll('a')].reduce((n, a) => n + textOf(a).length, 0);
      const score = (t.length - 2 * links) * (1 + Math.min(paras, 30) / 10) / Math.sqrt(1 + el.querySelectorAll('div').length / 40);
      if (score > bestScore) {
        bestScore = score;
        best = el;
      }
    }
    if (!parts.length) add(textOf(document.querySelector('h1')) || document.title);
    add(textOf(best === root ? clone : best));
  }
  let text = parts.join('\n\n').trim();
  if (!text) text = clean(meta('og:description') || meta('description'));
  if (text.length > maxChars) text = text.slice(0, maxChars).replace(/\s+\S*$/, '') + '\n…';

  // ------------------------------------------------------------ photos
  const urls: string[] = [];
  const seen = new Set<string>();
  const SKIP = /(logo|icon|sprite|avatar|agent|headshot|broker|badge|maps\.google|staticmap|mapbox|tile|placeholder|blank|pixel|tracking|\.svg)/i;
  const keyOf = (u: string) =>
    u.replace(/[?#].*$/, '')
      .replace(/(photos\.zillowstatic\.com\/fp\/[0-9a-f]+)-.*$/, '$1')
      .replace(/(images\.craigslist\.org\/[\w]+?)_\d+x\d+c?\.(jpg|webp)$/, '$1');
  const push = (raw: string | null | undefined) => {
    if (!raw || urls.length >= maxPhotos) return;
    let u: string;
    try {
      u = new URL(raw.trim().split(/\s+/)[0], location.href).href;
    } catch {
      return;
    }
    if (!/^https?:/.test(u) || SKIP.test(u)) return;
    if (site === 'craigslist') u = u.replace(/_\d+x\d+c?\.(jpg|webp)$/, '_600x450.$1');
    const k = keyOf(u);
    if (seen.has(k)) return;
    seen.add(k);
    urls.push(u);
  };
  const largest = (img: HTMLImageElement): string => {
    const set = img.getAttribute('srcset') || img.getAttribute('data-srcset') || (img.parentElement?.tagName === 'PICTURE' ? img.parentElement.querySelector('source')?.getAttribute('srcset') : '') || '';
    const best = set.split(',').map((s) => s.trim().split(/\s+/)).filter((p) => p[0])
      .sort((a, b) => parseFloat(b[1] || '0') - parseFloat(a[1] || '0'))[0]?.[0];
    return best || img.currentSrc || img.src || img.getAttribute('data-src') || img.getAttribute('data-lazy-src') || '';
  };
  if (hint) {
    for (const s of hint.photos) {
      for (const el of document.querySelectorAll(s)) {
        const img = el instanceof HTMLImageElement ? el : el.querySelector('img');
        if (el instanceof HTMLAnchorElement) push(el.href);
        else if (img && !(img.naturalWidth && img.naturalWidth < 200)) push(largest(img));
      }
    }
  }
  for (const o of ld) {
    const im = o.image ?? o.photo;
    for (const x of Array.isArray(im) ? im : [im]) push(typeof x === 'string' ? x : (x as Obj | undefined)?.url as string | undefined ?? (x as Obj | undefined)?.contentUrl as string | undefined);
  }
  push(meta('og:image'));
  if (urls.length < 3) {
    for (const img of document.images) {
      const w = img.naturalWidth || img.width;
      const h = img.naturalHeight || img.height;
      if (w >= 320 && h >= 200 && visible(img)) push(largest(img));
    }
  }

  return {
    url: location.href,
    host,
    site,
    title: textOf(document.querySelector('h1')) || document.title,
    text,
    photos: urls,
    postal,
    selection: false,
    captured_at: new Date().toISOString(),
  };
}

/** The renter's selection, with its line breaks (the context menu's `selectionText` collapses them). */
export function captureSelection(): string {
  return String(getSelection() ?? '').trim();
}
