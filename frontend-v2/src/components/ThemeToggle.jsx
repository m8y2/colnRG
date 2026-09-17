import { useEffect, useState } from 'react';

// Same non-cookie technique as v1 (frontend/src/App.jsx): a plain
// localStorage flag, no "match device" option kept live during the visit.
// A page that silently changes theme mid-session because the OS switched
// at sunset is confusing to come back to, so the device's preference is
// only ever a one-time starting point: read once, then overridden the
// moment someone picks a side, exactly like v1's toggle.
const STORAGE_KEY = 'crg-v2-theme';

function initialTheme() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === 'light' || saved === 'dark') return saved;
  } catch {
    // storage unavailable (private browsing etc.), so fall through to the
    // device default below; the choice just won't be remembered this visit
  }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState(initialTheme);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // storage unavailable, but theme still applies for this visit
    }
  }, [theme]);

  const isDark = theme === 'dark';
  const label = isDark ? 'Switch to light mode' : 'Switch to dark mode';

  return (
    <button
      type="button"
      className="btn btn-secondary btn-sm theme-toggle"
      onClick={() => setTheme(isDark ? 'light' : 'dark')}
      title={label}
    >
      <span aria-hidden="true">{isDark ? '☀' : '☾'}</span>
      <span className="visually-hidden">{label}</span>
    </button>
  );
}
