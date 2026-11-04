import Link from 'next/link';

import { Demo } from '@/components/demo/demo';
import { VerdictMeter } from '@/components/verdict-meter';
import claremont from '@/lib/mock/fixtures/claremont.v1.json';
import manhattan from '@/lib/replay/manhattan.json';
import { scoreFromV1, type Baseline, type V1Response } from '@/lib/replay/v2';
import { DEFAULT_ANSWERS, SOURCE_WORDS, forWhom, pct } from '@/lib/words';

// The hero card is the product itself: the Morningside sample, scored at build time by the same engine.
const preview = scoreFromV1(claremont as unknown as V1Response, { floor: 4, position: 'unknown' }, DEFAULT_ANSWERS, manhattan as unknown as Baseline);

export default function Home() {
  const rows = [...preview.ingredients].sort((a, b) => a.quieter_than - b.quieter_than).slice(0, 3);
  return (
    <>
      <section className="hero">
        <div className="wrap">
          <div>
            <p className="eyebrow">New York apartments, before you sign</p>
            <h1 style={{ marginTop: 16 }}>How loud is this apartment, for the way you sleep?</h1>
            <p className="hero-lede">
              Paste a listing. A Meta model reads it for the apartment itself, the city’s own data scores the noise around it, and three taps say what keeps
              you up. You get one verdict against Manhattan, and every line of it is cited.
            </p>
            <div className="hero-actions">
              <Link href="#demo" className="btn">
                Try a listing
              </Link>
              <Link href="/method/" className="link-arrow">
                How it’s worked out
              </Link>
            </div>
            <div className="hero-proof">
              <div>
                <b>8</b>public city datasets
              </div>
              <div>
                <b>{preview.manhattan.buildings}</b>Manhattan buildings to rank against
              </div>
              <div>
                <b>0</b>sources the model may invent
              </div>
            </div>
          </div>
          <aside className="phone-card" aria-label="An example verdict">
            <p className="addr">140 Claremont Avenue · floor 4 · side not given</p>
            <p className="word">{preview.verdict} for Manhattan</p>
            <VerdictMeter verdict={preview.verdict} range={preview.range} />
            <p className="for">
              {forWhom(DEFAULT_ANSWERS)} Quieter than {pct(preview.quieter_than)} of Manhattan apartments.
            </p>
            <div className="rows">
              {rows.map((i) => (
                <div className="row" key={i.name}>
                  <span>{SOURCE_WORDS[i.name].title}</span>
                  <span>quieter than {pct(i.quieter_than)}</span>
                </div>
              ))}
            </div>
            <p className="quote">Floor 4 from “on the fourth floor”. The side is not in the listing, so the verdict carries a range.</p>
          </aside>
        </div>
      </section>

      <section className="section" id="demo">
        <div className="wrap">
          <div className="demo-head">
            <div className="section-head" style={{ marginBottom: 0 }}>
              <p className="eyebrow">Try it</p>
              <h2>Paste a listing. Watch it get read.</h2>
            </div>
            <p className="mode-note">
              Facts only. A floor counts when the listing says it; “quiet” and “sun-drenched” do not. Anything the listing leaves out becomes a range, never a
              guess, and you are never asked for a floor you have not seen.
            </p>
          </div>
          <Demo />
        </div>
      </section>

      <section className="section">
        <div className="wrap">
          <div className="section-head">
            <p className="eyebrow">Three sources of truth</p>
            <h2>A map pin gets one noise score for everyone. An apartment is not a map pin.</h2>
            <p>The same street sounds different on the fourth floor at the back than on the second floor at the front, and different again to someone who sleeps until ten.</p>
          </div>
          <div className="three">
            <div className="card">
              <span className="k">1</span>
              <h3>The city’s data</h3>
              <p>
                311 complaints, lot records, the street centerline, building permits, liquor licenses, the subway and emergency stations score each source of
                noise around the building, and rank it against the same source across Manhattan.
              </p>
              <p className="foot">Deterministic. The model built before the hackathon, unchanged.</p>
            </div>
            <div className="card">
              <span className="k">2</span>
              <h3>The listing</h3>
              <p>
                Muse Spark reads the text and the photos for the apartment itself: floor, side, view, windows, AC units, walls. Each fact is tied to its line
                or its photo. “Can’t tell” is an answer; adjectives are not.
              </p>
              <p className="foot">A tool refuses any field without its quoted line.</p>
            </div>
            <div className="card">
              <span className="k">3</span>
              <h3>You</h3>
              <p>
                When you sleep, whether daytime noise bothers you, and what gets to you. Your answers set how much each source and each hour counts, and which
                source is a dealbreaker.
              </p>
              <p className="foot">Three taps. Never the floor or the side.</p>
            </div>
          </div>
        </div>
      </section>

      <section className="section">
        <div className="wrap split">
          <div className="card">
            <p className="eyebrow">For listing sites</p>
            <h3>One call, one verdict per renter</h3>
            <p>Send the address and what your listing already knows. Get the word, each source’s rank, any dealbreaker and a cited paragraph back.</p>
            <Link href="/for-listing-sites/" className="link-arrow">
              What a site gets
            </Link>
          </div>
          <div className="card">
            <p className="eyebrow">Method</p>
            <h3>Every factor, and what it waits on</h3>
            <p>What is live, what is next, and what no public data can see yet, in plain words, with the rule and the numbers behind each one.</p>
            <Link href="/method/" className="link-arrow">
              Read the method
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
