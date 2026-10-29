// The judged build (`npm run build`) ships no own-key setting: none of its text, headers or names is anywhere in what
// it builds. The classmates' build (`npm run build:byok`) has every one of them, which keeps the list honest.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, test } from 'node:test';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const tmp = mkdtempSync(join(tmpdir(), 'hush-iq-extension-'));
after(() => rmSync(tmp, { recursive: true, force: true }));

const KEY_UI = [
  'Your own model key', 'API key', 'Save key', 'Test key', 'Remove key', 'is not an API key',
  'X-HushIQ-Key', 'X-HushIQ-Provider', 'X-HushIQ-Model', '/key-check',
  'platform.openai.com', 'platform.claude.com', 'ownKey', 'keyHeaders', 'scrub', 'own key',
];

/** Every text file the build writes, by name. */
function build(name: string, ...args: string[]): Map<string, string> {
  const out = join(tmp, name);
  execFileSync(process.execPath, [join(root, 'scripts/build.mjs'), '--no-zip', '--out', out, ...args], { stdio: 'pipe' });
  return new Map(readdirSync(out).filter((f) => /\.(js|html|css|json)$/.test(f)).map((f) => [f, readFileSync(join(out, f), 'utf8')]));
}

const judged = build('judged');
const classmates = build('byok', '--byok');

test('the judged build holds none of the own-key settings', () => {
  for (const [file, text] of judged) {
    for (const s of KEY_UI) assert.ok(!text.includes(s), `${file} contains "${s}"`);
  }
});

test('the classmates’ build holds every one of them', () => {
  const all = [...classmates.values()].join('\n');
  for (const s of KEY_UI) assert.ok(all.includes(s), `the byok build lacks "${s}"`);
});

test('both builds have the AI reading switch', () => {
  for (const files of [judged, classmates]) {
    assert.match(files.get('options.html')!, /id="ai"/);
    assert.ok(files.get('panel.js')!.includes('X-HushIQ-AI'));
  }
});
