/**
 * The verdict writer's template, used until `POST /verdict` is live (the live service falls back to its own
 * template the same way). It builds the evidence lines from the score and the listing, then writes each
 * sentence from those lines alone, citing them by id: the same contract the model is held to.
 */
import type { EvidenceLine, RangeCase, Score, Sentence, Source, Verdict, VerdictInput } from '../types.ts';
import { SOURCE_WORDS, addressLine, forWhom, listWords, ordinal, pct, sideWords, sleepLabel } from '../words.ts';

export function evidenceFor({ score, answers, fields }: VerdictInput): { lines: EvidenceLine[]; ids: Record<string, string> } {
  const lines: EvidenceLine[] = [];
  const ids: Record<string, string> = {};
  const add = (key: string, text: string) => {
    const id = `E${lines.length + 1}`;
    lines.push({ id, text });
    ids[key] = id;
  };
  add('verdict', `${addressLine(score.address.label, score.address.query)}: ${score.verdict}, quieter than ${pct(score.quieter_than)} of Manhattan apartments, for sleep from ${sleepLabel(answers)}.`);
  const byRank = [...score.ingredients].sort((x, y) => x.quieter_than - y.quieter_than);
  for (const i of byRank) {
    add(`rank:${i.name}`, `${SOURCE_WORDS[i.name].title}: quieter than ${pct(i.quieter_than)} of Manhattan apartments; weight ${Math.round(i.weight)}%${i.ticked ? ', ticked by the renter' : ''}.`);
    if (i.evidence[0]) add(`fact:${i.name}`, `${SOURCE_WORDS[i.name].title}: ${i.evidence[0]}.`);
  }
  for (const c of score.caps) {
    add(`cap:${c.source}:${c.cap}`, `${SOURCE_WORDS[c.source].title} ${c.applied ? 'caps the verdict' : 'would cap the verdict'} at ${c.cap}: ${c.why}.`);
  }
  if (score.range) {
    const { loudest_case: l, quietest_case: q } = score.range;
    add('range', `Listing silent on ${[score.unit.floor_from !== 'listing' && 'floor', score.unit.side_from !== 'listing' && 'side'].filter(Boolean).join(' and ')}: ${l.verdict} at ${l.floor ? `floor ${l.floor}, ` : ''}${sideWords(l.side)}; ${q.verdict} at ${q.floor ? `floor ${q.floor}, ` : ''}${sideWords(q.side)}.`);
  }
  const fq = fields.floor.evidence[0];
  if (fields.floor.status === 'read' && fq?.source === 'text') add('floor', `Floor ${fields.floor.value}, from the listing: “${fq.quote}”.`);
  const sq = fields.side.evidence[0];
  if (fields.side.status === 'read' && sq?.source === 'text') add('side', `${fields.side.value === 'front' ? 'Street side' : 'Rear'}, from the listing: “${sq.quote}”.`);
  return { lines, ids };
}

function loudestSentence(score: Score, ids: Record<string, string>): Sentence | null {
  const worst = [...score.ingredients].sort((x, y) => x.quieter_than - y.quieter_than)[0];
  if (!worst) return null;
  const name = SOURCE_WORDS[worst.name].title.toLowerCase();
  const cites = [ids[`rank:${worst.name}`], ids[`fact:${worst.name}`]].filter(Boolean);
  if (worst.quieter_than >= 60) {
    return { text: `Nothing here stands out: even the loudest source, ${name}, is quieter than ${pct(worst.quieter_than)} of Manhattan apartments.`, cites };
  }
  return { text: `What you will hear most is ${name}, quieter than only ${pct(worst.quieter_than)} of Manhattan apartments.`, cites };
}

export function templateVerdict(input: VerdictInput): Verdict {
  const { score, answers } = input;
  const { lines, ids } = evidenceFor(input);
  const sentences: Sentence[] = [];
  const where = score.unit.floor_from === 'listing' && score.unit.floor
    ? ` on the ${ordinal(score.unit.floor)} floor`
    : score.unit.floor ? `, taken at the building's middle floor,` : '';
  sentences.push({
    text: `${forWhom(answers).replace(/\.$/, '')}, this apartment${where} reads ${score.verdict}: quieter than ${pct(score.quieter_than)} of Manhattan apartments.`,
    cites: [ids.verdict, ids.floor].filter(Boolean),
  });
  const loud = loudestSentence(score, ids);
  if (loud) sentences.push(loud);

  const ticked = score.ingredients.filter((i) => i.ticked);
  if (ticked.length) {
    sentences.push({
      text: `You said ${listWords(ticked.map((i) => SOURCE_WORDS[i.name].short))} ${ticked.length > 1 ? 'bother' : 'bothers'} you, so ${ticked.length > 1 ? 'they count' : 'it counts'} three times as much: ${ticked
        .map((i, k) => (k === 0 ? `${SOURCE_WORDS[i.name].short} is quieter than ${pct(i.quieter_than)} of Manhattan apartments` : `${SOURCE_WORDS[i.name].short} than ${pct(i.quieter_than)}`))
        .join(', ')}.`,
      cites: ticked.map((i) => ids[`rank:${i.name}`]),
    });
  }

  const applied = score.caps.filter((c) => c.applied);
  const warned = score.caps.filter((c) => !c.applied);
  if (applied.length) {
    const c = applied[0];
    sentences.push({
      text: `${SOURCE_WORDS[c.source].title} holds the verdict at ${c.cap}: it is ${c.why.replace(/^you said it bothers you, and it is /, '')}, which a good average elsewhere cannot outvote.`,
      cites: [ids[`cap:${c.source}:${c.cap}`]],
    });
  } else if (warned.length) {
    const srcs = [...new Set(warned.map((c) => c.source))] as Source[];
    const names = listWords(srcs.map((n) => SOURCE_WORDS[n].title.toLowerCase()));
    sentences.push({
      text: srcs.length > 1
        ? `${["", "One", "Two", "Three", "Four", "Five"][srcs.length]} sources sit among Manhattan's loudest, ${names}; either one alone would keep the verdict from reading better than ${warned[0].cap}.`
        : `${SOURCE_WORDS[srcs[0]].title} sits among Manhattan's loudest, so the verdict could not read better than ${warned[0].cap} whatever the rest.`,
      cites: warned.map((c) => ids[`cap:${c.source}:${c.cap}`]),
    });
  }

  if (score.range) {
    const { loudest_case: l, quietest_case: q } = score.range;
    const at = (c: RangeCase) =>
      [l.floor !== q.floor && c.floor ? `on floor ${c.floor}` : '', l.side !== q.side ? (c.side === 'front' ? 'on the street side' : 'at the rear') : '']
        .filter(Boolean)
        .join(' ');
    sentences.push({
      text: l.verdict === q.verdict
        ? `The listing leaves the unit open, but it reads ${l.verdict} wherever it sits.`
        : `The listing leaves the unit open: it would read ${l.verdict} ${at(l)} and ${q.verdict} ${at(q)}.`,
      cites: [ids.range],
    });
  } else if (ids.side) {
    sentences.push({ text: `The listing places it on the ${input.fields.side.value === 'front' ? 'street side' : 'rear'}, and the score uses that.`, cites: [ids.side] });
  }

  return { evidence: lines, sentences: sentences.map((s) => ({ ...s, cites: s.cites.filter(Boolean) })), writer: 'template' };
}
