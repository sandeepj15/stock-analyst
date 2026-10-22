// Theme system shared state. `data-theme` on `<html>` drives every CSS
// custom property in app/globals.css; this module is the single source
// of truth for reading/writing it (localStorage-persisted, OS-preference
// default) and for the lightweight-charts color palettes, which can't
// read CSS variables themselves (chart options need literal color
// strings) so they're kept here in sync with globals.css by hand.
export type ThemeName = "light" | "dark";

export const THEME_STORAGE_KEY = "signalforge-theme";
export const THEME_CHANGE_EVENT = "signalforge-theme-change";

export function getStoredTheme(): ThemeName | null {
  if (typeof window === "undefined") return null;
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return stored === "light" || stored === "dark" ? stored : null;
  } catch {
    return null;
  }
}

export function getPreferredTheme(): ThemeName {
  // Light-first default: the user's explicit choice (persisted via the toggle)
  // always wins; absent that, this defaults to light mode.
  const stored = getStoredTheme();
  return stored ?? "light";
}

export function getCurrentTheme(): ThemeName {
  if (typeof document === "undefined") return "light";
  return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
}

export function applyTheme(theme: ThemeName): void {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-theme", theme);
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // localStorage unavailable (e.g. private mode) - theme still applies for this page view.
  }
  window.dispatchEvent(new CustomEvent<ThemeName>(THEME_CHANGE_EVENT, { detail: theme }));
}

// Inline script injected (via dangerouslySetInnerHTML, see app/layout.tsx)
// into <head> so it runs synchronously before first paint - this is what
// actually prevents the flash-of-wrong-theme, this module's helpers above
// are only used after hydration (the toggle, and chart re-theming).
export const THEME_INIT_SCRIPT = `
(function () {
  try {
    var stored = localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});
    // Light-first default: only an explicit prior toggle to "dark" overrides it.
    var theme = stored === "dark" ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", theme);
  } catch (e) {}
})();
`;

export interface ChartPalette {
  background: string;
  text: string;
  grid: string;
  border: string;
  up: string;
  down: string;
  upVolume: string;
  downVolume: string;
  accent: string;
  warn: string;
  purple: string;
}

// Mirrors app/globals.css's `html[data-theme="dark|light"]` blocks -
// lightweight-charts needs literal color strings, not CSS variables.
export const CHART_PALETTES: Record<ThemeName, ChartPalette> = {
  dark: {
    background: "#0c0f14",
    text: "#e8edf4",
    grid: "#141a22",
    border: "#1b222c",
    up: "#2fbf71",
    down: "#f0494c",
    upVolume: "#2fbf7166",
    downVolume: "#f0494c66",
    accent: "#f2a93b",
    warn: "#f0b429",
    purple: "#c084fc",
  },
  light: {
    background: "#ffffff",
    text: "#1a2130",
    grid: "#e8ecf2",
    border: "#d7dee8",
    up: "#166534",
    down: "#b42318",
    upVolume: "#16653455",
    downVolume: "#b4231855",
    accent: "#b6790a",
    warn: "#9a6700",
    purple: "#8250df",
  },
};
