import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { getSiteSummary } from "../api";

const summaryCache = {};

const POPUP_STYLE = {
  maxHeight: 260,
  overflowY: "auto",
};

function buildPopupHtml(site) {
  return `
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;min-width:180px">
      <strong style="font-size:0.95rem">${site.code} — ${site.name}</strong>
      <div id="summary-${site.code}" style="margin-top:8px;font-size:0.8rem;color:#4b5563">Loading…</div>
    </div>
  `;
}

async function attachSummary(popup, code) {
  const el = document.getElementById(`summary-${code}`);
  if (!el) return;
  try {
    const cached = summaryCache[code];
    const data = cached || await getSiteSummary(code);
    if (!cached) summaryCache[code] = data;
    const chems = data.chemicals;
    if (Object.keys(chems).length === 0) {
      el.innerHTML = '<span style="color:#6b7280">No chemical data.</span>';
      return;
    }
    let html = '<table style="width:100%;border-collapse:collapse;font-size:0.8rem">';
    html += '<tr style="color:#4b5563;border-bottom:1px solid #e5e7eb"><th style="text-align:left;padding:2px 6px">Chemical</th><th style="text-align:right;padding:2px 6px">Mean</th><th style="text-align:right;padding:2px 6px">Max</th></tr>';
    for (const [chem, info] of Object.entries(chems)) {
      html += `<tr style="border-bottom:1px solid #f3f4f6"><td style="padding:2px 6px;font-weight:500">${chem}</td><td style="padding:2px 6px;text-align:right">${info.mean}</td><td style="padding:2px 6px;text-align:right">${info.max}</td></tr>`;
    }
    html += '</table>';
    el.innerHTML = html;
  } catch {
    el.innerHTML = '<span style="color:#dc2626">Error loading data.</span>';
  }
}

const ICON = L.divIcon({
  className: "",
  html: '<div style="background:#1a56db;color:#fff;border-radius:50%;width:28px;height:28px;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,0.3)">📍</div>',
  iconSize: [28, 28],
  iconAnchor: [14, 14],
});

export default function SiteMap({ sites }) {
  const mapRef = useRef(null);
  const mapInstance = useRef(null);
  const labelsLayer = useRef(null);
  const [showLabels, setShowLabels] = useState(false);

  useEffect(() => {
    if (mapInstance.current) return;

    const map = L.map(mapRef.current, {
      center: [51.71, -1.9],
      zoom: 11,
      scrollWheelZoom: true,
    });

    L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
      attribution: "&copy; <a href='https://www.openstreetmap.org/copyright'>OSM</a> &copy; <a href='https://carto.com'>CARTO</a>",
      maxZoom: 18,
    }).addTo(map);

    const group = L.layerGroup();
    labelsLayer.current = group;

    const hasCoord = sites.filter((s) => s.coordinates);
    if (hasCoord.length === 0) {
      map.setView([51.71, -1.9], 10);
      return;
    }

    const bounds = [];
    for (const site of hasCoord) {
      const [lat, lng] = site.coordinates;
      bounds.push([lat, lng]);

      const marker = L.marker([lat, lng], { icon: ICON }).addTo(map);
      const popup = L.popup({ maxHeight: 260, className: "site-popup" }).setContent(buildPopupHtml(site));
      marker.bindPopup(popup);
      marker.on("popupopen", () => attachSummary(popup, site.code));

      const lblLat = lat;
      const lblLng = lng + 0.008;
      const callout = L.polyline([[lat, lng], [lblLat, lblLng]], {
        color: "#6b7280",
        weight: 1.5,
        dashArray: "3 3",
        opacity: 0.7,
      });
      group.addLayer(callout);

      const lbl = L.marker([lblLat, lblLng], {
        icon: L.divIcon({
          className: "",
          html: `<div style="display:inline-block;white-space:nowrap;font-size:11px;font-weight:600;color:#1a56db;background:rgba(255,255,255,0.92);padding:2px 7px;border-radius:4px;border:1px solid #d1d5db;box-shadow:0 1px 3px rgba(0,0,0,0.1)">${site.code} — ${site.name}</div>`,
          iconSize: [0, 0],
          iconAnchor: [0, 14],
        }),
        interactive: false,
      });
      group.addLayer(lbl);
    }

    map.fitBounds(bounds, { padding: [8, 8] });
    mapInstance.current = map;

    return () => {
      map.remove();
      mapInstance.current = null;
    };
  }, [sites]);

  useEffect(() => {
    const group = labelsLayer.current;
    if (!group) return;
    if (showLabels) {
      group.addTo(mapInstance.current);
    } else {
      mapInstance.current?.removeLayer(group);
    }
  }, [showLabels]);

  return (
    <div className="table-section">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <h2 className="chart-section-heading" style={{ margin: 0, marginBottom: 0 }}>Sampling Sites ({sites.length})</h2>
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "0.85rem", color: "#374151", cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={showLabels}
            onChange={(e) => setShowLabels(e.target.checked)}
          />
          Show site names
        </label>
      </div>
      <div ref={mapRef} style={{ height: 500, width: "100%", borderRadius: 8 }} />
    </div>
  );
}
