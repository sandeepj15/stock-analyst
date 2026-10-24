"use client";

import { useEffect, useRef, useState } from "react";
import { useTheme } from "../lib/useTheme";
import { THEME_OPTIONS, type ThemeName } from "../lib/theme";

export default function ThemeToggle() {
  const [theme, setTheme] = useTheme();
  const [isOpen, setIsOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  const activeOption = THEME_OPTIONS.find((t) => t.id === theme) || THEME_OPTIONS[0];

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    }
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setIsOpen(false);
      }
    }

    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      document.addEventListener("keydown", handleKeyDown);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  const handleSelect = (selectedId: ThemeName) => {
    setTheme(selectedId);
    setIsOpen(false);
  };

  return (
    <div className="theme-selector-wrapper" ref={menuRef} style={{ position: "relative" }}>
      <button
        type="button"
        className="theme-toggle"
        onClick={() => setIsOpen((prev) => !prev)}
        aria-label={`Current theme: ${activeOption.name}. Click to change.`}
        aria-expanded={isOpen}
        title="Change theme palette"
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: "6px",
          padding: "5px 10px",
          borderRadius: "6px",
          cursor: "pointer",
          fontWeight: 600,
          fontSize: "0.82rem",
          background: "var(--surface-alt)",
          border: "1px solid var(--panel-border)",
          color: "var(--text)",
          transition: "all 0.15s ease",
        }}
      >
        <span aria-hidden="true" style={{ fontSize: "0.95rem" }}>
          {activeOption.icon}
        </span>
        <span>{activeOption.name}</span>
        <span style={{ fontSize: "0.65rem", opacity: 0.6, marginLeft: "2px" }}>
          {isOpen ? "▲" : "▼"}
        </span>
      </button>

      {isOpen && (
        <div
          className="theme-dropdown-menu"
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            right: 0,
            zIndex: 1000,
            minWidth: "250px",
            background: "var(--panel)",
            border: "1px solid var(--panel-border)",
            borderRadius: "10px",
            boxShadow: "0 12px 30px rgba(0, 0, 0, 0.4)",
            padding: "6px",
            display: "flex",
            flexDirection: "column",
            gap: "3px",
            animation: "fadeIn 0.15s ease",
          }}
        >
          <div
            style={{
              padding: "6px 10px 4px",
              fontSize: "0.70rem",
              textTransform: "uppercase",
              letterSpacing: "0.06em",
              color: "var(--text-muted)",
              fontWeight: 700,
              borderBottom: "1px solid var(--panel-border)",
              marginBottom: "3px",
            }}
          >
            Select Color Palette
          </div>

          {THEME_OPTIONS.map((opt) => {
            const isSelected = opt.id === theme;
            return (
              <button
                key={opt.id}
                type="button"
                onClick={() => handleSelect(opt.id)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "8px 10px",
                  borderRadius: "6px",
                  border: isSelected ? "1px solid var(--accent)" : "1px solid transparent",
                  background: isSelected ? "var(--surface-alt)" : "transparent",
                  color: "var(--text)",
                  cursor: "pointer",
                  textAlign: "left",
                  width: "100%",
                  transition: "background 0.1s ease",
                }}
                className="theme-menu-item"
              >
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <span style={{ fontSize: "1.1rem" }}>{opt.icon}</span>
                  <div style={{ display: "flex", flexDirection: "column" }}>
                    <span style={{ fontSize: "0.85rem", fontWeight: 700, color: isSelected ? "var(--accent)" : "inherit" }}>
                      {opt.name}
                    </span>
                    <span style={{ fontSize: "0.70rem", color: "var(--text-muted)" }}>
                      {opt.description}
                    </span>
                  </div>
                </div>

                <div style={{ display: "flex", alignItems: "center", gap: "6px", marginLeft: "8px" }}>
                  <span
                    style={{
                      width: "12px",
                      height: "12px",
                      borderRadius: "50%",
                      background: opt.primaryColor,
                      border: "1px solid rgba(255,255,255,0.2)",
                      display: "inline-block",
                    }}
                    title={`Accent: ${opt.primaryColor}`}
                  />
                  {isSelected && (
                    <span style={{ color: "var(--accent)", fontSize: "0.85rem", fontWeight: 800 }}>
                      ✓
                    </span>
                  )}
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
