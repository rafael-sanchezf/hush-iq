/** What the extension read from the renter's open tab, or from their selection or paste. */
export interface Capture {
  url: string;
  host: string;
  site: 'streeteasy' | 'zillow' | 'apartments' | 'craigslist' | 'other' | 'paste';
  title: string;
  /** The listing text as read, which the renter can trim before it is sent. */
  text: string;
  /** Absolute URLs of the listing's photos, in page order. */
  photos: string[];
  /** The address the page publishes as structured data (schema.org PostalAddress), when it has one. */
  postal: { street: string | null; locality: string | null; region: string | null; postal_code: string | null } | null;
  selection: boolean;
  captured_at: string;
}

/** What the service worker hands the panel: a capture, or why there is none. */
export type CaptureMessage =
  | { id: string; ok: true; capture: Capture }
  | { id: string; ok: false; error: string; url?: string };

export const SITE_NAMES: Record<Capture['site'], string> = {
  streeteasy: 'StreetEasy',
  zillow: 'Zillow',
  apartments: 'Apartments.com',
  craigslist: 'Craigslist',
  other: 'this page',
  paste: 'your paste',
};

/** The reader takes up to 20,000 characters (services/agent/CONTRACT.md); a listing needs far fewer. */
export const MAX_CHARS = 12000;
export const MAX_PHOTOS = 12;
