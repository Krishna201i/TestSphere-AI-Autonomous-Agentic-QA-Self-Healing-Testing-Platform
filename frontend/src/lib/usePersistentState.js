/**
 * useState that remembers its value in this browser (filters, view choices).
 * Storage failures (private mode, blocked storage) fall back to plain state.
 */
import { useEffect, useState } from 'react';

export default function usePersistentState(key, initial) {
  const storageKey = `testsphere.${key}`;
  const [value, setValue] = useState(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      return raw == null ? initial : JSON.parse(raw);
    } catch {
      return initial;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(value));
    } catch {
      // not remembered; still works for this visit
    }
  }, [storageKey, value]);
  return [value, setValue];
}
