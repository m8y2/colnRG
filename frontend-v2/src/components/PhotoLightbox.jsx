import { useEffect, useRef } from 'react';
import { formatDate } from '../lib/format.js';

// Full-screen photo viewer, used by the "Your place" page: choosing a
// photo expands it to fill the screen, with the location and date at the
// top and the volunteer's words at the bottom. Esc, the close button or
// a click on the backdrop closes it. The photo itself is shown at full
// resolution (the same URL the tile already fetched, so it comes from
// the browser cache).

export default function PhotoLightbox({ photo, onClose }) {
  const closeRef = useRef(null);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    closeRef.current?.focus();
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
    };
  }, [onClose]);

  return (
    <div
      className="lightbox"
      role="dialog"
      aria-modal="true"
      aria-label={`Photo taken at ${photo.w3w}`}
      onClick={onClose}
    >
      <div className="lightbox__top" onClick={(e) => e.stopPropagation()}>
        <span className="lightbox__w3w">{photo.w3w}</span>
        <span className="lightbox__date">{formatDate(photo.date)}</span>
        <button
          ref={closeRef}
          type="button"
          className="btn btn-secondary btn-sm lightbox__close"
          onClick={onClose}
        >
          Close
        </button>
      </div>
      <img
        className="lightbox__img"
        src={photo.url}
        alt={photo.description || `Photo taken at ${photo.w3w}`}
        onClick={(e) => e.stopPropagation()}
      />
      {photo.description && (
        <div className="lightbox__bottom" onClick={(e) => e.stopPropagation()}>
          <p>{photo.description}</p>
        </div>
      )}
    </div>
  );
}