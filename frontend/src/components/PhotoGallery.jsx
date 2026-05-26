import { useState, useEffect } from "react";
import { getPhotos } from "../api";

export default function PhotoGallery() {
  const [photos, setPhotos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    getPhotos().then((result) => {
      setPhotos(result.photos || []);
      setLoading(false);
    });
  }, []);

  useEffect(() => {
    if (selected) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => { document.body.style.overflow = ""; };
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
          <div key={p.ec5_uuid} className="photo-tile" onClick={() => setSelected(p)}>
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
        <div className="photo-overlay" onClick={() => setSelected(null)}>
          <button className="photo-close" onClick={() => setSelected(null)}>✕</button>
          <img
            className="photo-overlay-img"
            src={selected.photo_url || selected.photo_2_url}
            alt={selected.photo_desc || "Photo"}
            onClick={(e) => e.stopPropagation()}
          />
          <div className="photo-overlay-info" onClick={(e) => e.stopPropagation()}>
            <p><strong>{selected.w3w_site_code || "—"}</strong> · {selected.sample_date}</p>
            {selected.w3w && <p className="photo-overlay-w3w">{selected.w3w}</p>}
            {selected.photo_desc && <p>{selected.photo_desc}</p>}
            {selected.photo_2_url && (
              <span className="photo-has-second">📷 2 photos</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
