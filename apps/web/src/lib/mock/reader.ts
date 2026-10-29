/**
 * The listing reader's replay, used until `POST /read` is live. It reads the pasted text with fixed rules
 * instead of a model, and keeps the reader's one rule: every field it reads carries the exact line of the
 * listing it came from, and anything it cannot find is "can't tell". It does not see photos; it says so.
 * Then it scores the building with the real engine (lib/score.ts) and streams each step as a turn.
 */
import { getScore } from '../score.ts';
import type { Answers, EvidenceRef, Field, Observed, ReadInput, ReaderResult, ReaderTurn } from '../types.ts';
import { DEFAULT_ANSWERS, addressLine, listWords, pct } from '../words.ts';
import { extract } from './extract.ts';
import { SAMPLES } from './listings.ts';

// ---------------------------------------------------------------- the stream

class Aborted extends Error {
  name = 'AbortError';
}

function wait(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new Aborted());
    const t = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => {
      clearTimeout(t);
      reject(new Aborted());
    }, { once: true });
  });
}

const q = (s: string) => `“${s}”`;
const ev = (f: Field<unknown>): EvidenceRef[] => f.evidence;

export async function mockRead(input: ReadInput, onTurn: (t: ReaderTurn) => void, signal?: AbortSignal): Promise<ReaderResult> {
  const answers: Answers = input.answers ?? DEFAULT_ANSWERS;
  const x = extract(input.text);
  const sample = SAMPLES.find((s) => s.text.trim() === input.text.trim());
  const turns: ReaderTurn[] = [];
  const emit = async (t: Omit<ReaderTurn, 'i'>, delay = 420) => {
    await wait(delay, signal);
    const turn = { ...t, i: turns.length } as ReaderTurn;
    turns.push(turn);
    onTurn(turn);
  };

  const words = input.text.trim().split(/\s+/).filter(Boolean).length;
  const photos = input.photos.length;
  await emit({
    kind: 'read', title: 'Read the listing',
    detail: `${words} words${photos ? `, ${photos} photo${photos > 1 ? 's' : ''}` : ''}. Facts only, each tied to its line.`,
  }, 250);
  for (let i = 0; i < photos; i++) {
    await emit({
      kind: 'look', status: 'cant_tell', title: `Photo ${i + 1}: not read in the replay`,
      detail: 'The live reader looks for windows, AC units, the view and the walls in each photo.',
    }, 300);
  }

  const { address, unit, floor, side } = x.fields;
  await emit(address.status === 'read'
    ? { kind: 'read', title: 'Address', detail: q(address.value!), evidence: ev(address) }
    : { kind: 'read', status: 'cant_tell', title: 'Address: not in the listing' });
  if (unit.status === 'read') await emit({ kind: 'read', title: `Unit ${unit.value}`, detail: q(unit.evidence[0].source === 'text' ? unit.evidence[0].quote : ''), evidence: ev(unit) }, 300);
  await emit(floor.status === 'read'
    ? { kind: 'read', title: `Floor ${floor.value}`, detail: q((floor.evidence[0] as { quote: string }).quote), evidence: ev(floor) }
    : { kind: 'read', status: 'cant_tell', title: 'Floor: can’t tell', detail: 'The listing does not say. The score uses the building’s middle floor and shows the range.' });
  if (x.sideConflict) {
    await emit({ kind: 'read', status: 'cant_tell', title: 'Side: the listing says both', detail: `${q(x.sideConflict[0])} and ${q(x.sideConflict[1])}. Scored as unknown, with the range.` });
  } else {
    await emit(side.status === 'read'
      ? { kind: 'read', title: side.value === 'front' ? 'Side: street' : 'Side: rear', detail: q((side.evidence[0] as { quote: string }).quote), evidence: ev(side) }
      : { kind: 'read', status: 'cant_tell', title: 'Side: can’t tell', detail: 'Nothing says street or rear. The score shows both ends.' });
  }

  if (x.ignored.length) {
    await emit({
      kind: 'note', title: `Ignored ${x.ignored.length} adjective${x.ignored.length > 1 ? 's' : ''}`,
      detail: `${listWords(x.ignored.map(q))}: a listing’s adjectives are not evidence.`,
    });
  }

  const OBS_LABEL: Record<keyof Observed, string> = { view: 'View', windows: 'Windows', ac_units: 'AC units', wall_material: 'Walls' };
  const seen = (Object.keys(OBS_LABEL) as (keyof Observed)[]).filter((k) => x.observed[k].status === 'read');
  for (const k of seen) {
    const f = x.observed[k];
    await emit({ kind: 'read', title: `${OBS_LABEL[k]}: ${f.value}`, detail: q((f.evidence[0] as { quote: string }).quote), evidence: ev(f) }, 320);
  }
  const unseen = (Object.keys(OBS_LABEL) as (keyof Observed)[]).filter((k) => x.observed[k].status !== 'read');
  if (unseen.length) {
    await emit({ kind: 'read', status: 'cant_tell', title: `Can’t tell: ${listWords(unseen.map((k) => OBS_LABEL[k].toLowerCase()))}`, detail: 'Shown, never guessed. These do not feed the score yet.' }, 320);
  }

  if (sample?.id === 'claremont') {
    // The grounding check, as the live reader's submit_listing tool runs it: a field with no quoted line is refused.
    await emit({
      kind: 'check', status: 'refused', title: 'submit_listing refused “side: rear”',
      detail: 'No line of the listing says it. Sent back as can’t tell.',
    }, 650);
  }
  const readCount = [address, unit, floor, side].filter((f) => f.status === 'read').length;
  await emit({
    kind: 'check', title: 'submit_listing accepted',
    detail: `${readCount} of 4 fields read, each with its quoted line; ${4 - readCount} can’t tell.`,
  }, 520);

  const result: ReaderResult = { fields: x.fields, position: x.position, observed: x.observed, score: null, trace: turns };
  if (!x.geocode) {
    await emit({ kind: 'ask', status: 'cant_tell', title: 'Which building is it?', detail: 'The listing has no street address. Type it below to score it.' }, 300);
    return result;
  }

  let score;
  try {
    [score] = await Promise.all([
      getScore(x.geocode, { floor: floor.value, position: x.position }, answers, signal),
      wait(450, signal),
    ]);
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e;
    await emit({ kind: 'geocode', status: 'error', title: 'Could not find that building', detail: (e as Error).message }, 0);
    throw e;
  }
  const facts = score.building_facts;
  const built = facts?.yearbuilt ? `, built ${facts.yearbuilt}` : '';
  const floors = score.unit.building_floors ? `${score.unit.building_floors} floors` : 'height unknown';
  await emit({
    kind: 'geocode', title: 'Found the building',
    detail: `${addressLine(score.address.label, score.address.query)} · ${floors}${built}${score.address.bbl ? ` · BBL ${score.address.bbl}` : ''}`,
  }, 0);
  await emit({
    kind: 'tool', title: `Pulled ${score.sources.length || 8} city datasets`,
    detail: '311 complaints, PLUTO, street centerline, DOB permits, liquor licenses, subway, facilities.',
  }, 380);
  await emit({
    kind: 'score', title: `Ranked against ${score.manhattan.buildings} Manhattan buildings`,
    detail: `${score.verdict}: quieter than ${pct(score.quieter_than)} of Manhattan apartments.`,
  }, 420);
  return { ...result, score };
}
