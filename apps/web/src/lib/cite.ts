import type { Verdict } from './types.ts';

/**
 * The site's own check on a verdict, live or template: a sentence may cite only evidence lines it was sent.
 * Unknown ids are dropped from the sentence and counted, so the page never links to a line that does not exist.
 */
export function checkCitations(v: Verdict): { verdict: Verdict; dropped: number } {
  const known = new Set(v.evidence.map((e) => e.id));
  let dropped = 0;
  const sentences = v.sentences.map((s) => {
    const cites = s.cites.filter((c) => known.has(c));
    dropped += s.cites.length - cites.length;
    return { ...s, cites };
  });
  return { verdict: { ...v, sentences }, dropped };
}
