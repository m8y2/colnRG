import { useState, useEffect, useRef } from "react";
import { getPhotos } from "../api";

export default function PhotoGallery() {
  const [photos, setPhotos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [photoY, setPhotoY] = useState(0);
  const overlayRef = useRef(null);

  useEffect(() => {
    getPhotos().then((result) => {
      setPhotos(result.photos || []);
      setLoading(false);
    });
  }, []);

  const handleSelect = (p, e) => {
    const tile = e.currentTarget;
    const rect = tile.getBoundingClientRect();
    setPhotoY(rect.top + rect.height / 2);
    setSelected(p);
  };

  useEffect(() => {
    if (selected && overlayRef.current) {
      overlayRef.current.scrollTop = 0;
    }
  }, [selected]);

  if (loading) return <div className="loading">Loading photos...</div>;

  if (photos.length === 0)
    return <div className="loading">No photos found.</div>;

  return (
    <div>
      <h2 className="chart-section-heading">
        Photo Gallery ({photos.length} entries with photos)
      </h2>
      <div className="photo-grid">
        {photos.map((p) => (
          <div key={p.ec5_uuid} className="photo-tile" onClick={(e) => handleSelect(p, e)}>
            <img
              src={p.photo_url || p.photo_2_url}
              alt={p.photo_desc || "Photo"}
              loading="lazy"
            />
            <div className="photo-tile-info">
              {p.w3w_site_code && <span>{p.w3w_site_code}</span>}
              <span>{p.sample_date}</span>
            </div>
          </div>
        ))}
      </div>

      {selected && (
        <div className="photo-overlay" ref={overlayRef}>
          <div className="photo-overlay-inner" style={{ paddingTop: Math.max(0, photoY - 100) }}>
            <div className="photo-overlay-top">
              <div className="photo-overlay-meta">
                {selected.w3w_site_code && <span className="photo-meta-tag">{selected.w3w_site_code}</span>}
                <span className="photo-meta-date">{selected.sample_date}</span>
                {selected.w3w && <span className="photo-meta-location">{selected.w3w}</span>}
                {selected.photo_desc && <span className="photo-meta-desc">{selected.photo_desc}</span>}
              </div>
              <button className="photo-close" onClick={() => setSelected(null)}>✕</button>
            </div>
            <img
              className="photo-overlay-img"
              src={selected.photo_url || selected.photo_2_url}
              alt={selected.photo_desc || "Photo"}
            />
          </div>
        </div>
      )}
    </div>
  );
}
