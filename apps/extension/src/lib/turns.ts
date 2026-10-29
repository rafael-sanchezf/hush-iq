/** The reader's turns in the panel's words, whichever shape they arrive in. */
import type { ReaderResult, ReaderTurn, TurnKind } from './types.ts';
import { observedLabel, sideLabel } from './words.ts';

const KINDS: TurnKind[] = ['read', 'look', 'tool', 'check', 'ask', 'geocode', 'score', 'note'];

type Raw = Record<string, unknown>;
const asObj = (x: unknown): Raw => (x && typeof x === 'object' ? (x as Raw) : {});
const num = (x: unknown) => (typeof x === 'number' ? x : undefined);

/**
 * A turn from the live reader (services/agent/CONTRACT.md: `{n, by, tool, args, result, ok, ms, said}`) in the
 * panel's words. A turn already in the panel's shape (`title`) passes through.
 */
export function normalizeTurn(raw: Raw, i: number): ReaderTurn {
  if (typeof raw.title === 'string') {
    const kind = KINDS.includes(raw.kind as TurnKind) ? (raw.kind as TurnKind) : 'note';
    return { ...(raw as unknown as ReaderTurn), i: num(raw.i) ?? i, kind };
  }
  const tool = (raw.tool as string | null) ?? null;
  const result = asObj(raw.result);
  const args = asObj(raw.args);
  const ok = raw.ok !== false;
  const base = { i: num(raw.n) ?? i, by: raw.by as ReaderTurn['by'], tool, ms: num(raw.ms) };
  const err = typeof result.error === 'string' ? result.error : undefined;
  switch (tool) {
    case 'read_photo': {
      const idx = Array.isArray(args.indexes) ? (args.indexes as number[]).map((n) => n + 1) : [];
      return { ...base, kind: 'look', status: ok ? 'ok' : 'refused', title: `Looked at photo${idx.length > 1 ? 's' : ''} ${idx.join(', ')}`, detail: err };
    }
    case 'submit_listing': {
      const refused = asObj(result.refused);
      const accepted = Array.isArray(result.accepted) ? (result.accepted as string[]) : [];
      if (!ok || Object.keys(refused).length) {
        const why = Object.entries(refused).map(([f, w]) => `${f}: ${w}`).join('; ');
        return { ...base, kind: 'check', status: 'refused', title: `submit_listing refused ${Object.keys(refused).join(', ') || 'the draft'}`, detail: why || err };
      }
      return { ...base, kind: 'check', title: 'submit_listing accepted', detail: accepted.length ? `Checked: ${accepted.join(', ')}.` : undefined };
    }
    case 'locate': {
      const label = (result.label as string) ?? (asObj(result.location).label as string | undefined);
      return { ...base, kind: 'geocode', status: ok ? 'ok' : 'error', title: ok ? 'Found the building' : 'Could not place the address', detail: ok ? label : err };
    }
    case 'score': {
      const q = num(result.quieter_than);
      return {
        ...base, kind: 'score', status: ok ? 'ok' : 'error', title: ok ? `Scored with engine ${result.engine ?? 'v2'}` : 'Scoring failed',
        detail: ok && result.verdict ? `${result.verdict}${q !== undefined ? `: quieter than ${Math.round(q)}% of Manhattan apartments` : ''}.` : err,
      };
    }
    case null:
      return { ...base, kind: 'note', title: 'The model answered in text', detail: typeof raw.said === 'string' ? raw.said : undefined };
    default:
      return { ...base, kind: 'tool', status: ok ? 'ok' : 'error', title: String(tool), detail: err };
  }
}

/** One turn per listing field in a live result, so the panel shows what was read and what could not be told. */
export function fieldTurns(r: ReaderResult, from: number): ReaderTurn[] {
  const out: ReaderTurn[] = [];
  const quote = (e: ReaderResult['fields']['floor']['evidence'][number] | undefined) =>
    !e ? undefined : e.source === 'text' ? `“${e.quote}”` : `Photo ${Number(e.source.split(':')[1]) + 1}: ${e.what}`;
  const f = r.fields;
  const rows: [string, string | null, typeof f.floor.evidence, boolean][] = [
    ['Address', f.address.status === 'read' ? String(f.address.value) : null, f.address.evidence, true],
    ['Unit', f.unit.status === 'read' ? String(f.unit.value) : null, f.unit.evidence, false],
    ['Floor', f.floor.status === 'read' ? String(f.floor.value) : null, f.floor.evidence, true],
    ['Side', f.side.status === 'read' ? sideLabel(f.side.value).toLowerCase() : null, f.side.evidence, true],
  ];
  for (const [k, v, ev, always] of rows) {
    if (v === null && !always) continue;
    out.push(v === null
      ? { i: from + out.length, kind: 'read', tool: 'result', status: 'cant_tell', title: `${k}: can’t tell` }
      : { i: from + out.length, kind: 'read', tool: 'result', title: `${k} ${v}`, detail: quote(ev[0]), evidence: ev });
  }
  for (const [k, label] of [['view', 'View'], ['windows', 'Windows'], ['ac_units', 'AC units'], ['wall_material', 'Walls']] as const) {
    const o = r.observed?.[k];
    if (o?.status === 'read') {
      out.push({ i: from + out.length, kind: 'look', tool: 'result', title: `${label}: ${observedLabel(k, o.value).toLowerCase()}`, detail: quote(o.evidence[0]) });
    }
  }
  return out;
}
