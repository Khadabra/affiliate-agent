import React from "react";
import type { SystemTelemetry } from "../../types";

interface HeaderProps {
  theme: "dark" | "light";
  onToggleTheme: () => void;
  isOnline: boolean;
  telemetry: SystemTelemetry | null;
  onRefresh: () => void;
  isLoading: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  theme,
  onToggleTheme,
  isOnline,
  telemetry,
  onRefresh,
  isLoading,
}) => {
  return (
    <header className="header">
      <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
        <h2 style={{ fontSize: "1.15rem", fontWeight: 700, letterSpacing: "-0.01em" }}>
          AI Affiliate Content Factory
        </h2>
        <span
          className={`badge ${isOnline ? "badge-success" : "badge-danger"}`}
          title={isOnline ? "FastAPI server running at http://127.0.0.1:8000" : "Cannot reach backend API"}
        >
          <span style={{ fontSize: "0.85em" }}>{isOnline ? "●" : "○"}</span>
          {isOnline ? "API Online" : "API Offline"}
        </span>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
        {/* Quick Resource Summary Pill */}
        {isOnline && telemetry && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "12px",
              fontSize: "0.8rem",
              color: "var(--text-secondary)",
              padding: "4px 12px",
              backgroundColor: "var(--bg-secondary)",
              borderRadius: "6px",
              border: "1px solid var(--border-color)",
            }}
          >
            <span>
              CPU: <strong>{telemetry.cpu.usage_percent !== null ? `${telemetry.cpu.usage_percent}%` : "—"}</strong>
            </span>
            <span style={{ color: "var(--border-subtle)" }}>|</span>
            <span>
              RAM: <strong>{telemetry.memory.usage_percent !== null ? `${telemetry.memory.usage_percent}%` : "—"}</strong>
            </span>
            {telemetry.gpu.available && (
              <>
                <span style={{ color: "var(--border-subtle)" }}>|</span>
                <span>
                  VRAM: <strong>{telemetry.gpu.vram_used_mb}MB</strong>
                </span>
              </>
            )}
          </div>
        )}

        {/* Refresh button */}
        <button
          className="btn btn-secondary"
          onClick={onRefresh}
          disabled={isLoading}
          title="Refresh hardware telemetry"
          style={{ padding: "6px 10px", fontSize: "0.8rem" }}
        >
          {isLoading ? "Refreshing..." : "↻ Refresh"}
        </button>

        {/* Theme switcher */}
        <button
          className="btn btn-secondary"
          onClick={onToggleTheme}
          title={`Switch to ${theme === "dark" ? "Light" : "Dark"} Mode`}
          style={{ padding: "6px 12px", display: "flex", alignItems: "center", gap: "6px" }}
        >
          <span>{theme === "dark" ? "☀ Light" : "🌙 Dark"}</span>
        </button>
      </div>
    </header>
  );
};
