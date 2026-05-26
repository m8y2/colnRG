import { useState, useRef, useEffect, useMemo } from "react";

export default function AnimatedSelect({ options, value, onChange, placeholder, className }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const selected = useMemo(() => options.find((o) => o.value === value), [options, value]);
  const ordered = useMemo(() => {
    if (!value) return options;
    const all = options.find((o) => o.value === "");
    const sel = options.find((o) => o.value === value);
    const rest = options.filter((o) => o.value !== "" && o.value !== value);
    return [all, sel, ...rest].filter(Boolean);
  }, [options, value]);

  return (
    <div className={`chemical-select ${className || ""}`} ref={ref}>
      <button
        className="chemical-select-trigger"
        onClick={() => setOpen((o) => !o)}
        type="button"
      >
        <span>{selected?.label || placeholder || "Select..."}</span>
        <span className={`chemical-select-arrow ${open ? "open" : ""}`}>
          ▾
        </span>
      </button>
      <div className={`chemical-select-menu ${open ? "open" : ""}`}>
        {ordered.map((o) => (
          <button
            key={o.value}
            className={`chemical-select-item ${o.value === value ? "active" : ""}`}
            onClick={() => {
              onChange(o.value);
              setOpen(false);
            }}
            type="button"
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}
