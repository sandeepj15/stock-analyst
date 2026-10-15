"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { listInstruments } from "../lib/api";
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

  const filtered = query.trim() === "" 
    ? [] 
    : instruments.filter(
        (inst) =>
          inst.symbol.toLowerCase().includes(query.toLowerCase()) ||
          inst.company_name.toLowerCase().includes(query.toLowerCase())
      ).slice(0, 8); // limit to top 8 suggestions

  return (
    <div ref={wrapperRef} style={{ position: "relative", marginLeft: "20px", flex: 1, maxWidth: "400px" }}>
      <input
        type="text"
        placeholder="Search stocks..."
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setIsOpen(true);
        }}
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
                router.push(`/stocks/${inst.symbol}`);
              }}
              style={{
                padding: "8px 12px",
                cursor: "pointer",
                borderBottom: "1px solid var(--border)",
                display: "flex",
                flexDirection: "column"
              }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-muted)")}
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
