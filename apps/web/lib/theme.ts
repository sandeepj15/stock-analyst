// Theme system shared state. `data-theme` on `<html>` drives every CSS
// custom property in app/globals.css; this module is the single source
// of truth for reading/writing it (localStorage-persisted).
export type ThemeName = "dark" | "light" | "cyber" | "nord" | "warm";

export const THEME_STORAGE_KEY = "signalforge-theme";
export const THEME_CHANGE_EVENT = "signalforge-theme-change";

export const VALID_THEMES: ThemeName[] = ["dark", "light", "cyber", "nord", "warm"];

export interface ThemeOption {
  id: ThemeName;
  name: string;
  icon: string;
  description: string;
  primaryColor: string;
  bgColor: string;
}

export const THEME_OPTIONS: ThemeOption[] = [
  {
    id: "dark",
    name: "Midnight Slate",
    icon: "🌌",
    description: "Modern institutional dark slate with crisp contrast",
    primaryColor: "#38bdf8",
    bgColor: "#0b0f17",
  },
  {
    id: "light",
    name: "Clean Light",
    icon: "☀️",
    description: "Crisp daylight pro research mode",
    primaryColor: "#0284c7",
    bgColor: "#f8fafc",
  },
  {
    id: "cyber",
    name: "Cyber Noir (OLED)",
    icon: "🖤",
    description: "Deep true black with glowing neon accents",
    primaryColor: "#00f5a0",
    bgColor: "#000000",
  },
  {
    id: "nord",
    name: "Nordic Frost",
    icon: "❄️",
    description: "Arctic calm palette with frost cyan",
    primaryColor: "#88c0d0",
    bgColor: "#242933",
  },
  {
    id: "warm",
    name: "Warm Graphite",
    icon: "☕",
    description: "Warm amber & charcoal with reduced blue light",
    primaryColor: "#f59e0b",
    bgColor: "#141210",
  },
];

export function getStoredTheme(): ThemeName | null {
  if (typeof window === "undefined") return null;
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY) as ThemeName | null;
    return stored && VALID_THEMES.includes(stored) ? stored : null;
  } catch {
    return null;
  }
}

export function getPreferredTheme(): ThemeName {
  const stored = getStoredTheme();
  return stored ?? "dark";
}

export function getCurrentTheme(): ThemeName {
  if (typeof document === "undefined") return "dark";
  const current = document.documentElement.getAttribute("data-theme") as ThemeName;
  return VALID_THEMES.includes(current) ? current : "dark";
}

export function applyTheme(theme: ThemeName): void {
  if (typeof document === "undefined") return;
  const targetTheme = VALID_THEMES.includes(theme) ? theme : "dark";
  document.documentElement.setAttribute("data-theme", targetTheme);
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, targetTheme);
  } catch {
    // localStorage unavailable (e.g. private mode)
  }
  window.dispatchEvent(new CustomEvent<ThemeName>(THEME_CHANGE_EVENT, { detail: targetTheme }));
}

// Inline script injected into <head> so it runs synchronously before first paint
export const THEME_INIT_SCRIPT = `
(function () {
  try {
    var stored = localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});
    var valid = ["dark", "light", "cyber", "nord", "warm"];
    var theme = valid.indexOf(stored) !== -1 ? stored : "dark";
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

// Mirrors app/globals.css's `html[data-theme="..."]` blocks
export const CHART_PALETTES: Record<ThemeName, ChartPalette> = {
  dark: {
    background: "#0e131f",
    text: "#f1f5f9",
    grid: "#1e293b44",
    border: "#1f293d",
    up: "#10b981",
    down: "#f43f5e",
    upVolume: "#10b98155",
    downVolume: "#f43f5e55",
    accent: "#38bdf8",
    warn: "#f59e0b",
    purple: "#a855f7",
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
    accent: "#0284c7",
    warn: "#d97706",
    purple: "#7c3aed",
  },
  cyber: {
    background: "#050507",
    text: "#e4e4e7",
    grid: "#18181b88",
    border: "#27272a",
    up: "#00f5a0",
    down: "#ff3366",
    upVolume: "#00f5a055",
    downVolume: "#ff336655",
    accent: "#06b6d4",
    warn: "#facc15",
    purple: "#c084fc",
  },
  nord: {
    background: "#242933",
    text: "#eceff4",
    grid: "#2e3440cc",
    border: "#3b4252",
    up: "#a3be8c",
    down: "#bf616a",
    upVolume: "#a3be8c55",
    downVolume: "#bf616a55",
    accent: "#88c0d0",
    warn: "#ebcb8b",
    purple: "#b48ead",
  },
  warm: {
    background: "#161412",
    text: "#f5f5f4",
    grid: "#26232088",
    border: "#2e2a27",
    up: "#22c55e",
    down: "#ef4444",
    upVolume: "#22c55e55",
    downVolume: "#ef444455",
    accent: "#f59e0b",
    warn: "#f97316",
    purple: "#d946ef",
  },
};
