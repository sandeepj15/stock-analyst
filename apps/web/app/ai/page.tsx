import type { Metadata } from "next";
import AiAnalystChat from "../../components/AiAnalystChat";

export const metadata: Metadata = {
  title: "AI Analyst · Vertex Gemini | SignalForge",
  description:
    "Institutional quantitative equity research powered by Google Cloud Vertex AI Gemini and live PostgreSQL database.",
};

export default function AiPage() {
  return (
    <div className="ai-page-container">
      <AiAnalystChat isEmbedded={false} />
    </div>
  );
}
