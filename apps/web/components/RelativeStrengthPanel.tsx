import { formatPct } from "../lib/format";
import type { RelativeStrengthResponse } from "../lib/types";

const HORIZON_ORDER = ["1W", "1M", "3M", "6M", "1Y"];

const REASON_LABELS: Record<string, string> = {
  insufficient_peer_universe: "Not enough sector peers in the seeded universe to compare against.",
  insufficient_price_history: "Not enough price history yet for this horizon.",
};

export default function RelativeStrengthPanel({ data }: { data: RelativeStrengthResponse }) {
  const allInsufficientPeers = Object.values(data.metrics).every(
    (m) => m.reason === "insufficient_peer_universe"
  );

  return (
    <div className="panel">
      <h2>Sector relative strength</h2>
      <p className="footnote">
        Sector: {data.sector ?? "Unclassified"} · Peer universe:{" "}
        <strong>seeded_sector_peers</strong> ({data.peer_count} peer{data.peer_count === 1 ? "" : "s"} in this dev
        dataset — not a licensed sector index)
      </p>

      {allInsufficientPeers && (
        <div className="notice">
          {data.sector
            ? `${data.sector} has fewer than 2 other seeded instruments, so no sector comparison is available.`
            : "This instrument has no sector classification, so no sector comparison is available."}{" "}
          The stock&apos;s own return is still shown below where available.
        </div>
      )}

      <table style={{ marginTop: "0.75rem" }}>
        <thead>
          <tr>
            <th>Horizon</th>
            <th>Stock return</th>
            <th>Peer avg return</th>
            <th>Relative strength</th>
          </tr>
        </thead>
        <tbody>
          {HORIZON_ORDER.map((horizon) => {
            const m = data.metrics[horizon];
            if (!m) return null;
            if (m.reason && m.reason !== "insufficient_peer_universe") {
              return (
                <tr key={horizon}>
                  <td>{horizon}</td>
                  <td colSpan={3} className="footnote">
                    {REASON_LABELS[m.reason] ?? m.reason}
                  </td>
                </tr>
              );
            }
            return (
              <tr key={horizon}>
                <td>{horizon}</td>
                <td>{formatPct(m.stock_return_pct)}</td>
                <td>{m.peer_avg_return_pct === null ? "—" : formatPct(m.peer_avg_return_pct)}</td>
                <td
                  className={
                    m.relative_strength_pct === null
                      ? ""
                      : m.relative_strength_pct >= 0
                        ? "tone-up"
                        : "tone-down"
                  }
                >
                  {m.relative_strength_pct === null ? "—" : formatPct(m.relative_strength_pct)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {data.peer_symbols.length > 0 && (
        <p className="footnote">Peers: {data.peer_symbols.join(", ")}</p>
      )}
    </div>
  );
}
