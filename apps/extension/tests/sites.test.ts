/** The sites the icon and panel live on, and what counts as the same listing page. */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { SITE_PATTERNS, samePage, supported } from '../src/lib/sites.ts';

test('the four listing sites and their subdomains are supported, nothing else', () => {
  for (const u of ['https://streeteasy.com/building/x/4f', 'https://www.zillow.com/homedetails/1', 'https://www.apartments.com/a-b-ny/xyz/',
    'https://newyork.craigslist.org/mnh/apa/d/x/1.html']) assert.ok(supported(u), u);
  for (const u of [undefined, '', 'chrome://extensions', 'https://example.com/', 'https://streeteasy.com.evil.io/', 'http://streeteasy.com/',
    'https://notzillow.com/']) assert.ok(!supported(u), String(u));
});

test('the same page ignores query and hash, not the path', () => {
  assert.ok(samePage('https://streeteasy.com/rental/1?photo=3', 'https://streeteasy.com/rental/1/#map'));
  assert.ok(!samePage('https://streeteasy.com/rental/1', 'https://streeteasy.com/rental/2'));
  assert.ok(!samePage('', 'https://streeteasy.com/rental/2'));
});

test('match patterns cover each host', () => {
  assert.deepEqual(SITE_PATTERNS, ['https://*.streeteasy.com/*', 'https://*.zillow.com/*', 'https://*.apartments.com/*', 'https://*.craigslist.org/*']);
});
