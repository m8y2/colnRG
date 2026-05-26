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
              src={p.photo_url}
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
          <div className="photo-overlay-content" onClick={(e) => e.stopPropagation()}>
            <button className="photo-close" onClick={() => setSelected(null)}>✕</button>
            <img src={selected.photo_url} alt={selected.photo_desc || "Photo"} />
            <div className="photo-overlay-info">
              <p><strong>Site:</strong> {selected.w3w_site_code || "—"}</p>
              <p><strong>Date:</strong> {selected.sample_date}</p>
              <p><strong>Location:</strong> {selected.w3w || "—"}</p>
              {selected.photo_desc && <p><strong>Description:</strong> {selected.photo_desc}</p>}
              {selected.photo_2_url && (
                <div className="photo-secondary">
                  <p><strong>Second photo:</strong></p>
                  <img src={selected.photo_2_url} alt="Second photo" />
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
