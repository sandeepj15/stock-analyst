"use client";

import { useCallback, useEffect, useState } from "react";
import { THEME_CHANGE_EVENT, applyTheme, getCurrentTheme, type ThemeName } from "./theme";

// Must match `getCurrentTheme()`'s SSR fallback (lib/theme.ts) exactly.
// This is intentionally NOT the live theme - see the comment below.
const SSR_SAFE_DEFAULT: ThemeName = "dark";

/** Live theme state + toggle, shared across every component via a window
 * CustomEvent (no context provider needed - app/layout.tsx's inline
 * script already set the real `data-theme` on `<html>` before paint, so
 * the *page's colors* are correct from the very first frame regardless
 * of what this hook returns).
 *
 * This hook's own state deliberately starts at a fixed value instead of
 * reading the DOM immediately: React hydration requires the first client
 * render to produce the exact same output as the server-rendered HTML.
 * The server has no `document` (lib/theme.ts's `getCurrentTheme()` falls
 * back to "dark" there), so if a component read the *actual* (possibly
 * different, e.g. "light") theme during its first render, React would
 * hit a hydration mismatch - which is not a cosmetic warning here: a
 * mismatch this fundamental (an attribute the pre-paint script set
 * before hydration even started) can make React discard the whole
 * server-rendered document and rebuild it from scratch client-side,
 * which was observed to silently wipe the `data-theme` attribute again.
 * Starting every consumer at the same fixed default and correcting to
 * the real theme in `useEffect` (i.e. strictly after hydration commits)
 * avoids that entirely - a one-frame correction, never a document reset. */
export function useTheme(): [ThemeName, () => void] {
  const [theme, setTheme] = useState<ThemeName>(SSR_SAFE_DEFAULT);

  useEffect(() => {
    // First real read of the DOM, safely deferred until after hydration.
    setTheme(getCurrentTheme());

    function handleThemeChange(event: Event) {
      const detail = (event as CustomEvent<ThemeName>).detail;
      if (detail) setTheme(detail);
    }

    window.addEventListener(THEME_CHANGE_EVENT, handleThemeChange);
    return () => window.removeEventListener(THEME_CHANGE_EVENT, handleThemeChange);
  }, []);

  const toggle = useCallback(() => {
    applyTheme(getCurrentTheme() === "dark" ? "light" : "dark");
  }, []);

  return [theme, toggle];
}
