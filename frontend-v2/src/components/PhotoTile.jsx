import { useEffect, useRef, useState } from 'react';
import { formatDate } from '../lib/format.js';

// A single photo tile, used by the whole-river Photo gallery page and by
// the photos section of a location's page ("Your place") — the same
// format everywhere, so photos always behave the same way.
//
// Photos load from the backend's media endpoint, which serves the
// full-resolution image auto-cropped of letterbox bars. If that endpoint
// is unreachable (the offline demo has no backend), the tile falls back
// to the EpiCollect original.
//
// The image is only fetched once the tile comes near the viewport
// (IntersectionObserver, 600px lookahead), so a page full of tiles stays
// quick. A photo that fails to load is tried again every second until it
// loads — EpiCollect rate-limits and occasionally stalls, but the photos
// do come through. The tile is a real button (keyboard and screen-reader
// usable).
//
// Choosing a tile mutes the photo and overlays, within the same frame,
// the notes the volunteer left and a "See this spot" button (where a
// spot page exists to go to — a location page already on the spot passes
// no `navigate` and shows the notes only). Choosing it again closes the
// overlay.
//
// `navigate` is optional: the gallery passes it so the overlay can link
// through to the spot's own page; a location page passes nothing. A
// location page also passes `overlay={false}` — the full-screen lightbox
// (PhotoLightbox) takes over there, so the tile's own in-frame overlay
// never shows, while `open` still drives aria-expanded.
export default function PhotoTile({ photo, open, onToggle, navigate, overlay = true }) {
  // Where the browser has no IntersectionObserver the image just loads
  // immediately; where it does, `near` flips when the tile approaches the
  // viewport and the full-resolution photo is fetched only then.
  const [near, setNear] = useState(() => !('IntersectionObserver' in window));
  const [ok, setOk] = useState(true);
  const [tries, setTries] = useState(0);
  const [onOriginal, setOnOriginal] = useState(false);
  const tileRef = useRef(null);

  // The cropped media endpoint first, the EpiCollect original as the
  // fallback (the offline demo has no backend to crop through).
  const src = onOriginal ? (photo.original_url || photo.url) : photo.url;

  useEffect(() => {
    const el = tileRef.current;
    if (!el || near) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setNear(true);
          observer.disconnect();
        }
      },
      { rootMargin: '600px 0px' }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [near]);

  // Auto-retry: a failed photo is re-attempted every second (remounting
  // the <img> with a new key forces a fresh fetch) until one succeeds.
  useEffect(() => {
    if (!near || ok) return undefined;
    const timer = setInterval(() => setTries((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, [near, ok]);

  const handleError = () => {
    if (!onOriginal && photo.original_url) {
      setOnOriginal(true);
    } else {
      setOk(false);
    }
  };

  return (
    <li ref={tileRef} className={`photo-tile${open ? ' photo-tile--open' : ''}`}>
      <span className="photo-tile__imgwrap">
        {near ? (
          <button
            type="button"
            className="photo-tile__button"
            aria-expanded={open}
            onClick={onToggle}
          >
            {ok ? (
              <img
                key={tries}
                className="photo-tile__img"
                src={src}
                alt={photo.description || `Photo taken at ${photo.w3w}`}
                decoding="async"
                onLoad={() => setOk(true)}
                onError={handleError}
              />
            ) : (
              <span className="photo-tile__img photo-tile__placeholder">
                Trying to load this photo…
              </span>
            )}
            {!ok && (
              <img
                key={tries}
                src={src}
                alt=""
                aria-hidden="true"
                style={{ display: 'none' }}
                onLoad={() => setOk(true)}
                onError={handleError}
              />
            )}
          </button>
        ) : (
          <span className="photo-tile__img photo-tile__placeholder">
            Loading photo…
          </span>
        )}
        {overlay !== false && open && (
          <span className="photo-tile__overlay" onClick={onToggle}>
            {photo.description && <p className="photo-tile__notes">{photo.description}</p>}
            {navigate && (
              <button
                type="button"
                className="btn btn--primary"
                onClick={(e) => {
                  e.stopPropagation();
                  navigate(`your-place/${encodeURIComponent(photo.w3w)}`);
                }}
              >
                See this spot
              </button>
            )}
          </span>
        )}
      </span>
      <span className="photo-tile__meta">
        <span className="photo-tile__w3w">{photo.w3w}</span>
        <span className="photo-tile__date">{formatDate(photo.date)}</span>
      </span>
    </li>
  );
}