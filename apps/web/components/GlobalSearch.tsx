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
    <div ref={wrapperRef} className="global-search-wrapper">
      <div className="global-search-input-box">
        <span className="global-search-icon" aria-hidden="true">🔍</span>
        <input
          type="text"
          placeholder="Search 1,510 stocks (e.g. RELIANCE, TCS)..."
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setIsOpen(true);
          }}
          onKeyDown={handleKeyDown}
          onFocus={() => setIsOpen(true)}
          className="global-search-input"
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
        />
        {query && (
          <button
            type="button"
            className="global-search-clear"
            onClick={() => {
              setQuery("");
              setIsOpen(false);
            }}
            aria-label="Clear search"
          >
            ✕
          </button>
        )}
      </div>
      {isOpen && filtered.length > 0 && (
        <div className="global-search-dropdown">
          {filtered.map((inst) => (
            <div
              key={inst.symbol}
              onClick={() => {
                setQuery("");
                setIsOpen(false);
                saveStockSummary(inst);
                router.push(`/stocks/${inst.symbol}`);
              }}
              className="global-search-item"
              onMouseEnter={() => {
                saveStockSummary(inst);
                router.prefetch(`/stocks/${inst.symbol}`);
                prefetchStock(inst.symbol);
              }}
            >
              <div className="global-search-item-main">
                <span className="global-search-item-sym">{inst.symbol}</span>
                <span className="global-search-item-name">{inst.company_name}</span>
              </div>
              <div className="global-search-item-meta">
                <span className="global-search-item-sector">{inst.sector || inst.exchange}</span>
                {inst.score !== undefined && inst.score !== null && (
                  <span className={`search-badge-score band-${(inst.band || "neutral").toLowerCase()}`}>
                    {inst.score.toFixed(1)}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
