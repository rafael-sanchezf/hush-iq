import type { Metadata } from 'next';
import Link from 'next/link';

import { VerdictMeter } from '@/components/verdict-meter';
import claremont from '@/lib/mock/fixtures/claremont.v1.json';
import manhattan from '@/lib/replay/manhattan.json';
import { scoreFromV1, type Baseline, type V1Response } from '@/lib/replay/v2';
import type { Answers } from '@/lib/types';
import { REPO_URL } from '@/lib/env';
import { SOURCE_WORDS, pct } from '@/lib/words';

export const metadata: Metadata = {
  title: 'For listing sites',
  description: 'What a listing site gets from one Hush IQ call: a verdict per renter, each source’s rank, the dealbreakers, and a cited paragraph.',
};

// The card on this page is a real score, computed at build time: the Morningside sample for a renter bothered by sirens.
const ANSWERS: Answers = { sleep_from: 23, sleep_until: 7, day_bothers: true, bothers: ['sirens'] };
const card = scoreFromV1(claremont as unknown as V1Response, { floor: 4, position: 'unknown' }, ANSWERS, manhattan as unknown as Baseline);

const GETS = [
  { h: 'The word, for this renter', f: 'verdict', p: 'Very loud to Very quiet, one fifth of Manhattan each. The same apartment can read Quiet to one renter and Typical to another, because what keeps them up differs.' },
  { h: 'Each source’s rank', f: 'ingredients[].quieter_than', p: 'Street traffic, local businesses, neighbors, sirens and construction, each “quieter than X% of Manhattan apartments”, with its weight for this renter and the city records behind it.' },
  { h: 'Dealbreakers, named', f: 'caps', p: 'A source in Manhattan’s loudest 5% holds the verdict at Loud; one the renter cares about, in the loudest 10%, at Typical. The response says which source did it.' },
  { h: 'A range instead of a guess', f: 'range', p: 'When your listing does not give the floor or the side, the score uses the expected floor and returns the loudest and quietest case, so nobody is asked what they have not seen.' },
  { h: 'A paragraph that shows its work', f: 'POST /verdict', p: 'Three to five sentences on what this renter will hear, each citing numbered evidence lines. Code checks every citation, number and name before it leaves.' },
  { h: 'Facts from your own listing', f: 'POST /read', p: 'No structured floor or side? Send the description and photos. The reader returns each fact with its quoted line or photo, and “can’t tell” when it is not there.' },
];

export default function ForListingSites() {
  const rows = [...card.ingredients].sort((a, b) => a.quieter_than - b.quieter_than);
  return (
    <>
      <section className="page-hero">
        <div className="wrap">
          <p className="eyebrow">For listing sites</p>
          <h1 style={{ marginTop: 14 }}>One call, a verdict for every renter who opens the listing</h1>
          <p className="lede">
            Your listing already knows the address, often the floor, sometimes the side. Send them with the renter’s three answers and get back how loud the
            apartment is for that person, against the rest of Manhattan, with every source named and every line cited.
          </p>
        </div>
      </section>

      <section className="section" style={{ paddingTop: 56 }}>
        <div className="wrap">
          <div className="listing-mock">
            <div className="fake" aria-hidden="true">
              <div className="ph">Your listing page</div>
              <span className="price">$3,150/month</span>
              <span className="ln w60" />
              <span className="ln" />
              <span className="ln w40" />
            </div>
            <aside className="embed" aria-label="A Hush IQ verdict on a listing">
              <span className="k">
                <span>How loud, for you</span>
                <span>Hush IQ</span>
              </span>
              <span className="word">{card.verdict}</span>
              <VerdictMeter verdict={card.verdict} range={card.range} />
              <p className="muted" style={{ fontSize: 14 }}>
                Asleep 11 pm to 7 am, bothered by sirens. Quieter than {pct(card.quieter_than)} of Manhattan apartments
                {card.range ? `; ${card.range.loudest_case.verdict} on the street side, ${card.range.quietest_case.verdict} at the rear` : ''}.
              </p>
              <div className="mini-rows">
                {rows.map((i) => (
                  <div key={i.name}>
                    <span>
                      {SOURCE_WORDS[i.name].title}
                      {i.ticked ? ' ·  matters to you' : ''}
                    </span>
                    <span>quieter than {pct(i.quieter_than)}</span>
                  </div>
                ))}
              </div>
            </aside>
          </div>
          <p className="foot-note">
            A real score: 140 Claremont Avenue, floor 4 from the listing, side not given, for a renter who ticked sirens. Drawn here to show the data; the
            embeddable card is on the roadmap, and your site draws it in its own style today.
          </p>
        </div>
      </section>

      <section className="section">
        <div className="wrap">
          <div className="section-head">
            <p className="eyebrow">What one call returns</p>
            <h2>Everything a renter asks before a viewing</h2>
          </div>
          <div className="gets">
            {GETS.map((g) => (
              <div className="card" key={g.h}>
                <h3>{g.h}</h3>
                <p>{g.p}</p>
                <p>
                  <code>{g.f}</code>
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="section">
        <div className="wrap split">
          <div className="card">
            <p className="eyebrow">Wiring it</p>
            <h3>Four steps</h3>
            <ol className="steps-list" style={{ marginTop: 8 }}>
              <li>
                <p><b>Send what the listing has.</b>The address, and the floor and side when you have them, to <code>GET /v2/score</code>.</p>
              </li>
              <li>
                <p><b>Add the renter’s answers if you have them.</b>Sleep hours, daytime noise, what gets to them. Without them: asleep 11 pm to 7 am, daytime counts, nothing ticked.</p>
              </li>
              <li>
                <p><b>Show the word and the ranks.</b>Link the cited paragraph from <code>POST /verdict</code> for the renter who asks why.</p>
              </li>
              <li>
                <p><b>No structured floor or side?</b>Send the description and photos to <code>POST /read</code> first.</p>
              </li>
            </ol>
          </div>
          <div className="card">
            <p className="eyebrow">Where it stands</p>
            <h3>Honest limits</h3>
            <p>
              Ranks are against a 300-building Manhattan sample; addresses in the other boroughs score, but against Manhattan. There are no API keys or rate
              limits yet, and the reader and verdict services are built but not hosted. Every number is a rank from public data, not a sound measurement.
            </p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px 24px', marginTop: 6 }}>
              <Link href="/docs/" className="link-arrow">
                API docs
              </Link>
              <a href={REPO_URL} className="link-arrow">
                Source on GitHub
              </a>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
