// Score-band -> color mapping (SCORING.md section 1 / SPEC.md section 19
// band labels). This is display-only - the band *label* itself always
// comes from the API (packages/scoring/bands.py), never recomputed or
// re-labeled here; this just picks which CSS variable (app/globals.css,
// both themes) renders it in.
const BAND_COLOR_VARS: Record<string, string> = {
  "Very Weak": "--band-very-weak",
  Weak: "--band-weak",
  Neutral: "--band-neutral",
  Moderate: "--band-moderate",
  Strong: "--band-strong",
  "Very Strong": "--band-very-strong",
};

export function bandColor(band: string | null | undefined): string {
  if (!band) return "var(--text-muted)";
  const cssVar = BAND_COLOR_VARS[band];
  return cssVar ? `var(${cssVar})` : "var(--text-muted)";
}
