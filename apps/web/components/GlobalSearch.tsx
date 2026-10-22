"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { listInstruments, prefetchStock } from "../lib/api";
import { saveStockSummary } from "../lib/stockSummaryCache";
import { InstrumentSummary } from "../lib/types";

export default function GlobalSearch() {
  const [query, setQuery] = useState("");
  const [instruments, setInstruments] = useState<InstrumentSummary[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const router = useRouter();
  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Fetch all instruments once for client-side fast search
    listInstruments().then((data) => setInstruments(data)).catch(console.error);
  }, []);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const trimmed = query.trim().toLowerCase();
  const filtered = trimmed === "" 
    ? [] 
    : instruments
        .filter(
          (inst) =>
            inst.symbol.toLowerCase().includes(trimmed) ||
            inst.company_name.toLowerCase().includes(trimmed)
        )
        .sort((a, b) => {
          const aSym = a.symbol.toLowerCase();
          const bSym = b.symbol.toLowerCase();
          if (aSym === trimmed && bSym !== trimmed) return -1;
          if (aSym !== trimmed && bSym === trimmed) return 1;
          if (aSym.startsWith(trimmed) && !bSym.startsWith(trimmed)) return -1;
          if (!aSym.startsWith(trimmed) && bSym.startsWith(trimmed)) return 1;
          const aName = a.company_name.toLowerCase();
          const bName = b.company_name.toLowerCase();
          if (aName.startsWith(trimmed) && !bName.startsWith(trimmed)) return -1;
          if (!aName.startsWith(trimmed) && bName.startsWith(trimmed)) return 1;
          return aSym.localeCompare(bSym);
        })
        .slice(0, 8); // limit to top 8 suggestions

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && filtered.length > 0) {
      const topInst = filtered[0];
      setQuery("");
      setIsOpen(false);
      saveStockSummary(topInst);
      router.push(`/stocks/${topInst.symbol}`);
    }
  };

  return (
    <div ref={wrapperRef} style={{ position: "relative", marginLeft: "20px", flex: 1, maxWidth: "400px" }}>
      <input
        type="text"
        placeholder="Search stocks (e.g. RELIANCE, TCS)..."
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setIsOpen(true);
        }}
        onKeyDown={handleKeyDown}
        onFocus={() => setIsOpen(true)}
        style={{
          width: "100%",
          padding: "6px 12px",
          borderRadius: "4px",
          border: "1px solid var(--border)",
          background: "var(--bg-panel)",
          color: "var(--fg-default)",
        }}
      />
      {isOpen && filtered.length > 0 && (
        <div
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            right: 0,
            marginTop: "4px",
            background: "var(--bg-panel)",
            border: "1px solid var(--border)",
            borderRadius: "4px",
            boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
            zIndex: 100,
            maxHeight: "300px",
            overflowY: "auto"
          }}
        >
          {filtered.map((inst) => (
            <div
              key={inst.symbol}
              onClick={() => {
                setQuery("");
                setIsOpen(false);
                saveStockSummary(inst);
                router.push(`/stocks/${inst.symbol}`);
              }}
              style={{
                padding: "8px 12px",
                cursor: "pointer",
                borderBottom: "1px solid var(--border)",
                display: "flex",
                flexDirection: "column"
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = "var(--bg-muted)";
                saveStockSummary(inst);
                router.prefetch(`/stocks/${inst.symbol}`);
                prefetchStock(inst.symbol);
              }}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
            >
              <span style={{ fontWeight: "bold" }}>{inst.symbol}</span>
              <span style={{ fontSize: "0.85rem", color: "var(--fg-muted)" }}>{inst.company_name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
