import type { Metadata } from 'next';
import Link from 'next/link';

import { FactorMap } from '@/components/factor-map';
import { RULES, STATUS_HELP, STATUS_WORDS, type Status } from '@/content/factors';
import { REPO_URL } from '@/lib/env';

export const metadata: Metadata = {
  title: 'How it’s worked out',
  description: 'Every factor in the Hush IQ score, what is live, what is next, and what no public data can see yet.',
};

/** The permit reader on three addresses: what it read, from the recorded live runs of Oct 28
 * (services/adjust/tests/fixtures/live), and a live rerun on Nov 3 through engine v2 (python -m adjust.demo_v2).
 * Recorded, not live: the score the demo shows does not take the adjustment yet (CLM-1). */
const PERMIT_RUNS = [
  {
    address: '100 West 57th Street',
    read: [
      ['interior renovation', 'INTERIOR RENOVATION OF NON-LOAD WALLS, FLOORS, AND CIELING'],
      ['interior renovation', 'OFFICE RENOVATION'],
    ],
    permits: 6,
    adjustment: 'Quieter by 1 of 2',
    rank: 'Construction rank 2 → 5: quieter than 5% of Manhattan apartments instead of 2%. The verdict stays Very loud, 16.7 → 18.3.',
  },
  {
    address: '350 East 86th Street',
    read: [
      ['new building', 'SUPPORT OF EXCAVATION WORK'],
      ['facade', 'Facade Repairs'],
    ],
    permits: 2,
    adjustment: 'Louder by 1 of 2',
    rank: 'Construction rank 0 → 0: already louder than every apartment in the sample, so the cap leaves the verdict at Very loud.',
  },
  {
    address: '55 Bethune Street',
    read: [['facade, years', 'EXTERIOR MASONRY RESTORATION, ROOF REPLACEMENTS']],
    permits: 1,
    adjustment: 'Louder by 1 of 2',
    rank: 'Construction rank 35.7 → 21.7. The verdict stays Quiet, 64.7 → 62; for a renter who ticks construction, Typical, 55.7 → 48.3.',
  },
];

const LEGEND: Status[] = ['live', 'v2', 'next', 'partial', 'tbd', 'removed'];

export default function Method() {
  return (
    <>
      <section className="page-hero">
        <div className="wrap">
          <p className="eyebrow">Method</p>
          <h1 style={{ marginTop: 14 }}>What makes an apartment loud, for you</h1>
          <p className="lede">
            Three things decide it. The sources of noise around the building. What about this apartment lets that noise in or keeps it out. And who you are:
            when you sleep and what gets to you. The score turns all three into one verdict against the rest of Manhattan.
          </p>
        </div>
      </section>

      <section className="section" style={{ paddingTop: 56 }}>
        <div className="wrap">
          <div className="legend" style={{ marginBottom: 20 }}>
            {LEGEND.map((s) => (
              <span key={s} style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
                <span className={`status ${s}`}>{STATUS_WORDS[s]}</span>
                {STATUS_HELP[s]}
              </span>
            ))}
          </div>
          <FactorMap />
        </div>
      </section>

      <section className="section">
        <div className="wrap">
          <div className="section-head">
            <p className="eyebrow">Engine v2</p>
            <h2>Eight rules, from sources to a verdict</h2>
            <p>
              The first model added the five sources together in decibels. That assumes a neighbors “66” means the same as a street “66”. For the street it
              roughly does, since it comes from road physics; for neighbors, sirens and construction the numbers are complaint and permit counts converted
              by our own rules. Engine v2 compares each source only with itself, and ranks against a fixed Manhattan so a higher floor at the rear always moves
              the verdict the right way.
            </p>
          </div>
          <ol className="rules">
            {RULES.map((r) => (
              <li key={r.k}>
                <span className="k">{r.k}</span>
                <div>
                  <h3>{r.title}</h3>
                  {r.body.map((b) => (
                    <p key={b}>{b}</p>
                  ))}
                </div>
              </li>
            ))}
          </ol>
          <p className="foot-note" style={{ marginTop: 20 }}>
            The rules and their numbers live in <a href={`${REPO_URL}/blob/main/packages/model/ENGINE_V2.md`}>ENGINE_V2.md</a>; the earlier steps, M1 to
            M13, in <a href={`${REPO_URL}/blob/main/packages/model/DECISIONS.md`}>DECISIONS.md</a>.
          </p>
        </div>
      </section>

      <section className="section">
        <div className="wrap split">
          <div className="card">
            <p className="eyebrow">Where Meta models come in</p>
            <h3>They read; they never score</h3>
            <p>
              The listing reader looks at the text and the photos for facts about the unit: the floor, the side, the view, windows, a window AC, walls where
              they show. It ignores the listing’s adjectives and ties every fact to its line or photo. The verdict writer explains the result and may cite only
              the evidence it was sent. The permit reader says how big and how long a construction job is. Each output is checked in code, not by the prompt.
            </p>
          </div>
          <div className="card">
            <p className="eyebrow">What it is not</p>
            <h3>Not a sound meter</h3>
            <p>
              Every number on a verdict is a rank against Manhattan. Nothing here has been checked against a meter yet; a short phone reading at a viewing is on the
              roadmap. 311 counts measure who complains, not how loud it is, and construction is temporary.
            </p>
            <Link href="/#demo" className="link-arrow">
              Try a listing
            </Link>
          </div>
        </div>
      </section>
      <section className="section">
        <div className="wrap">
          <div className="section-head">
            <p className="eyebrow">The permit reader</p>
            <h2>What the permit counts cannot see</h2>
            <p>
              Construction is scored from the permits on the building’s tax block. A count treats an office refit like an excavation. Muse Spark reads each
              permit’s job description, says what kind of work it is and how long it runs, quoting the permit, and moves the construction source by at
              most two steps. The cap is set in code, and a tool refuses an adjustment that cites a permit not in the pull. It moves the source; it rarely moves
              the verdict, and that is the point of the cap. Three addresses:
            </p>
          </div>
          <div className="three">
            {PERMIT_RUNS.map((r) => (
              <div className="card" key={r.address}>
                <h3>{r.address}</h3>
                {r.read.map(([kind, quote]) => (
                  <p key={quote}>
                    <b>{kind}</b>: “{quote}”
                  </p>
                ))}
                <p>
                  <b>{r.adjustment}</b>, citing {r.permits} permit{r.permits > 1 ? 's' : ''}. {r.rank}
                </p>
                <p className="foot">muse-spark-1.3. Readings recorded Oct 28; adjustment and ranks from a live rerun, Nov 3.</p>
              </div>
            ))}
          </div>
          <p className="foot-note" style={{ marginTop: 20 }}>
            Recorded live runs, not live on this page: the demo’s score does not take the adjustment yet. The runs are in{' '}
            <a href={`${REPO_URL}/tree/main/services/adjust/tests/fixtures/live`}>services/adjust</a>; the service answers at <code>POST /adjust/permits</code>.
          </p>
        </div>
      </section>
    </>
  );
}
