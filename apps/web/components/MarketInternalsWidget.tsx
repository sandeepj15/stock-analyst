import type { InstrumentSummary } from "../lib/types";

// Displays Advance/Decline statistics and Stage 2 momentum scanner passage rate
// for the entire universe of instruments.
export default function MarketInternalsWidget({ instruments }: { instruments: InstrumentSummary[] }) {
  if (!instruments || instruments.length === 0) {
    return (
      <div className="pulse-card">
        <div className="pulse-card-head">
          <h3>Market Internals</h3>
        </div>
        <p className="footnote">Data not available.</p>
      </div>
    );
  }

  let advancing = 0;
  let declining = 0;
  let unchanged = 0;

  let momentumPass = 0;
  let momentumTotal = 0;

  for (const inst of instruments) {
    if (inst.day_change_pct !== null) {
      if (inst.day_change_pct > 0) advancing++;
      else if (inst.day_change_pct < 0) declining++;
      else unchanged++;
    }

    if (inst.momentum_pass !== null) {
      momentumTotal++;
      if (inst.momentum_pass) {
        momentumPass++;
      }
    }
  }

  const adTotal = advancing + declining + unchanged;
  const adRatio = declining > 0 ? (advancing / declining).toFixed(2) : "—";
  
  const advPct = adTotal > 0 ? (advancing / adTotal) * 100 : 0;
  const decPct = adTotal > 0 ? (declining / adTotal) * 100 : 0;
  const flatPct = adTotal > 0 ? (unchanged / adTotal) * 100 : 0;
  
  const stage2Pct = momentumTotal > 0 ? (momentumPass / momentumTotal) * 100 : 0;

  return (
    <div className="pulse-card">
      <div className="pulse-card-head">
        <h3>Market Internals</h3>
        <span className="footnote">{adTotal > 0 ? `${adTotal} Stocks` : ""}</span>
      </div>

      <div style={{ marginTop: "1rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.4rem", fontSize: "0.78rem" }}>
          <span style={{ color: "var(--up)" }}>{advancing} Advancing</span>
          <span style={{ color: "var(--down)" }}>{declining} Declining</span>
        </div>
        <div style={{ display: "flex", height: "10px", borderRadius: "999px", overflow: "hidden", background: "var(--surface-alt)", marginBottom: "0.5rem" }}>
          <div style={{ width: `${advPct}%`, background: "var(--up)", transition: "width 0.2s ease" }} />
          <div style={{ width: `${flatPct}%`, background: "var(--text-muted)", transition: "width 0.2s ease" }} />
          <div style={{ width: `${decPct}%`, background: "var(--down)", transition: "width 0.2s ease" }} />
        </div>
        <div style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
          A/D Ratio: <span className="num" style={{ fontWeight: 600, color: advancing >= declining ? "var(--up)" : "var(--down)" }}>{adRatio}</span>
        </div>
      </div>

      <div style={{ marginTop: "1.25rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.4rem", fontSize: "0.78rem" }}>
          <span style={{ color: "var(--text)" }}>Stage 2 Breakouts</span>
          <span className="num" style={{ fontWeight: 600, color: "var(--text)" }}>{momentumPass} <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>/ {momentumTotal}</span></span>
        </div>
        <div style={{ display: "flex", height: "10px", borderRadius: "999px", overflow: "hidden", background: "var(--surface-alt)" }}>
          <div style={{ width: `${stage2Pct}%`, background: "var(--up)", transition: "width 0.2s ease" }} />
        </div>
      </div>

    </div>
  );
}
