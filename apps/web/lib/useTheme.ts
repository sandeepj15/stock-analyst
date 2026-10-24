"use client";

import { useCallback, useEffect, useState } from "react";
import { THEME_CHANGE_EVENT, applyTheme, getCurrentTheme, VALID_THEMES, type ThemeName } from "./theme";

const SSR_SAFE_DEFAULT: ThemeName = "dark";

export function useTheme(): [ThemeName, (theme: ThemeName) => void, () => void] {
  const [theme, setTheme] = useState<ThemeName>(SSR_SAFE_DEFAULT);

  useEffect(() => {
    // First real read of the DOM, safely deferred until after hydration.
    setTheme(getCurrentTheme());

    function handleThemeChange(event: Event) {
      const detail = (event as CustomEvent<ThemeName>).detail;
      if (detail && VALID_THEMES.includes(detail)) {
        setTheme(detail);
      }
    }

    window.addEventListener(THEME_CHANGE_EVENT, handleThemeChange);
    return () => window.removeEventListener(THEME_CHANGE_EVENT, handleThemeChange);
  }, []);

  const setThemeExplicit = useCallback((nextTheme: ThemeName) => {
    applyTheme(nextTheme);
  }, []);

  const cycleTheme = useCallback(() => {
    const current = getCurrentTheme();
    const idx = VALID_THEMES.indexOf(current);
    const next = VALID_THEMES[(idx + 1) % VALID_THEMES.length];
    applyTheme(next);
  }, []);

  return [theme, setThemeExplicit, cycleTheme];
}
