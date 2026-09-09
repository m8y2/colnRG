import { useState } from 'react';
import { useApi } from '../lib/useApi.js';
import * as api from '../lib/api.js';
import { LoadingState, ErrorState, EmptyState } from '../components/AsyncState.jsx';
import PhotoTile from '../components/PhotoTile.jsx';

// The whole-river photo gallery: every photo a volunteer attached to a
// sample, newest first, like v1's gallery tab. All photos are listed
// automatically (no paging or "show more"); each tile is the shared
// PhotoTile component — the same format used on a location's own page,
// just not filtered to one spot. See PhotoTile.jsx for the lazy-loading
// and auto-retry behaviour.

export default function PhotoGallery({ navigate }) {
  const { status, data, error, reload } = useApi(() => api.getPhotos(), []);
  const [openSet, setOpenSet] = useState(() => new Set());

  const photos = data?.photos || [];
  const allOpen = photos.length > 0 && openSet.size === photos.length;

  const toggle = (photo) => {
    setOpenSet((prev) => {
      const next = new Set(prev);
      if (next.has(photo.url)) {
        next.delete(photo.url);
      } else {
        next.add(photo.url);
      }
      return next;
    });
  };

  const toggleAll = () => {
    setOpenSet(allOpen ? new Set() : new Set(photos.map((p) => p.url)));
  };

  return (
    <div className="stack">
      <div className="page-header page-header--row">
        <div>
          <h1>Photo gallery</h1>
          <p className="lead">
            Photos taken at sampling points, newest first. Choose one to see
            where it was taken and any words the volunteer left with it.
          </p>
        </div>
        {status === 'ready' && photos.length > 0 && (
          <button type="button" className="btn" onClick={toggleAll}>
            {allOpen ? 'Hide descriptions' : 'Show all descriptions'}
          </button>
        )}
      </div>

      {status === 'loading' && <LoadingState label="Loading photos…" />}
      {status === 'error' && <ErrorState message={error} onRetry={reload} />}
      {status === 'ready' && photos.length === 0 && (
        <EmptyState message="No photos yet." />
      )}

      {status === 'ready' && photos.length > 0 && (
        <ul className="photo-grid" aria-label="Photos from sampling points">
          {photos.map((photo) => (
            <PhotoTile
              key={photo.url}
              photo={photo}
              open={openSet.has(photo.url)}
              onToggle={() => toggle(photo)}
              navigate={navigate}
            />
          ))}
        </ul>
      )}
    </div>
  );
}