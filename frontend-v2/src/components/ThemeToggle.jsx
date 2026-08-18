import { useEffect, useId, useState } from 'react';

const STORAGE_KEY = 'crg-v2-theme';

function applyTheme(value) {
  if (value === 'light' || value === 'dark') {
    document.documentElement.dataset.theme = value;
  } else {
    delete document.documentElement.dataset.theme;
  }
}

export default function ThemeToggle() {
  const selectId = useId();
  const [theme, setTheme] = useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) || 'system';
    } catch {
      return 'system';
    }
  });

  useEffect(() => {
    applyTheme(theme);
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // storage unavailable (private browsing etc.) — theme still applies for this visit
    }
  }, [theme]);

  return (
    <div className="field" style={{ minWidth: 150 }}>
      <label className="field__label visually-hidden" htmlFor={selectId}>
        Colour theme
      </label>
      <select
        id={selectId}
        className="native-select"
        value={theme}
        onChange={(e) => setTheme(e.target.value)}
      >
        <option value="system">Match device</option>
        <option value="light">Light</option>
        <option value="dark">Dark</option>
      </select>
    </div>
  );
}
