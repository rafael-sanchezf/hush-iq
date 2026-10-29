'use client';

import { useState } from 'react';

import { VerdictMeter } from '@/components/verdict-meter';
import type { Answers, Cap, EvidenceRef, Field, Observed, RangeCase, ReaderFields, Score, Services, Source, Verdict } from '@/lib/types';
import { VERDICTS } from '@/lib/types';
import { SOURCE_WORDS, addressLine, forWhom, pct, sideWords } from '@/lib/words';

interface Props {
  score: Score;
  verdict: Verdict | null;
  dropped: number;
  fields: ReaderFields;
  observed: Observed;
  answers: Answers;
  services: Services;
  updating: boolean;
}

function quoteOf(f: Field<unknown>): string | null {
  const e = f.evidence[0];
  if (!e) return null;
  return e.source === 'text' ? `“${e.quote}”` : `${photoLabel(e)}: ${e.what}`;
}

function photoLabel(e: EvidenceRef): string {
  const n = Number(e.source.split(':')[1]);
  return Number.isFinite(n) ? `Photo ${n + 1}` : 'A photo';
}

function caseWords(c: RangeCase): string {
  return [c.floor ? `floor ${c.floor}` : null, sideWords(c.side)].filter(Boolean).join(', ');
}

/** One line per source that hit a cap: the strongest cap it set, and whether it changed the verdict. */
function capLines(caps: Cap[]): Cap[] {
  const best = new Map<Source, Cap>();
  for (const c of caps) {
    const prev = best.get(c.source);
    if (!prev || VERDICTS.indexOf(c.cap) < VERDICTS.indexOf(prev.cap) || (c.applied && !prev.applied)) best.set(c.source, c);
  }
  return [...best.values()].sort((a, b) => Number(b.applied) - Number(a.applied));
}

export function Result({ score, verdict, dropped, fields, observed, answers, services, updating }: Props) {
  const [hot, setHot] = useState<string | null>(null);
  const range = score.range;
  const caps = capLines(score.caps);
  const sources = [...score.ingredients].sort((a, b) => a.quieter_than - b.quieter_than);
  const facts = score.building_facts;

  const flash = (id: string) => {
    setHot(id);
    document.getElementById(`ev-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  };

  const floorQuote = quoteOf(fields.floor);
  const sideQuote = quoteOf(fields.side);

  return (
    <div className={`result${updating ? ' updating' : ''}`} id="verdict" aria-live="polite">
      <section className="verdict-card" aria-label="The verdict">
        <div>
          <p className="addr">{addressLine(score.address.label, score.address.query)}</p>
          <h3 className="word">{score.verdict} for Manhattan</h3>
          <VerdictMeter verdict={score.verdict} range={range} />
          <p className="for">
            {forWhom(answers)} <b>Quieter than {pct(score.quieter_than)} of Manhattan apartments.</b>
          </p>
          <div className="hours">
            <span className="k eyebrow" style={{ fontSize: 12 }}>How your hours count</span>
            <div className="hours-bar" aria-hidden="true">
              {(['night', 'early', 'day'] as const).map((w) => (
                <span key={w} className={w} style={{ flexGrow: score.slot_weights[w] }}>
                  {score.slot_weights[w] >= 12 ? `${w === 'night' ? 'Night' : w === 'early' ? 'Early' : 'Day'} ${Math.round(score.slot_weights[w])}%` : ''}
                </span>
              ))}
            </div>
            <p className="hours-note">
              Night 10 pm to 5 am, early 5 to 8 am, day 8 am to 10 pm. An hour you sleep counts three times an hour awake
              {answers.day_bothers ? '' : ', six when daytime noise does not bother you'}.
            </p>
          </div>
          {caps.map((c) => (
            <div className="cap-line" key={`${c.source}-${c.cap}`}>
              <span className={`glyph ${c.applied ? 'refused' : 'cant_tell'}`} aria-hidden="true">!</span>
              <span>
                {c.applied ? (
                  <>
                    <b>Held at {c.cap} by {SOURCE_WORDS[c.source].title.toLowerCase()}</b>: {c.why}. Without it the verdict would read {score.uncapped_verdict}.
                  </>
                ) : (
                  <>
                    <b>{SOURCE_WORDS[c.source].title}</b> is {c.why.replace(/^you said it bothers you, and it is /, '')}
                    {c.why.startsWith('you said') ? ', and you said it bothers you' : ''}. On its own it would hold the verdict at {c.cap}.
                  </>
                )}
              </span>
            </div>
          ))}
        </div>
        <div className="unit-facts">
          <div className="unit-fact">
            <span className="k">Floor</span>
            <span className="v">
              {score.unit.floor_from === 'listing' ? `Floor ${score.unit.floor}` : score.unit.floor ? `Floor ${score.unit.floor}, expected` : 'Unknown'}
            </span>
            <span className="q">
              {score.unit.floor_from === 'listing' && floorQuote ? `From the listing: ${floorQuote}` : 'Not in the listing: the building’s middle residential floor.'}
            </span>
          </div>
          <div className="unit-fact">
            <span className="k">Side</span>
            <span className="v">{score.unit.side_from === 'listing' ? (score.unit.side === 'front' ? 'Street side' : 'Rear') : 'Can’t tell'}</span>
            <span className="q">{score.unit.side_from === 'listing' && sideQuote ? `From the listing: ${sideQuote}` : 'Not in the listing: scored between street side and rear.'}</span>
          </div>
          {range ? (
            <div className="unit-fact">
              <span className="k">Range</span>
              <span className="v">
                {range.loudest_case.verdict === range.quietest_case.verdict ? `${range.loudest_case.verdict} either way` : `${range.loudest_case.verdict} to ${range.quietest_case.verdict}`}
              </span>
              <span className="q">
                {range.loudest_case.verdict} at {caseWords(range.loudest_case)}; {range.quietest_case.verdict} at {caseWords(range.quietest_case)}.
              </span>
            </div>
          ) : null}
          <div className="unit-fact">
            <span className="k">Building</span>
            <span className="v">
              {[score.unit.building_floors ? `${score.unit.building_floors} floors` : null, facts?.yearbuilt ? `built ${facts.yearbuilt}` : null].filter(Boolean).join(', ') || 'Unknown'}
            </span>
            <span className="q">
              {[facts?.unitsres ? `${facts.unitsres} apartments` : null, score.unit.ground_floor_commercial ? 'shops or a bar on the ground floor' : null]
                .filter(Boolean)
                .join(', ') || 'From PLUTO, the city’s lot records.'}
            </span>
          </div>
        </div>
      </section>

      <div className="result-grid">
        <section className="card" aria-labelledby="hear-title">
          <div className="block-head">
            <h3 id="hear-title">What you’ll hear</h3>
            <span className={`pill${verdict?.writer === 'muse-spark-open' ? ' ink' : ''}`}>
              <span className="dot" />
              {verdict ? (verdict.writer === 'muse-spark-open' ? 'Muse Spark Open' : 'Template') : 'Writing'}
            </span>
          </div>
          {verdict ? (
            <>
              <p className="paragraph">
                {verdict.sentences.map((s, i) => (
                  <span className="s" key={i}>
                    {s.text}
                    {s.cites.map((c) => (
                      <a
                        key={c}
                        href={`#ev-${c}`}
                        className={`cite${hot === c ? ' hot' : ''}`}
                        onMouseEnter={() => setHot(c)}
                        onFocus={() => setHot(c)}
                        onClick={(e) => {
                          e.preventDefault();
                          flash(c);
                        }}
                        aria-label={`Evidence ${c}`}
                      >
                        {c.replace(/^E/, '')}
                      </a>
                    ))}{' '}
                  </span>
                ))}
              </p>
              <p className="writer">
                {verdict.writer === 'muse-spark-open'
                  ? 'Written by Muse Spark Open on Baseten. It may cite only the evidence lines below; the server and this page both check.'
                  : services.verdict === 'live'
                    ? 'The model did not answer in time, so the writer’s template wrote this, under the same rule: every sentence cites the lines below.'
                    : 'Written by the verdict writer’s template until Muse Spark Open is deployed. Same rule: every sentence cites the lines below.'}
                {dropped ? ` ${dropped} citation${dropped > 1 ? 's' : ''} pointed at no line and ${dropped > 1 ? 'were' : 'was'} removed.` : ''}
              </p>
              <ol className="evidence" aria-label="The evidence the writer was sent">
                {verdict.evidence.map((e) => (
                  <li key={e.id} id={`ev-${e.id}`} className={hot === e.id ? 'hot' : undefined} onMouseEnter={() => setHot(e.id)}>
                    <b>{e.id}</b>
                    <span>{e.text}</span>
                  </li>
                ))}
              </ol>
            </>
          ) : (
            <p className="muted">Writing the paragraph from the evidence…</p>
          )}
        </section>

        <section className="card" aria-labelledby="sources-title">
          <div className="block-head">
            <h3 id="sources-title">Source by source</h3>
            <span className="muted" style={{ fontSize: 14 }}>Loudest first</span>
          </div>
          <div className="sources">
            {sources.map((i) => (
              <article className="source" key={i.name}>
                <div className="source-top">
                  <h4>{SOURCE_WORDS[i.name].title}</h4>
                  <span className="num">
                    {pct(i.quieter_than)}
                    <small>quieter than</small>
                  </span>
                </div>
                <p className="rank-line">
                  Quieter than {pct(i.quieter_than)} of Manhattan apartments · {Math.round(i.weight)}% of your verdict
                </p>
                <div className={`rank-bar${i.ticked ? ' ticked' : ''}`} aria-hidden="true">
                  <i style={{ width: `${Math.max(2, i.quieter_than)}%` }} />
                </div>
                <div className="rank-ends" aria-hidden="true">
                  <span>Loudest</span>
                  <span>Quietest</span>
                </div>
                {i.ticked || i.temporary ? (
                  <div className="tags">
                    {i.ticked ? <span className="pill ink">Matters to you</span> : null}
                    {i.temporary ? <span className="pill">Temporary</span> : null}
                  </div>
                ) : null}
                {i.evidence.length ? (
                  <details>
                    <summary>The city data ({i.evidence.length} line{i.evidence.length > 1 ? 's' : ''})</summary>
                    <ul>
                      {i.evidence.map((e, k) => (
                        <li key={k}>{e}</li>
                      ))}
                    </ul>
                  </details>
                ) : null}
              </article>
            ))}
          </div>
        </section>
      </div>

      <section className="card" aria-labelledby="saw-title">
        <div className="block-head">
          <h3 id="saw-title">What the model saw</h3>
          <span className="muted" style={{ fontSize: 14 }}>Shown, not scored yet</span>
        </div>
        <div className="saw">
          {(
            [
              ['Unit', fields.unit],
              ['View', observed.view],
              ['Windows', observed.windows],
              ['AC units', observed.ac_units],
              ['Walls', observed.wall_material],
            ] as [string, Field<unknown>][]
          ).map(([k, f]) => (
            <div className="saw-item" key={k}>
              <span className="k">{k}</span>
              <span className={`v${f.status === 'read' ? '' : ' cant'}`}>{f.status === 'read' ? String(f.value) : 'Can’t tell'}</span>
              <span className="q">{quoteOf(f) ?? 'Nothing in the listing says it.'}</span>
            </div>
          ))}
        </div>
        <p className="foot-note">
          These join the score once the photo test shows the reader gets them right and each has a rule. Until then they are here so you can check them at a
          viewing.
        </p>
      </section>

      <p className="foot-note">
        Engine v2 against {score.manhattan.buildings} Manhattan buildings standing for {score.manhattan.apartments.toLocaleString('en-US')} apartments
        (sample of {score.manhattan.as_of}); city data as of {score.as_of ?? 'today'}.{' '}
        {score.replayed_from === 'v1'
          ? 'Ranked in your browser from the hosted model’s ingredients until /v2/score is deployed; the numbers match the engine’s own.'
          : ''}{' '}
        Every number is a rank against Manhattan, not a sound measurement.
      </p>
    </div>
  );
}
