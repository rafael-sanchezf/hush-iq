/**
 * Which services the demo talks to, fixed at build time (a static export has no server to read them later).
 *
 * - `NEXT_PUBLIC_READER_URL`  set: the live listing reader (`POST /read`); unset: the replay in lib/mock.
 * - `NEXT_PUBLIC_VERDICT_URL` set: the live verdict writer (`POST /verdict`); unset: the template writer.
 * - `NEXT_PUBLIC_SCORE_URL`   the score API, default the hosted one. `/v2/score` when it answers; until then
 *   engine v2's ranking is replayed in the browser on `/v1/score`'s ingredients (lib/replay/v2.ts).
 * - `NEXT_PUBLIC_HUSH_MOCK=1` forces the replay for the reader and the verdict even when their URLs are set.
 */
const trim = (s: string | undefined) => (s ?? '').trim().replace(/\/+$/, '');

const forceMock = process.env.NEXT_PUBLIC_HUSH_MOCK === '1';

export const ENV = {
  readerUrl: forceMock ? '' : trim(process.env.NEXT_PUBLIC_READER_URL),
  verdictUrl: forceMock ? '' : trim(process.env.NEXT_PUBLIC_VERDICT_URL),
  scoreUrl: trim(process.env.NEXT_PUBLIC_SCORE_URL) || 'https://hush-iq-api.vercel.app',
};

export const REPO_URL = 'https://github.com/rafael-sanchezf/hush-iq';
