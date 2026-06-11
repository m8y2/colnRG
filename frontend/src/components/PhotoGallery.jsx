import { useState, useEffect } from "react";
import { getPhotos } from "../api";

export default function PhotoGallery() {
  const [photos, setPhotos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [hidden, setHidden] = useState(new Set());

  useEffect(() => {
    getPhotos().then((result) => {
      setPhotos(result.photos || []);
      setLoading(false);
    });
  }, []);

  const handleError = (url) => {
    setHidden((prev) => new Set(prev).add(url));
  };

  const handleSelect = (p) => {
    setSelected((prev) => (prev?.ec5_uuid === p.ec5_uuid ? null : p));
  };

  const visible = photos.filter(
    (p) =>
      !hidden.has(p.photo_url) &&
      (!p.photo_2_url || !hidden.has(p.photo_2_url))
  );

  if (loading) return <div className="loading">Loading photos...</div>;

  if (visible.length === 0)
    return <div className="loading">No photos found.</div>;

  return (
    <div>
      <h2 className="chart-section-heading">
        Photo Gallery ({photos.length} entries with photos)
      </h2>
      <div className="photo-grid">
        {visible.map((p) => {
          const isOpen = selected?.ec5_uuid === p.ec5_uuid;
          const src = p.photo_url || p.photo_2_url;
          return (
            <div key={p.ec5_uuid} className={`photo-tile${isOpen ? " photo-tile-open" : ""}`} onClick={() => handleSelect(p)}>
              {!hidden.has(src) && (
                <img
                  src={src}
                  alt={p.photo_desc || "Photo"}
                  loading="lazy"
                  onError={() => handleError(src)}
                />
              )}
              <div className="photo-tile-info">
                {p.w3w_site_code && <span>{p.w3w_site_code}</span>}
                <span>{p.sample_date}</span>
              </div>
              {isOpen && (
                <div className="photo-tile-detail">
                  {p.w3w_site_code && <span className="photo-meta-tag">{p.w3w_site_code}</span>}
                  <span className="photo-meta-date">{p.sample_date}</span>
                  {p.w3w && <span className="photo-meta-location">{p.w3w}</span>}
                  {p.photo_desc && <p className="photo-meta-desc">{p.photo_desc}</p>}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
