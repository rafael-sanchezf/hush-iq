import { fileURLToPath } from 'node:url';

/**
 * A static export: `next build` writes plain HTML, CSS and JS to `out/`. The demo talks to the
 * reader, verdict and score services from the browser, so the site itself needs no server.
 *
 * `trailingSlash` emits `method/index.html` rather than `method.html`, so the export serves from any
 * static host without rewrites. `turbopack.root` pins this folder: a worktree under
 * `.claude/worktrees/` sits inside the main checkout, whose own files would otherwise be picked up.
 *
 * @type {import('next').NextConfig}
 */
const nextConfig = {
  output: 'export',
  trailingSlash: true,
  agentRules: false,
  images: { unoptimized: true },
  turbopack: {
    root: fileURLToPath(new URL('.', import.meta.url)),
  },
};

export default nextConfig;
