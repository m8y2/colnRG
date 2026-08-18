import { useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { bandColorVar, bandGlyph, worstBand, latestBandNames } from '../lib/bands.js';

// Builds the popup content with DOM APIs (textContent, not innerHTML) since
// what3words addresses and other API-sourced text should be treated as
// untrusted when inserted into the page.
function buildPopupContent(location, worst) {
  const wrap = document.createElement('div');

  const heading = document.createElement('strong');
  heading.textContent = location.w3w;
  wrap.appendChild(heading);

  if (worst) {
    const bandLine = document.createElement('div');
    bandLine.style.marginTop = '4px';
    const glyph = document.createElement('span');
    glyph.setAttribute('aria-hidden', 'true');
    glyph.style.color = bandColorVar(worst);
    glyph.textContent = `${bandGlyph(worst)} `;
    bandLine.appendChild(glyph);
    bandLine.appendChild(document.createTextNode(`Worst current reading: ${worst} band`));
    wrap.appendChild(bandLine);
  } else {
    const none = document.createElement('div');
    none.style.marginTop = '4px';
    none.textContent = 'No readings yet';
    wrap.appendChild(none);
  }

  if (location.onOpen) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn btn-secondary btn-sm';
    btn.style.marginTop = '8px';
    btn.textContent = 'See this place';
    btn.addEventListener('click', () => location.onOpen(location.w3w));
    wrap.appendChild(btn);
  }

  return wrap;
}

/**
 * A Leaflet map of sampling locations, each marker coloured by its worst
 * (most severe) current WFD band across the banded parameters, and
 * labelled with its what3words address — not a volunteer-initials code,
 * see V2_SPEC_ADDENDUM.md Change 3. This is a primary view: it is how a
 * non-technical reader finds their bit of the river, so it always renders
 * alongside an accessible text list carrying the same information (see
 * `LocationList`) — a map alone is not accessible.
 *
 * `locations`: [{ w3w, latitude, longitude, bands: {parameter: band|null}, onOpen? }]
 */
export default function LocationMap({ locations, onSelectLocation, selected }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const layerRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, {
      scrollWheelZoom: false,
      attributionControl: true,
    });
    mapRef.current = map;
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 18,
    }).addTo(map);
    layerRef.current = L.layerGroup().addTo(map);

    return () => {
      map.remove();
      mapRef.current = null;
      layerRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    const layer = layerRef.current;
    if (!map || !layer) return;
    layer.clearLayers();

    const bounds = [];
    for (const location of locations || []) {
      if (location.latitude == null || location.longitude == null) continue;
      const worst = worstBand(latestBandNames(location));
      const isSelected = selected && selected === location.w3w;
      const icon = L.divIcon({
        className: `location-marker${isSelected ? ' location-marker--selected' : ''}`,
        html: `<span class="location-marker__dot" style="background:${worst ? bandColorVar(worst) : 'var(--text-muted)'}"></span>`,
        iconSize: [18, 18],
        iconAnchor: [9, 9],
        popupAnchor: [0, -9],
      });
      const marker = L.marker([location.latitude, location.longitude], { icon, keyboard: true });
      marker.bindPopup(buildPopupContent({ ...location, onOpen: onSelectLocation }, worst));
      if (onSelectLocation) marker.on('click', () => onSelectLocation(location.w3w));
      marker.addTo(layer);
      const el = marker.getElement();
      if (el) {
        el.setAttribute('role', 'button');
        el.setAttribute('aria-label', `${location.w3w}${worst ? ` — ${worst} band` : ' — no readings yet'}`);
      }
      bounds.push([location.latitude, location.longitude]);
    }
    if (bounds.length) {
      map.fitBounds(bounds, { padding: [28, 28] });
    }
  }, [locations, onSelectLocation, selected]);

  return (
    <div>
      <div
        ref={containerRef}
        className="site-map"
        aria-label="Map of River Coln sampling locations, coloured by their most recent water quality band"
      />
      <p className="precision-note">
        Locations are what3words addresses — 3-metre squares recorded by volunteers standing on the riverbank. They mark
        roughly the right spot, not survey-grade positions.
      </p>
    </div>
  );
}
