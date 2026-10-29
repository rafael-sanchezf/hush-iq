'use client';

import { useState } from 'react';

import type { ReaderTurn, Services } from '@/lib/types';

const GLYPH: Record<string, string> = { ok: '✓', cant_tell: '?', refused: '!', error: '×' };

interface Props {
  /** The reader's own mode from its last result, when it said: a live service with no key runs its mock. */
  mode: 'live' | 'mock' | null;
  turns: ReaderTurn[];
  working: boolean;
  workingLabel: string;
  services: Services;
  asking: boolean;
  error: string | null;
  onAddress: (address: string) => void;
}

/** The reader's turns as they stream: what it read, the line it read it from, what it could not tell. */
export function ReaderPanel({ mode, turns, working, workingLabel, services, asking, error, onAddress }: Props) {
  const [address, setAddress] = useState('');
  const live = services.reader === 'live' && mode !== 'mock';
  return (
    <section className="reader" aria-labelledby="reader-title">
      <div className="reader-head">
        <h3 id="reader-title">The reader</h3>
        <span className={`pill${live ? ' ink' : ''}`} title={live ? undefined : 'The reader service is not deployed yet. This replay follows the same rules, without a model.'}>
          <span className="dot" />
          {live ? 'Muse Spark, live' : services.reader === 'live' ? 'Reader, no model key' : 'Replay'}
        </span>
      </div>
      <p className="reader-sub">
        {live
          ? 'Muse Spark reads the text and the photos for facts about the unit. A tool refuses any field without its line.'
          : services.reader === 'live'
            ? 'The reader service is up but has no Meta key yet, so its rules stand in for the model. Same checks, no photos.'
            : 'A scripted stand-in for Muse Spark until the reader is deployed. Same rule: a field without its quoted line is refused.'}
      </p>

      {turns.length === 0 && !working ? (
        <div className="reader-empty">
          <div>
            <div className="ghost-steps" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
            Paste a listing or pick a sample, then press Read. Each step shows here with the line it came from.
          </div>
        </div>
      ) : (
        <ol className="turns" aria-live="polite" aria-busy={working}>
          {turns.map((t) => {
            const status = t.status ?? 'ok';
            return (
              <li key={t.i} className={`turn ${status}`}>
                <span className={`glyph ${status}`} aria-hidden="true">
                  {GLYPH[status] ?? '•'}
                </span>
                <div className="turn-body">
                  <div className="turn-title">
                    <span>{t.title}</span>
                    <span className="kind">
                      {t.tool ?? t.kind}
                      {t.ms !== undefined ? ` · ${(t.ms / 1000).toFixed(1)} s` : ''}
                    </span>
                  </div>
                  {t.detail ? <div className="turn-detail">{t.detail}</div> : null}
                </div>
              </li>
            );
          })}
          {working ? (
            <li className="turn">
              <span className="glyph working" aria-hidden="true" />
              <div className="turn-body">
                <div className="turn-title muted">{workingLabel}</div>
              </div>
            </li>
          ) : null}
        </ol>
      )}

      {asking ? (
        <form
          className="ask"
          onSubmit={(e) => {
            e.preventDefault();
            if (address.trim().length > 3) onAddress(address.trim());
          }}
        >
          <label htmlFor="ask-address" className="sr-only">
            The building’s street address
          </label>
          <input id="ask-address" value={address} onChange={(e) => setAddress(e.target.value)} placeholder="e.g. 140 Claremont Ave, Manhattan" autoComplete="street-address" />
          <button className="btn" type="submit">
            Score it
          </button>
        </form>
      ) : null}
      {error ? <p className="error-line">{error}</p> : null}
    </section>
  );
}
