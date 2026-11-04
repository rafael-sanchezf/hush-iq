'use client';

import { useState } from 'react';

import { LANES, STATUS_WORDS, type Status } from '@/content/factors';

const ORDER: Status[] = ['live', 'v2', 'next', 'partial', 'tbd', 'removed'];
const BAR: Record<Status, string> = {
  live: 'var(--ink)',
  v2: 'var(--ink-2)',
  next: 'var(--ink-3)',
  partial: 'var(--warn)',
  tbd: 'var(--track)',
  removed: 'var(--line)',
};

function counts(statuses: Status[]): Record<Status, number> {
  const c = Object.fromEntries(ORDER.map((k) => [k, 0])) as Record<Status, number>;
  for (const s of statuses) c[s]++;
  return c;
}

/** The four lanes as a strip, then every factor, filterable by status and open for its rule and numbers. */
export function FactorMap() {
  const [filter, setFilter] = useState<Status | 'all'>('all');
  const [allOpen, setAllOpen] = useState(false);
  const all = LANES.flatMap((l) => l.factors.map((f) => f.status));
  const tot = counts(all);

  return (
    <>
      <nav className="flow" aria-label="The four parts of the score">
        {LANES.map((lane) => {
          const c = counts(lane.factors.map((f) => f.status));
          const n = lane.factors.length;
          return (
            <a className="card" href={`#${lane.id}`} key={lane.id} style={{ textDecoration: 'none' }}>
              <span className="k">{lane.k}</span>
              <h3>{lane.title}</h3>
              <span className="bar" aria-hidden="true">
                {ORDER.filter((k) => c[k]).map((k) => (
                  <span key={k} style={{ width: `${(100 * c[k]) / n}%`, background: BAR[k] }} />
                ))}
              </span>
              <p>
                {n} factors: {ORDER.filter((k) => c[k]).map((k) => `${c[k]} ${STATUS_WORDS[k].toLowerCase()}`).join(' · ')}
              </p>
            </a>
          );
        })}
      </nav>

      <div className="filters" role="group" aria-label="Show factors by status" style={{ marginTop: 40 }}>
        <button type="button" className="chip" aria-pressed={filter === 'all'} onClick={() => setFilter('all')}>
          All {all.length}
        </button>
        {ORDER.filter((k) => tot[k]).map((k) => (
          <button key={k} type="button" className="chip" aria-pressed={filter === k} onClick={() => setFilter(k)}>
            {STATUS_WORDS[k]} {tot[k]}
          </button>
        ))}
        <button type="button" className="btn ghost" style={{ minHeight: 40, padding: '0 16px', fontSize: 15, borderRadius: 999 }} onClick={() => setAllOpen((v) => !v)}>
          {allOpen ? 'Collapse all' : 'Expand all'}
        </button>
      </div>

      {LANES.map((lane) => {
        const shown = lane.factors.map((f, i) => ({ f, i })).filter(({ f }) => filter === 'all' || f.status === filter);
        if (!shown.length) return null;
        return (
          <section className="lane" id={lane.id} key={lane.id}>
            <div className="lane-head">
              <p className="eyebrow">{lane.k}</p>
              <h2>{lane.title}</h2>
              <p>{lane.intro}</p>
            </div>
            <div className="factors">
              {shown.map(({ f, i }) => (
                <details className="factor" key={f.name} open={allOpen || undefined}>
                  <summary>
                    <div>
                      <div className="name">
                        {lane.ordered ? <span className="ix">Step {i + 1}</span> : null}
                        <h3>{f.name}</h3>
                      </div>
                      <p className="line">{f.line}</p>
                    </div>
                    <div className="tags">
                      <span className={`status ${f.status}`}>{STATUS_WORDS[f.status]}</span>
                      {(f.basis ?? []).map((b) => (
                        <span className="tag" key={b}>{b}</span>
                      ))}
                      {f.path ? <span className="tag">{f.path}</span> : null}
                      {f.meta ? <span className="tag meta">Meta model</span> : null}
                      <span className="chev" aria-hidden="true">›</span>
                    </div>
                  </summary>
                  <div className="body">
                    {f.data ? (
                      <div className="blk">
                        <span className="lbl">Data</span>
                        <p>{f.data}</p>
                      </div>
                    ) : null}
                    {f.rule ? (
                      <div className="blk">
                        <span className="lbl">Rule and numbers</span>
                        <ul>
                          {f.rule.map((r) => (
                            <li key={r}>{r}</li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                    {f.gap ? (
                      <div className="blk">
                        <span className="lbl">{f.status === 'tbd' ? 'Why it waits' : 'What it misses'}</span>
                        <p className="why">{f.gap}</p>
                      </div>
                    ) : null}
                    {f.meta ? (
                      <div className="blk">
                        <span className="lbl">Where a Meta model helps</span>
                        <p>{f.meta}</p>
                      </div>
                    ) : null}
                    {!f.data && !f.rule && !f.gap && !f.meta ? <p className="why">Nothing more to add yet.</p> : null}
                  </div>
                </details>
              ))}
            </div>
          </section>
        );
      })}
    </>
  );
}
