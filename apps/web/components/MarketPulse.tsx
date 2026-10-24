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
    // Safely hydrate cached data from sessionStorage on client mount without triggering hydration mismatches
    try {
      const savedRegime = sessionStorage.getItem("signalforge_regime_cache");
      if (savedRegime) setRegime(JSON.parse(savedRegime));
      const savedDist = sessionStorage.getItem("signalforge_score_dist_cache");
      if (savedDist) setScoreDistribution(JSON.parse(savedDist));
      const savedSectors = sessionStorage.getItem("signalforge_sectors_cache");
      if (savedSectors) setSectors(JSON.parse(savedSectors));
    } catch {}

    getMarketRegime()
      .then((res) => {
        setRegime(res);
        try {
          sessionStorage.setItem("signalforge_regime_cache", JSON.stringify(res));
        } catch {}
      })
      .catch(() => setRegime(null));

    getScoreDistribution()
      .then((res) => {
        setScoreDistribution(res);
        try {
          sessionStorage.setItem("signalforge_score_dist_cache", JSON.stringify(res));
        } catch {}
      })
      .catch(() => setScoreDistribution(null));

    getSectorSummary()
      .then((res) => {
        setSectors(res);
        try {
          sessionStorage.setItem("signalforge_sectors_cache", JSON.stringify(res));
        } catch {}
      })
      .catch(() => setSectors(null));
  }, []);

  return (
    <section className="pulse-section" aria-label="Market Pulse">
      <h2 className="pulse-heading">Market Pulse</h2>
      <div className="pulse-grid">
        <NiftyMiniChart regime={regime} />
        <BreadthGauge regime={regime} />
        <MarketInternalsWidget instruments={instruments} />
        <ScoreDistributionChart
          data={scoreDistribution}
          selectedBand={selectedBand}
          onSelectBand={onSelectBand}
          instruments={instruments}
        />
        <SectorHeatmap data={sectors} selectedSector={selectedSector} onSelectSector={onSelectSector} />
        <TopMovers instruments={instruments} />
        <MarketLeadersWidget instruments={instruments} />
      </div>
    </section>
  );
}
