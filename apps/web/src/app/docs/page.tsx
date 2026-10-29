import type { Metadata } from 'next';

import { REPO_URL } from '@/lib/env';

export const metadata: Metadata = {
  title: 'API',
  description: 'The Hush IQ API: /v2/score for a verdict by rank, /read for the listing reader, /verdict for the cited paragraph.',
};

const SCORE_EXAMPLE = `{
  "engine": "v2",
  "verdict": "Very loud",
  "quieter_than": 8.7,
  "uncapped_verdict": "Very loud",
  "caps": [
    { "source": "nightlife", "cap": "Loud", "why": "in Manhattan's loudest 5%", "applied": false },
    { "source": "sirens", "cap": "Typical", "applied": false,
      "why": "you said it bothers you, and it is in Manhattan's loudest 10%" }
  ],
  "range": null,
  "ingredients": [
    { "name": "street", "label": "Street", "quieter_than": 32.3, "verdict": "Loud",
      "weight": 47.1, "ticked": true, "temporary": false,
      "evidence": ["W  47 ST: one lane, 1 travel lane, 25 mph, bus or truck route, 20 m away", "…"] },
    { "name": "nightlife", "label": "Nightlife", "quieter_than": 1.3, "verdict": "Very loud",
      "weight": 7.4, "ticked": false, "temporary": false,
      "evidence": ["58 licensed venues within 150 m: 12 bars, 25 restaurants, 21 venues", "…"] }
    // building, sirens, construction
  ],
  "answers": { "sleep": { "from": 23, "until": 7 }, "day_bothers": true, "ticks": ["traffic", "sirens"] },
  "slot_weights": { "night": 47.5, "early": 17.5, "day": 35.0 },
  "unit": { "floor": 3, "floor_from": "listing", "side": "front", "side_from": "listing",
            "building_floors": 7, "ground_floor_commercial": true },
  "address": { "label": "310 WEST 47 STREET, New York, NY, USA", "bbl": "1010370040", "borough": "Manhattan" },
  "manhattan": { "buildings": 298, "apartments": 958418, "as_of": "2026-10-22" },
  "as_of": "2026-10-28",
  "caveats": ["Every number here is a rank against Manhattan, not a sound measurement.", "…"]
}`;

const READ_EXAMPLE = `curl -N -X POST $READER_URL/read \\
  -H 'content-type: application/json' \\
  -d '{"text": "Two-bedroom walk-up #3F, 310 West 47th Street ... third-floor ... facing 47th Street",
       "photos": ["data:image/jpeg;base64,..."],
       "answers": {"sleep_from": 23, "sleep_until": 7, "day_bothers": true, "bothers": ["traffic"]}}'

event: turn
data: {"n": 1, "by": "model", "tool": "read_photo", "args": {"indexes": [0]}, "ok": true, "ms": 1840}

event: turn
data: {"n": 2, "by": "model", "tool": "submit_listing", "ok": false,
       "result": {"error": "refused", "refused": {"side": "no line states it"}, "accepted": ["address", "floor"]}}

event: turn
data: {"n": 3, "by": "model", "tool": "submit_listing", "ok": true}

event: turn
data: {"n": 4, "by": "code", "tool": "locate", "ok": true}

event: turn
data: {"n": 5, "by": "code", "tool": "score", "ok": true,
       "result": {"engine": "v2", "verdict": "Very loud", "quieter_than": 8.7, "range": null}}

event: result
data: {"status": "complete", "fields": {...}, "position": "front", "observed": {...}, "score": {...}, "mode": "live"}`;

const FIELD_EXAMPLE = `"floor": {
  "value": 3,
  "status": "read",
  "evidence": [{ "source": "text", "quote": "third-floor", "start": 98, "end": 109 }]
},
"side": { "value": "unknown", "status": "cant_tell", "evidence": [] },
"ac_units": {
  "value": "through_wall",
  "status": "read",
  "evidence": [{ "source": "photo:2", "what": "a sleeve under the bedroom window" }]
}`;

const VERDICT_EXAMPLE = `{
  "evidence": [
    { "id": "E1", "kind": "verdict", "source": null,
      "text": "Verdict for you: Very loud, quieter than 9% of Manhattan apartments." },
    { "id": "E3", "kind": "rank", "source": "street",
      "text": "Street: Loud, quieter than 32% of Manhattan apartments for street noise." },
    { "id": "E4", "kind": "weight", "source": "street",
      "text": "Street weight: 47% of the verdict, counted three times because you said traffic bothers you." }
  ],
  "sentences": [
    { "text": "For the way you sleep, this apartment is very loud: quieter than 9% of Manhattan apartments.",
      "cites": ["E1"] },
    { "text": "You said traffic bothers you, so street noise counts for 47% of the verdict.",
      "cites": ["E4", "E3"] }
  ],
  "writer": "muse-spark-open",
  "trace": [{ "writer": "muse-spark-open", "attempt": 1, "ok": true, "ms": 2310 }]
}`;

function Status({ children, tone }: { children: string; tone: 'live' | 'v2' | 'next' }) {
  return <span className={`status ${tone}`}>{children}</span>;
}

export default function Docs() {
  return (
    <>
      <section className="page-hero">
        <div className="wrap">
          <p className="eyebrow">API</p>
          <h1 style={{ marginTop: 14 }}>Three calls: score, read, verdict</h1>
          <p className="lede">
            The score ranks an apartment against Manhattan from city data and the renter’s answers. The reader turns a listing into the facts the score needs,
            each with its line. The verdict writer explains the score in sentences that cite only the evidence it was sent.
          </p>
        </div>
      </section>

      <section className="section" style={{ paddingTop: 56 }}>
        <div className="wrap docs">
          <nav className="docs-toc" aria-label="On this page">
            <span className="h">Endpoints</span>
            <a href="#score">GET /v2/score</a>
            <a href="#read">POST /read</a>
            <a href="#verdict">POST /verdict</a>
            <span className="h">Notes</span>
            <a href="#rules">The rules every call keeps</a>
          </nav>

          <div>
            <article className="endpoint" id="score">
              <div className="endpoint-title">
                <span className="method">GET</span>
                <h2>/v2/score</h2>
                <Status tone="v2">Deploying with engine v2</Status>
              </div>
              <p>
                One apartment, one renter. Each source of noise is ranked against the same source across Manhattan, and the ranks are averaged with the renter’s
                weights. Every number in the response is a rank, a weight, a floor or a count. Base URL <code>https://hush-iq-api.vercel.app</code>, open CORS,
                no key today. <code>/v1/score</code> is live there now and stays live beside it.
              </p>
              <pre className="code">
                <code>{`curl 'https://hush-iq-api.vercel.app/v2/score?address=310+W+47th+St,+Manhattan&floor=3&position=front&sleep_from=23&sleep_until=7&day_bothers=true&bothers=traffic,sirens'`}</code>
              </pre>
              <h3>Query</h3>
              <div className="table-wrap">
                <table className="params">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Type</th>
                      <th>What it is</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr><td><code>address</code></td><td>string, required</td><td>Any NYC address GeoSearch can place. A borough helps.</td></tr>
                    <tr><td><code>floor</code></td><td>int 1 to 120</td><td>From the listing. Omit when it does not say: the score takes the building’s middle residential floor and adds a range.</td></tr>
                    <tr><td><code>position</code></td><td><code>front | rear | unknown</code></td><td>Street side or rear, from the listing. Default <code>unknown</code>, which adds a range.</td></tr>
                    <tr><td><code>sleep_from</code></td><td>int 0 to 23</td><td>The hour the renter falls asleep. Default 23.</td></tr>
                    <tr><td><code>sleep_until</code></td><td>int 0 to 23</td><td>The hour the renter wakes up. Default 7.</td></tr>
                    <tr><td><code>day_bothers</code></td><td>bool</td><td>Does noise during the day bother them. Default true; false halves an awake hour’s weight.</td></tr>
                    <tr><td><code>bothers</code></td><td>comma list</td><td>Any of <code>traffic, people, neighbors, sirens, construction</code>. Each counts three times. <code>people</code> is nightlife.</td></tr>
                    <tr><td><code>fresh</code></td><td>bool</td><td>Pull the city data again instead of the cache. A fresh pull takes 6 to 8 s; cached, under 1 s.</td></tr>
                  </tbody>
                </table>
              </div>
              <h3>Response</h3>
              <div className="table-wrap">
                <table className="params">
                  <thead>
                    <tr>
                      <th>Field</th>
                      <th>What it says</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr><td><code>verdict</code></td><td>Very loud, Loud, Typical, Quiet or Very quiet: one fifth of Manhattan each, after caps.</td></tr>
                    <tr><td><code>quieter_than</code></td><td>The share of Manhattan apartments this one is quieter than, for this renter.</td></tr>
                    <tr><td><code>caps</code></td><td>Each cap, the source that set it, why, and whether it changed the verdict (<code>applied</code>).</td></tr>
                    <tr><td><code>range</code></td><td>When the floor or side is unknown: <code>loudest_case</code> and <code>quietest_case</code>, each with its verdict, floor and side. Otherwise null.</td></tr>
                    <tr><td><code>ingredients[]</code></td><td>Per source: its rank (<code>quieter_than</code>), its own verdict word, its weight in percent, whether the renter ticked it, whether it is temporary, and the city-data lines behind it.</td></tr>
                    <tr><td><code>slot_weights</code></td><td>How much night, early morning and day count, in percent, from the sleep hours.</td></tr>
                    <tr><td><code>unit</code></td><td>The floor and side the score used, and whether each came from the listing or was expected.</td></tr>
                    <tr><td><code>manhattan</code></td><td>The sample every rank is against: buildings, the apartments they stand for, its date.</td></tr>
                  </tbody>
                </table>
              </div>
              <pre className="code">
                <code>{SCORE_EXAMPLE}</code>
              </pre>
              <p className="foot-note">A real response, trimmed. Errors: 422 for a bad query, 502 when a city dataset does not answer.</p>
            </article>

            <article className="endpoint" id="read">
              <div className="endpoint-title">
                <span className="method">POST</span>
                <h2>/read</h2>
                <Status tone="next">Built, not hosted yet</Status>
              </div>
              <p>
                The listing reader. Muse Spark reads the pasted text and the photos for facts about the unit, through tools that refuse any field without its
                evidence, then the service places the address and scores it. The response is a stream of server-sent events: one <code>turn</code> per step as
                it happens, then one <code>result</code>.
              </p>
              <h3>Request</h3>
              <div className="table-wrap">
                <table className="params">
                  <thead>
                    <tr>
                      <th>Field</th>
                      <th>Type</th>
                      <th>What it is</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr><td><code>text</code></td><td>string</td><td>The listing as pasted, up to 20,000 characters. May be empty when photos are sent.</td></tr>
                    <tr><td><code>photos</code></td><td>data URLs</td><td>Up to 12 images. Or send <code>multipart/form-data</code> with repeated <code>photos</code> files.</td></tr>
                    <tr><td><code>answers</code></td><td>object, optional</td><td>The three taps with the score’s names, so the score in the result is for this renter.</td></tr>
                  </tbody>
                </table>
              </div>
              <pre className="code">
                <code>{READ_EXAMPLE}</code>
              </pre>
              <p className="foot-note">An illustrative stream: the model’s first draft is refused for a side with no line, and the second passes.</p>
              <h3>Every field carries its evidence</h3>
              <p>
                Each of <code>address</code>, <code>unit</code>, <code>floor</code>, <code>side</code> and the observed <code>view</code>, <code>windows</code>,{' '}
                <code>ac_units</code>, <code>wall_material</code> is <code>{'{value, status, evidence}'}</code>. A text quote is exactly the span of the listing at
                its offsets; a photo citation names a photo the reader looked at. Read <code>status</code>, not <code>value</code>: “can’t tell” is an answer.
                Only the floor and the side reach the score today.
              </p>
              <pre className="code">
                <code>{FIELD_EXAMPLE}</code>
              </pre>
              <p className="foot-note">
                Full contract: <a href={`${REPO_URL}/blob/main/services/agent/CONTRACT.md`}>services/agent/CONTRACT.md</a>. With no Meta key the service runs a
                rule-based stand-in and says so with <code>"mode": "mock"</code>.
              </p>
            </article>

            <article className="endpoint" id="verdict">
              <div className="endpoint-title">
                <span className="method">POST</span>
                <h2>/verdict</h2>
                <Status tone="next">Built, not hosted yet</Status>
              </div>
              <p>
                The “what you’ll hear” paragraph for one renter. The service turns the score into numbered evidence lines, Muse Spark Open on Baseten writes
                sentences whose citations are limited to those ids, and code checks every sentence before it leaves: each cites a line it was sent, and every
                number, name and kind of source in it appears in the lines it cites. A draft that fails is retried once, then the template writes.
              </p>
              <pre className="code">
                <code>{`curl -X POST $VERDICT_URL/verdict -H 'content-type: application/json' \\
  -d '{"score": <a /v2/score response>, "answers": {...}, "fields": <the reader's fields>}'`}</code>
              </pre>
              <pre className="code">
                <code>{VERDICT_EXAMPLE}</code>
              </pre>
              <p className="foot-note">
                Illustrative and abridged. <code>writer</code> is <code>muse-spark-open</code>, <code>muse-spark-1.3</code> or <code>template</code>, and <code>trace</code> shows
                every attempt, so a fallback is never silent. Full contract:{' '}
                <a href={`${REPO_URL}/blob/main/services/verdict/CONTRACT.md`}>services/verdict/CONTRACT.md</a>.
              </p>
            </article>

            <article className="endpoint" id="rules">
              <div className="endpoint-title">
                <h2 style={{ fontFamily: 'var(--display)' }}>The rules every call keeps</h2>
              </div>
              <ul className="steps-list">
                <li>
                  <p><b>No decibels leave the engine.</b>Every number is a rank, a weight, a floor or a count. Ranks compare a source only with the same source elsewhere.</p>
                </li>
                <li>
                  <p><b>The model cannot invent a source.</b>Reader fields need a quoted line or a photo; verdict sentences may cite only the evidence ids they were sent. The checks run in code, inside the tools.</p>
                </li>
                <li>
                  <p><b>Silence is a range, not a guess.</b>A listing that does not give the floor or the side gets the expected value and both ends.</p>
                </li>
                <li>
                  <p><b>Answers set weights, never facts.</b>The renter is asked when they sleep and what gets to them, never the floor or the side.</p>
                </li>
              </ul>
            </article>
          </div>
        </div>
      </section>
    </>
  );
}
