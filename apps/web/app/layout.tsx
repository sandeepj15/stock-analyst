import type { Metadata, Viewport } from "next";
import Link from "next/link";
import "./globals.css";
import ThemeToggle from "../components/ThemeToggle";
import GlobalSearch from "../components/GlobalSearch";
import { THEME_INIT_SCRIPT } from "../lib/theme";

export const metadata: Metadata = {
  title: "SignalForge",
  description: "Evidence-first market research and decision-support platform.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#161b22" },
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
  ],
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
          <div className="topnav-main-row">
            <div className="topnav-brand-wrap">
              <Link href="/" prefetch={true} className="brand">
                SignalForge
              </Link>
              <span className="tagline">Evidence-first research, not predictions.</span>
            </div>
            <div className="nav-right">
              <Link href="/ai" prefetch={true} className="topnav-ai-link" title="AI Alpha & Research">
                <span className="topnav-ai-icon">🎯</span>
                <span className="topnav-ai-text">AI Alpha</span>
                <span className="topnav-ai-badge">Gemini</span>
              </Link>
              <ThemeToggle />
            </div>
          </div>
          <div className="topnav-search-row">
            <GlobalSearch />
          </div>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
