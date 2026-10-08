"use client";

import { useTheme } from "../lib/useTheme";

export default function ThemeToggle() {
  const [theme, toggle] = useTheme();
  const isDark = theme === "dark";

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={toggle}
      aria-label={`Switch to ${isDark ? "light" : "dark"} theme`}
      title={`Switch to ${isDark ? "light" : "dark"} theme`}
    >
      <span aria-hidden="true">{isDark ? "\u{1F319}" : "\u{2600}\u{FE0F}"}</span>
      {isDark ? "Dark" : "Light"}
    </button>
  );
}
