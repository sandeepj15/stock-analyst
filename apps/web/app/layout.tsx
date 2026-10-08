import Link from "next/link";
import "./globals.css";
import ThemeToggle from "../components/ThemeToggle";
import { THEME_INIT_SCRIPT } from "../lib/theme";

export const metadata = {
  title: "SignalForge",
  description: "Evidence-first market research and decision-support platform.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  // suppressHydrationWarning below: `data-theme` is intentionally set by
  // a plain script (rendered just below) before React hydrates, not by
  // React itself - this is the standard, documented way to do this, and
  // the resulting "extra attribute from the server" warning is
  // expected/harmless (see lib/useTheme.ts for how every component
  // avoids an *actual* hydration mismatch from this).
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Sets `data-theme` on <html> synchronously, before first paint,
            so there is no flash of the wrong theme: default to the OS
            preference (`prefers-color-scheme`) unless the user already
            overrode it via the toggle (persisted in localStorage, see
            lib/theme.ts). This must stay a plain blocking <script>, not a
            Next.js Script component (those are deferred). */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body>
        <header className="topnav">
          <Link href="/" className="brand">
            SignalForge
          </Link>
          <span className="tagline">Evidence-first research, not predictions.</span>
          <div className="nav-right">
            <ThemeToggle />
          </div>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
