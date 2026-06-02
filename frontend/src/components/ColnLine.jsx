import { useState, useRef } from "react";
import { getSiteSummary } from "../api";

const SITES = [
  { code: "EP" },
  { code: "PW" },
  { code: "SJR" },
  { code: "MG" },
  { code: "NL" },
  { code: "ST/LAT" },
  { code: "CS" },
  { code: "WMW" },
  { code: "GED" },
  { code: "DFG" },
  { code: "GDR" },
  { code: "CAK" },
  { code: "JD" },
  { code: "KH" },
  { code: "SM" },
  { code: "HB" },
  { code: "DD" },
  { code: "MH" },
  { code: "TJ" },
  { code: "PIC" },
  { code: "DC" },
  { code: "DK" },
  { code: "OB" },
  { code: "PT/M" },
  { code: "PT" },
];

const CX = 300;
const TOP_Y = 60;
const BOT_Y = 870;
const STEP = (BOT_Y - TOP_Y) / (SITES.length - 1);
const LABEL_OFFSET = 100;

function yPos(i) {
  return TOP_Y + i * STEP;
}

export default function ColnLine({ darkMode }) {
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
          fill={darkMode ? "#1e293b" : "#fff"}
          stroke={darkMode ? "#475569" : "#e5e7eb"}
          strokeWidth={1}
          filter="url(#popup-shadow)"
        />
        <foreignObject
          x={px + 10}
          y={py + 10}
          width={POPUP_W - 20}
          height={POPUP_H - 20}
        >
          <div style={{ fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif", fontSize: "0.8rem", color: "var(--text)" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
              <strong style={{ fontSize: "0.9rem", color: "var(--text)" }}>{popup.site}</strong>
              <span
                onClick={() => setPopup(null)}
                style={{ cursor: "pointer", color: "var(--text-muted)", fontSize: "1.1rem", lineHeight: 1 }}
              >
                ×
              </span>
            </div>
            {!chems || Object.keys(chems).length === 0 ? (
              <p style={{ color: "var(--text-muted)", margin: 0 }}>No chemical data.</p>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ color: "var(--text-muted)", borderBottom: "1px solid var(--border)" }}>
                    <th style={{ textAlign: "left", padding: "3px 6px" }}>Chemical</th>
                    <th style={{ textAlign: "right", padding: "3px 6px" }}>Mean</th>
                    <th style={{ textAlign: "right", padding: "3px 6px" }}>Max</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(chems).map(([chem, info]) => (
                    <tr key={chem} style={{ borderBottom: "1px solid var(--border)" }}>
                      <td style={{ padding: "3px 6px", fontWeight: 500, textTransform: "capitalize", color: "var(--text)" }}>{chem.replace("_", " ")}</td>
                      <td style={{ padding: "3px 6px", textAlign: "right", color: "var(--text-secondary)" }}>{info.mean}</td>
                      <td style={{ padding: "3px 6px", textAlign: "right", color: "var(--text-secondary)" }}>{info.max}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <p style={{ fontSize: "0.65rem", color: "var(--text-muted)", margin: "6px 0 0" }}>
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
                <text x={tx} y={y + 5} textAnchor={ta} fill="#9ca3af" fontSize={13} fontWeight={600}>
                  {site.code}
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
