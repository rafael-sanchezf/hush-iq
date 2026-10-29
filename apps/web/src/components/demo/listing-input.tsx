'use client';

import { useRef, useState } from 'react';

import { SAMPLES } from '@/lib/mock/listings';
import { MAX_PHOTOS, toDataUrl } from '@/lib/photos';

export interface Photo {
  name: string;
  url: string;
}

interface Props {
  text: string;
  photos: Photo[];
  sampleId: string | null;
  onText: (text: string) => void;
  onSample: (id: string) => void;
  onPhotos: (photos: Photo[]) => void;
}

/** Step one: the listing as the renter found it. Pasted text and photos; nothing is fetched from a listing site. */
export function ListingInput({ text, photos, sampleId, onText, onSample, onPhotos }: Props) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function add(files: FileList | File[]) {
    const images = [...files].filter((f) => f.type.startsWith('image/'));
    const room = MAX_PHOTOS - photos.length;
    if (!images.length) return;
    setNote(images.length > room ? `Up to ${MAX_PHOTOS} photos; the first ${Math.max(room, 0)} were added.` : null);
    const added: Photo[] = [];
    for (const f of images.slice(0, Math.max(room, 0))) {
      try {
        added.push({ name: f.name, url: await toDataUrl(f) });
      } catch {
        setNote(`Could not open ${f.name}.`);
      }
    }
    onPhotos([...photos, ...added]);
  }

  return (
    <div className="card">
      <div className="step-label">
        <span className="n">1</span>
        <h3>The listing</h3>
      </div>
      <label htmlFor="listing" className="sr-only">
        Paste the listing text
      </label>
      <textarea
        id="listing"
        className="listing-text"
        value={text}
        onChange={(e) => onText(e.target.value)}
        placeholder="Paste the listing: the address, the description, anything it says about the unit."
        spellCheck={false}
      />
      <div className="samples" role="group" aria-label="Sample listings">
        {SAMPLES.map((s) => (
          <button key={s.id} type="button" className="sample" aria-pressed={sampleId === s.id} onClick={() => onSample(s.id)}>
            <b>{s.title}</b>
            <span>{s.shows}</span>
          </button>
        ))}
      </div>
      <div
        className={`drop${over ? ' over' : ''}`}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          void add(e.dataTransfer.files);
        }}
      >
        <span aria-hidden="true" style={{ fontSize: 20 }}>⌗</span>
        <span>
          Drop the listing’s photos here, or{' '}
          <button type="button" onClick={() => fileRef.current?.click()}>
            choose them
          </button>
          .
        </span>
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          multiple
          hidden
          onChange={(e) => {
            if (e.target.files) void add(e.target.files);
            e.target.value = '';
          }}
        />
      </div>
      {photos.length ? (
        <div className="thumbs">
          {photos.map((p, i) => (
            <div className="thumb" key={`${p.name}-${i}`}>
              <img src={p.url} alt={`Photo ${i + 1}: ${p.name}`} />
              <small>{i + 1}</small>
              <button type="button" aria-label={`Remove photo ${i + 1}`} onClick={() => onPhotos(photos.filter((_, j) => j !== i))}>
                ×
              </button>
            </div>
          ))}
        </div>
      ) : null}
      {note ? <p className="chip-hint">{note}</p> : null}
    </div>
  );
}
