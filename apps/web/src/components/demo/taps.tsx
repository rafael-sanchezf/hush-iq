'use client';

import type { Answers, Bother } from '@/lib/types';
import { BOTHERS } from '@/lib/types';
import { BOTHER_WORDS, hourLabel, hoursAsleep } from '@/lib/words';

const HOURS = Array.from({ length: 24 }, (_, h) => h);
// The strip runs noon to noon so a night's sleep reads as one block.
const STRIP = Array.from({ length: 24 }, (_, i) => (i + 12) % 24);

function asleep(h: number, from: number, until: number): boolean {
  if (from === until) return false;
  return from > until ? h >= from || h < until : from <= h && h < until;
}

/** The three taps: sleep hours, daytime noise, what gets to you. They set the weights, never the facts. */
export function Taps({ answers, onChange }: { answers: Answers; onChange: (a: Answers) => void }) {
  const set = (patch: Partial<Answers>) => onChange({ ...answers, ...patch });
  const toggle = (b: Bother) =>
    set({ bothers: answers.bothers.includes(b) ? answers.bothers.filter((x) => x !== b) : BOTHERS.filter((x) => x === b || answers.bothers.includes(x)) });
  const n = hoursAsleep(answers);

  return (
    <div className="card">
      <div className="step-label">
        <span className="n">2</span>
        <h3>You, in three taps</h3>
      </div>

      <div className="q">
        <div className="q-title">
          <span>When do you sleep?</span>
          <small>{n} hour{n === 1 ? '' : 's'} asleep</small>
        </div>
        <div className="sleep-pickers">
          <label className="select">
            <span>Asleep from</span>
            <select value={answers.sleep_from} onChange={(e) => set({ sleep_from: Number(e.target.value) })}>
              {HOURS.map((h) => (
                <option key={h} value={h}>{hourLabel(h)}</option>
              ))}
            </select>
          </label>
          <label className="select">
            <span>Until</span>
            <select value={answers.sleep_until} onChange={(e) => set({ sleep_until: Number(e.target.value) })}>
              {HOURS.map((h) => (
                <option key={h} value={h}>{hourLabel(h)}</option>
              ))}
            </select>
          </label>
        </div>
        <div className="clock" aria-hidden="true">
          {STRIP.map((h) => (
            <i key={h} className={asleep(h, answers.sleep_from, answers.sleep_until) ? 'asleep' : undefined} />
          ))}
        </div>
        <div className="clock-labels" aria-hidden="true">
          <span>noon</span>
          <span>6 pm</span>
          <span>midnight</span>
          <span>6 am</span>
          <span>noon</span>
        </div>
      </div>

      <div className="q">
        <div className="q-title">
          <span id="q-day">Does noise during the day bother you?</span>
        </div>
        <div className="seg" role="group" aria-labelledby="q-day">
          <button type="button" aria-pressed={answers.day_bothers} onClick={() => set({ day_bothers: true })}>
            Yes, I’m home
          </button>
          <button type="button" aria-pressed={!answers.day_bothers} onClick={() => set({ day_bothers: false })}>
            Not really
          </button>
        </div>
      </div>

      <div className="q">
        <div className="q-title">
          <span id="q-bothers">What gets to you?</span>
          <small>{answers.bothers.length ? `${answers.bothers.length} ticked` : 'Tick any'}</small>
        </div>
        <div className="chips" role="group" aria-labelledby="q-bothers">
          {BOTHERS.map((b) => (
            <button
              key={b}
              type="button"
              className="chip"
              aria-pressed={answers.bothers.includes(b)}
              onClick={() => toggle(b)}
              title={BOTHER_WORDS[b].hint}
            >
              {BOTHER_WORDS[b].label}
            </button>
          ))}
        </div>
        <p className="chip-hint">Each one you tick counts three times as much. Local businesses covers bars, restaurants, theatres and crowds.</p>
      </div>
    </div>
  );
}
