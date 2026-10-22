import type { Metadata } from "next";
import { Suspense } from "react";
import AiPageClient from "../../components/AiPageClient";

export const metadata: Metadata = {
  title: "AI Alpha Picks & Analyst · Gemini | SignalForge",
  description:
    "Institutional quantitative equity research powered by Google Cloud Vertex AI Gemini and live PostgreSQL multi-factor signals.",
};

export default function AiPage() {
  return (
    <Suspense
      fallback={
        <div
          style={{
            display: "flex",
            height: "360px",
            alignItems: "center",
            justifyContent: "center",
            color: "var(--text-muted)",
            fontSize: "0.9rem",
          }}
        >
          Loading AI Alpha &amp; Research...
        </div>
      }
    >
      <AiPageClient />
    </Suspense>
  );
}
