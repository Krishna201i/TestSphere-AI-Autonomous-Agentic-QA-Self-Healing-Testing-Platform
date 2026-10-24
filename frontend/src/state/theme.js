/**
 * Colour theme: "light", "dark" or "system" (follow the OS).  Stored per
 * browser; applied as data-theme on <html>, which theme.css keys off.
 */
import { useCallback, useState } from 'react';

const KEY = 'testsphere.theme';
export const THEMES = [['system', 'System'], ['light', 'Light'], ['dark', 'Dark']];

export function loadTheme() {
  try {
    const v = localStorage.getItem(KEY);
    return THEMES.some(([id]) => id === v) ? v : 'system';
  } catch {
    return 'system';
  }
}

export function applyTheme(theme) {
  const root = document.documentElement;
  if (theme === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', theme);
}

export function useTheme() {
  const [theme, setThemeState] = useState(loadTheme);
  const setTheme = useCallback((next) => {
    setThemeState(next);
    applyTheme(next);
    try {
      localStorage.setItem(KEY, next);
    } catch {
      // applies for this visit only
    }
  }, []);
  return [theme, setTheme];
}
