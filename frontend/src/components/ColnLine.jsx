import { useState, useRef } from "react";
import { getSiteSummary } from "../api";

const SITES = [
  { code: "EP", name: "Ewen/Preston" },
  { code: "PW", name: "Poole Keynes" },
  { code: "SJR", name: "Sid/Jacks/River" },
  { code: "MG", name: "Milton Garth" },
  { code: "NL", name: "New Mills Lat" },
  { code: "ST/LAT", name: "Stratton/Latten" },
  { code: "CS", name: "Cirencester/Sidd" },
  { code: "WMW", name: "Winson/Meadow/Whelford" },
  { code: "GED", name: "Gravelly End D" },
  { code: "DFG", name: "Dunfields Farm G" },
  { code: "GDR", name: "Gravelly Ditch R" },
  { code: "CAK", name: "Church Acre K" },
  { code: "JD", name: "Jackdaw Ditch" },
  { code: "KH", name: "Kempsford Hams" },
  { code: "SM", name: "Somerford M" },
  { code: "HB", name: "Horcott Bridge" },
  { code: "DD", name: "Downington D" },
  { code: "MH", name: "Milton Ham" },
  { code: "TJ", name: "Trewsbury J" },
  { code: "PIC", name: "Pindale C" },
  { code: "DC", name: "Derry C" },
  { code: "DK", name: "Downington K" },
  { code: "OB", name: "Old Bridge" },
  { code: "PT/M", name: "Pinsley T/M" },
  { code: "PT", name: "Poulton/Tetbury" },
];

const CX = 300;
const TOP_Y = 60;
const BOT_Y = 870;
const STEP = (BOT_Y - TOP_Y) / (SITES.length - 1);
const LABEL_OFFSET = 100;

function yPos(i) {
  return TOP_Y + i * STEP;
}

export default function ColnLine() {
  const thamesY = yPos(SITES.length - 1) + 40;
  const [popup, setPopup] = useState(null);
  const [loadingPopup, setLoadingPopup] = useState(false);
  const summaryCache = useRef({});

  const handleClick = (code, y, isLeft) => {
    setLoadingPopup(true);
    const cached = summaryCache.current[code];
    if (cached) {
      setPopup({ ...cached, y, isLeft });
      setLoadingPopup(false);
      return;
    }
    getSiteSummary(code).then((data) => {
      summaryCache.current[code] = data;
      setPopup({ ...data, y, isLeft });
      setLoadingPopup(false);
    });
  };

  const POPUP_W = 260;

  const renderPopup = () => {
    if (!popup) return null;
    const chems = popup.chemicals;
    const chemCount = chems ? Object.keys(chems).length : 0;
    const POPUP_H = chemCount > 0 ? 90 + chemCount * 22 : 80;
    const py = popup.y - POPUP_H / 2;
    const isLeft = popup.isLeft;
    const lx = CX + (isLeft ? -LABEL_OFFSET : LABEL_OFFSET);
    const tx = isLeft ? lx - 10 : lx + 10;
    const px = isLeft ? tx - POPUP_W - 10 : tx + 10;
    return (
      <g>
        <rect
          x={px}
          y={py}
          width={POPUP_W}
          height={POPUP_H}
          rx={8}
          ry={8}
          fill="#fff"
          stroke="#e5e7eb"
          strokeWidth={1}
          filter="url(#popup-shadow)"
        />
        <foreignObject
          x={px + 10}
          y={py + 10}
          width={POPUP_W - 20}
          height={POPUP_H - 20}
        >
          <div style={{ fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif", fontSize: "0.8rem" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
              <strong style={{ fontSize: "0.9rem" }}>{popup.site} — {popup.name}</strong>
              <span
                onClick={() => setPopup(null)}
                style={{ cursor: "pointer", color: "#6b7280", fontSize: "1.1rem", lineHeight: 1 }}
              >
                ×
              </span>
            </div>
            {!chems || Object.keys(chems).length === 0 ? (
              <p style={{ color: "#6b7280", margin: 0 }}>No chemical data.</p>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ color: "#6b7280", borderBottom: "1px solid #e5e7eb" }}>
                    <th style={{ textAlign: "left", padding: "3px 6px" }}>Chemical</th>
                    <th style={{ textAlign: "right", padding: "3px 6px" }}>Mean</th>
                    <th style={{ textAlign: "right", padding: "3px 6px" }}>Max</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(chems).map(([chem, info]) => (
                    <tr key={chem} style={{ borderBottom: "1px solid #f3f4f6" }}>
                      <td style={{ padding: "3px 6px", fontWeight: 500, textTransform: "capitalize" }}>{chem.replace("_", " ")}</td>
                      <td style={{ padding: "3px 6px", textAlign: "right" }}>{info.mean}</td>
                      <td style={{ padding: "3px 6px", textAlign: "right" }}>{info.max}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <p style={{ fontSize: "0.65rem", color: "#6b7280", margin: "6px 0 0" }}>
              Values in {chems?.phosphate?.unit || "mg/L"}
            </p>
          </div>
        </foreignObject>
      </g>
    );
  };

  return (
    <div className="table-section" style={{ position: "relative" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <h2 className="chart-section-heading" style={{ margin: 0, marginBottom: 0 }}>The Coln Line — Schematic</h2>
      </div>
      <svg viewBox="-100 0 850 1000" style={{ width: "100%", maxWidth: 750, display: "block", margin: "0 auto", fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" }}>
        <defs>
          <filter id="popup-shadow">
            <feDropShadow dx="0" dy="4" stdDeviation="8" floodOpacity="0.12" />
          </filter>
        </defs>

        {/* River Coln main line - connects through to Thames */}
        <line x1={CX} y1={yPos(0)} x2={CX} y2={thamesY} stroke="#2563eb" strokeWidth={8} strokeLinecap="butt" />

        {/* Grey extension above first site */}
        <line x1={CX} y1={yPos(0)} x2={CX} y2={TOP_Y - 30} stroke="#9ca3af" strokeWidth={4} strokeLinecap="butt" />
        <text x={CX} y={TOP_Y - 36} textAnchor="middle" fill="#9ca3af" fontSize={13}>Upper Coln</text>

        {/* Thames line at bottom */}
        <line x1={CX - 100} y1={thamesY} x2={CX + 100} y2={thamesY} stroke="#9ca3af" strokeWidth={4} strokeLinecap="butt" />
        <text x={CX + 106} y={thamesY + 5} textAnchor="start" fill="#9ca3af" fontSize={13}>River Thames</text>

        {/* Sites — callout lines, dots, and labels in one pass */}
        {SITES.map((site, i) => {
          const y = yPos(i);
          const isLeft = i % 2 === 0;
          const lx = isLeft ? CX - LABEL_OFFSET : CX + LABEL_OFFSET;
          const tx = isLeft ? lx - 10 : lx + 10;
          const ta = isLeft ? "end" : "start";
          const r = i === 0 || i === SITES.length - 1 ? 6 : 5;
          return (
            <g key={site.code}>
              <line x1={CX} y1={y} x2={lx} y2={y} stroke="#d1d5db" strokeWidth={1.5} />
              <line x1={CX} y1={y - 4} x2={CX} y2={y + 4} stroke="#d1d5db" strokeWidth={1.5} />
              <circle cx={CX} cy={y} r={r} fill="#2563eb" stroke="#fff" strokeWidth={2} />
              <g style={{ cursor: "pointer" }} onClick={() => handleClick(site.code, y, isLeft)}>
                <text x={tx} y={y + 5} textAnchor={ta} fill="#1a56db" fontSize={13} fontWeight={700}>
                  {site.code}
                </text>
                <text x={tx} y={y - 10} textAnchor={ta} fill="#6b7280" fontSize={10}>
                  {site.name}
                </text>
                <line
                  x1={ta === "end" ? tx + 2 : tx - 2}
                  y1={y + 8}
                  x2={ta === "end" ? tx - 2 : tx + 2}
                  y2={y + 8}
                  stroke="#93c5fd"
                  strokeWidth={1}
                  opacity={0.6}
                />
              </g>
            </g>
          );
        })}

        {/* Summary popup rendered in SVG */}
        {popup && renderPopup()}
      </svg>
    </div>
  );
}
