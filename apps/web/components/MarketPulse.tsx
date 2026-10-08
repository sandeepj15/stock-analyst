"use client";

import { useEffect, useState } from "react";
import { getMarketRegime, getScoreDistribution, getSectorSummary } from "../lib/api";
import type { InstrumentSummary, MarketRegimeResponse, ScoreDistributionResponse, SectorsResponse } from "../lib/types";
import NiftyMiniChart from "./NiftyMiniChart";
import BreadthGauge from "./BreadthGauge";
import ScoreDistributionChart from "./ScoreDistributionChart";
import SectorHeatmap from "./SectorHeatmap";
import TopMovers from "./TopMovers";
import MarketInternalsWidget from "./MarketInternalsWidget";
import MarketLeadersWidget from "./MarketLeadersWidget";

// Home page "Market Pulse" dashboard (UI/UX task): one cohesive section
// above the instrument table, built from five widgets that each own
// their own data fetch/loading/error state (same resilience philosophy
// as StockPageClient's phase3 panels - one widget's failure never blanks
// out the rest of the dashboard or the table below it).
interface Props {
  instruments: InstrumentSummary[];
  selectedBand: string | null;
  onSelectBand: (band: string | null) => void;
  selectedSector: string | null;
  onSelectSector: (sector: string | null) => void;
}

export default function MarketPulse({
  instruments,
  selectedBand,
  onSelectBand,
  selectedSector,
  onSelectSector,
}: Props) {
  const [regime, setRegime] = useState<MarketRegimeResponse | null>(null);
  const [scoreDistribution, setScoreDistribution] = useState<ScoreDistributionResponse | null>(null);
  const [sectors, setSectors] = useState<SectorsResponse | null>(null);

  useEffect(() => {
    getMarketRegime()
      .then(setRegime)
      .catch(() => setRegime(null)); // NiftyMiniChart/BreadthGauge render their own "not yet computed" state.
    getScoreDistribution()
      .then(setScoreDistribution)
      .catch(() => setScoreDistribution(null));
    getSectorSummary()
      .then(setSectors)
      .catch(() => setSectors(null));
  }, []);

  return (
    <section className="pulse-section" aria-label="Market Pulse">
      <h2 className="pulse-heading">Market Pulse</h2>
      <div className="pulse-grid">
        <NiftyMiniChart regime={regime} />
        <BreadthGauge regime={regime} />
        <MarketInternalsWidget instruments={instruments} />
        <ScoreDistributionChart data={scoreDistribution} selectedBand={selectedBand} onSelectBand={onSelectBand} />
        <SectorHeatmap data={sectors} selectedSector={selectedSector} onSelectSector={onSelectSector} />
        <TopMovers instruments={instruments} />
        <MarketLeadersWidget instruments={instruments} />
      </div>
    </section>
  );
}
