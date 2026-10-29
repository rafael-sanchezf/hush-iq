import type { Score, VerdictWord } from '@/lib/types';
import { VERDICTS } from '@/lib/types';

/**
 * Five steps, Very loud to Very quiet, one fifth of Manhattan each. The step that applies is the page's one
 * accent. When the listing is silent on the floor or the side, a bracket under the steps spans the range from
 * its loudest case to its quietest.
 */
export function VerdictMeter({ verdict, range }: { verdict: VerdictWord; range?: Score['range'] }) {
  const on = VERDICTS.indexOf(verdict);
  let bracket: { left: string; width: string } | null = null;
  if (range) {
    const a = VERDICTS.indexOf(range.loudest_case.verdict);
    const b = VERDICTS.indexOf(range.quietest_case.verdict);
    const lo = Math.min(a, b);
    const hi = Math.max(a, b);
    if (hi > lo) bracket = { left: `calc(${lo} * (100% + 6px) / 5)`, width: `calc(${hi - lo + 1} * (100% + 6px) / 5 - 6px)` };
  }
  return (
    <div className="meter" aria-hidden="true">
      <div className="meter-steps">
        {VERDICTS.map((v, i) => (
          <span key={v} className={i === on ? 'on' : undefined} />
        ))}
      </div>
      {bracket ? (
        <div className="meter-range">
          <i style={bracket} />
        </div>
      ) : null}
      <div className="meter-ends">
        <span>Very loud</span>
        <span>Very quiet</span>
      </div>
    </div>
  );
}
