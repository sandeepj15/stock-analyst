// Home page: search + browse the seeded instrument universe. This is the
// main interactive entry point into the stock research pages
// (SPEC.md section 87, "Prompt 6 - Stock Research UI").
import { listInstruments } from "../lib/api";
import HomeBrowser from "../components/HomeBrowser";

// Cache the home page universe listing for 60 seconds with ISR so navigation
// back to the home page responds instantaneously (0ms) instead of re-fetching
// 1.5MB of data on every single click.
export const revalidate = 60;

export default async function HomePage() {
  let instruments: Awaited<ReturnType<typeof listInstruments>> = [];
  let loadError: string | null = null;

  try {
    instruments = await listInstruments();
  } catch (err) {
    loadError = err instanceof Error ? err.message : "Failed to load instruments.";
  }

  if (loadError) {
    return (
      <div className="notice error">
        Could not load the instrument list from the API: {loadError}
      </div>
    );
  }

  return <HomeBrowser initialInstruments={instruments} />;
}
