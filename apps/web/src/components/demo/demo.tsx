'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { checkCitations, read, score as scoreFor, services as currentServices, verdict as writeVerdict } from '@/lib/client';
import { SAMPLES } from '@/lib/mock/listings';
import type { Answers, ReaderResult, ReaderTurn, Score, Services, Verdict } from '@/lib/types';
import { DEFAULT_ANSWERS } from '@/lib/words';

import { ListingInput, type Photo } from './listing-input';
import { ReaderPanel } from './reader-panel';
import { Result } from './result';
import { Taps } from './taps';

type Phase = 'idle' | 'reading' | 'scoring' | 'asking' | 'done' | 'error';

/**
 * The demo: paste a listing, answer three taps, watch the reader, get the verdict. Changing an answer after a
 * result re-scores and re-writes at once, without reading the listing again.
 */
export function Demo() {
  const [text, setText] = useState('');
  const [sampleId, setSampleId] = useState<string | null>(null);
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [answers, setAnswers] = useState<Answers>(DEFAULT_ANSWERS);
  const [phase, setPhase] = useState<Phase>('idle');
  const [turns, setTurns] = useState<ReaderTurn[]>([]);
  const [reading, setReading] = useState<ReaderResult | null>(null);
  const [address, setAddress] = useState<string | null>(null);
  const [score, setScore] = useState<Score | null>(null);
  const [verdict, setVerdict] = useState<{ verdict: Verdict; dropped: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updating, setUpdating] = useState(false);
  const [svc, setSvc] = useState<Services>({ reader: 'mock', verdict: 'mock', score: 'v2' });
  const run = useRef<AbortController | null>(null);
  const answersRef = useRef(answers);
  answersRef.current = answers;

  useEffect(() => setSvc(currentServices()), []);

  /** Score what was read for these answers, then have the writer explain it. */
  const finish = useCallback(async (r: ReaderResult, a: Answers, addr: string | null, signal: AbortSignal) => {
    const s = await scoreFor(r, a, addr ?? undefined, signal);
    if (signal.aborted) return;
    setScore(s);
    setSvc(currentServices());
    setVerdict(null);
    const v = await writeVerdict({ score: s, answers: a, fields: r.fields }, signal);
    if (signal.aborted) return;
    setVerdict(checkCitations(v));
  }, []);

  async function start() {
    run.current?.abort();
    const ctl = new AbortController();
    run.current = ctl;
    setPhase('reading');
    setTurns([]);
    setReading(null);
    setAddress(null);
    setScore(null);
    setVerdict(null);
    setError(null);
    try {
      const r = await read({ text, photos: photos.map((p) => p.url), answers }, (t) => setTurns((prev) => [...prev, t]), ctl.signal);
      if (ctl.signal.aborted) return;
      setReading(r);
      if (!r.score && !r.fields.address.value) {
        setPhase('asking');
        return;
      }
      setPhase('scoring');
      await finish(r, answersRef.current, null, ctl.signal);
      if (!ctl.signal.aborted) {
        setPhase('done');
        requestAnimationFrame(() => document.getElementById('verdict')?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
      }
    } catch (e) {
      if ((e as Error).name === 'AbortError') return;
      setError((e as Error).message || 'Something went wrong.');
      setPhase('error');
    }
  }

  async function scoreAddress(addr: string) {
    if (!reading) return;
    run.current?.abort();
    const ctl = new AbortController();
    run.current = ctl;
    setAddress(addr);
    setError(null);
    setPhase('scoring');
    try {
      await finish(reading, answersRef.current, addr, ctl.signal);
      if (!ctl.signal.aborted) setPhase('done');
    } catch (e) {
      if ((e as Error).name === 'AbortError') return;
      setError((e as Error).message);
      setPhase('asking');
    }
  }

  // A changed answer after a result: re-score and re-write, debounced, without reading again.
  useEffect(() => {
    if (phase !== 'done' || !reading) return;
    const ctl = new AbortController();
    const t = setTimeout(async () => {
      run.current?.abort();
      run.current = ctl;
      setUpdating(true);
      try {
        await finish(reading, answers, address, ctl.signal);
      } catch (e) {
        if ((e as Error).name !== 'AbortError') setError((e as Error).message);
      } finally {
        if (!ctl.signal.aborted) setUpdating(false);
      }
    }, 280);
    return () => {
      clearTimeout(t);
      ctl.abort();
    };
    // Only answers re-trigger this; the rest is read when it fires.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [answers]);

  const busy = phase === 'reading' || phase === 'scoring';
  const pickSample = (id: string) => {
    const s = SAMPLES.find((x) => x.id === id);
    if (!s) return;
    setText(s.text);
    setSampleId(id);
  };

  return (
    <>
      <div className="demo-grid">
        <div className="demo-inputs">
          <ListingInput
            text={text}
            photos={photos}
            sampleId={sampleId}
            onText={(t) => {
              setText(t);
              setSampleId(SAMPLES.find((s) => s.text === t)?.id ?? null);
            }}
            onSample={pickSample}
            onPhotos={setPhotos}
          />
          <Taps answers={answers} onChange={setAnswers} />
          <button type="button" className="btn block" disabled={busy || text.trim().length < 12} onClick={start}>
            {busy ? 'Reading…' : phase === 'done' ? 'Read it again' : 'Read the listing'}
          </button>
        </div>
        <ReaderPanel
          turns={turns}
          working={busy}
          workingLabel={phase === 'scoring' ? 'Writing the verdict…' : turns.length > 6 ? 'Scoring the building…' : 'Reading…'}
          services={svc}
          asking={phase === 'asking'}
          error={error}
          onAddress={scoreAddress}
        />
      </div>
      {score && reading ? (
        <Result
          score={score}
          verdict={verdict?.verdict ?? null}
          dropped={verdict?.dropped ?? 0}
          fields={reading.fields}
          observed={reading.observed}
          answers={answers}
          services={svc}
          updating={updating}
        />
      ) : null}
    </>
  );
}
