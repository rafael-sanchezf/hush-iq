// Builds the extension into dist/hush-iq-extension/ and zips it to dist/hush-iq-extension.zip.
//
//   node scripts/build.mjs                         the judged build: the hosted API, no own-key settings at all
//   node scripts/build.mjs --byok                  the classmates' build: own-key settings in, to dist/hush-iq-extension-byok/
//   node scripts/build.mjs --api https://x.y.z     another Hush IQ API: its origin becomes the one host permission
//   node scripts/build.mjs --copy-to <dir>         also leave a copy of the zip in <dir>
//   node scripts/build.mjs --no-zip                the unpacked folder only, for Load unpacked while developing
//   node scripts/build.mjs --out <dir>             build into <dir> instead (the tests do)
//
// __BYOK__ is the one switch between the two builds. Every own-key line sits behind `if (__BYOK__)`; esbuild drops
// those branches and every module only they reach, so the judged bundle holds no key setting, header, text or name.
//
// The zip is for sharing by hand. Nothing here uploads or publishes it.
import { execFileSync } from 'node:child_process';
import { cpSync, mkdirSync, readFileSync, rmSync, writeFileSync, copyFileSync, existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
const opt = (name) => {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : undefined;
};

const api = (opt('--api') ?? 'https://hush-iq-api.vercel.app').replace(/\/+$/, '');
const origin = new URL(api).origin;
const byok = args.includes('--byok');
const name = byok ? 'hush-iq-extension-byok' : 'hush-iq-extension';
const out = resolve(opt('--out') ?? join(root, 'dist', name));
const zip = `${out}.zip`;

rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });

await build({
  entryPoints: {
    background: join(root, 'src/background.ts'),
    panel: join(root, 'src/panel/panel.ts'),
    options: join(root, 'src/options/options.ts'),
  },
  outdir: out,
  bundle: true,
  format: 'esm',
  target: 'chrome116',
  // Readable output: the Web Store reviews the code it ships, and it is small. Names and line breaks stay; the
  // syntax pass only folds constants and drops dead branches, which is what takes the own-key code out.
  minifySyntax: true,
  legalComments: 'none',
  define: { __API_BASE__: JSON.stringify(api), __BYOK__: String(byok) },
  logLevel: 'warning',
});

for (const f of ['src/panel/panel.html', 'src/panel/panel.css', 'src/options/options.html']) {
  copyFileSync(join(root, f), join(out, f.split('/').pop()));
}
cpSync(join(root, 'icons'), join(out, 'icons'), { recursive: true });

const pkg = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
const manifest = JSON.parse(readFileSync(join(root, 'manifest.json'), 'utf8'));
manifest.version = pkg.version;
if (byok) manifest.version_name = `${pkg.version} own key`;
// The listing sites stay (lib/sites.ts); the API entry becomes the one this build calls.
manifest.host_permissions = [...manifest.host_permissions.filter((p) => !p.startsWith('https://hush-iq-api.')), `${origin}/*`];
writeFileSync(join(out, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n');

console.log(`built ${out} (API ${api}${byok ? ', own-key settings in' : ''})`);

if (!args.includes('--no-zip')) {
  rmSync(zip, { force: true });
  // -X leaves out macOS extra attributes; -D leaves out directory entries. The manifest sits at the zip's root.
  execFileSync('zip', ['-q', '-r', '-X', '-D', zip, '.'], { cwd: out });
  console.log(`zipped ${zip}`);
  const copyTo = opt('--copy-to');
  if (copyTo) {
    if (!existsSync(copyTo)) mkdirSync(copyTo, { recursive: true });
    copyFileSync(zip, join(copyTo, `${name}.zip`));
    console.log(`copied to ${join(copyTo, `${name}.zip`)}`);
  }
}
