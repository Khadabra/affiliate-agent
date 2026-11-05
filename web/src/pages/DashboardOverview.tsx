import React from "react";
import type { HealthResponse, NavPage, SystemInfo, SystemTelemetry } from "../types";

interface DashboardOverviewProps {
  health: HealthResponse | null;
  systemInfo: SystemInfo | null;
  telemetry: SystemTelemetry | null;
  isOnline: boolean;
  isLoading: boolean;
  error: string | null;
  onNavigate: (page: NavPage) => void;
  onRefresh: () => void;
}

export const DashboardOverview: React.FC<DashboardOverviewProps> = ({
  health,
  systemInfo,
  telemetry,
  isOnline,
  isLoading,
  error,
  onNavigate,
  onRefresh,
}) => {
  return (
    <div className="page-body">
      {/* Top Banner if Offline */}
      {!isOnline && (
        <div
          style={{
            padding: "16px 20px",
            backgroundColor: "var(--danger-bg)",
            border: "1px solid var(--danger)",
            borderRadius: "8px",
            color: "var(--danger-text)",
            marginBottom: "24px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <div>
            <strong>Backend API Offline:</strong> {error || "Cannot reach http://127.0.0.1:8000/health"}.
            <div style={{ fontSize: "0.85rem", marginTop: "4px" }}>
              Start the FastAPI server in terminal: <code>python -m affiliate_factory.api.app</code>
            </div>
          </div>
          <button className="btn btn-secondary" onClick={onRefresh} disabled={isLoading}>
            {isLoading ? "Checking..." : "Retry Connection"}
          </button>
        </div>
      )}

      {/* Header section */}
      <div style={{ marginBottom: "24px" }}>
        <h1 style={{ fontSize: "1.75rem", fontWeight: 700, marginBottom: "6px" }}>
          Dashboard Overview
        </h1>
        <p style={{ color: "var(--text-secondary)", fontSize: "0.95rem" }}>
          Real-time system health, SQLite storage integrity, and workstation hardware telemetry.
        </p>
      </div>

      {/* Grid 1: System Status Cards */}
      <div className="grid-2">
        {/* Card A: System & DB Status */}
        <div className="card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "16px" }}>
            <h3 style={{ fontSize: "1.05rem", fontWeight: 600 }}>System Status</h3>
            <span className={`badge ${isOnline ? "badge-success" : "badge-danger"}`}>
              {isOnline ? "Operational" : "Disconnected"}
            </span>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: "12px", fontSize: "0.875rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ color: "var(--text-secondary)" }}>Application:</span>
              <strong>{systemInfo?.app_name || "AI Affiliate Content Factory"} (v{systemInfo?.version || "1.0.0"})</strong>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ color: "var(--text-secondary)" }}>Binding:</span>
              <code>{systemInfo?.host || "127.0.0.1"}:{systemInfo?.port || 8000} (Localhost)</code>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ color: "var(--text-secondary)" }}>SQLite Journal Mode:</span>
              <strong style={{ color: "var(--success)" }}>
                {health?.journal_mode ? `${health.journal_mode.toUpperCase()} (Hardened)` : isOnline ? "WAL Mode" : "—"}
              </strong>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ color: "var(--text-secondary)" }}>API Cost Policy:</span>
              <span className="badge badge-accent" style={{ fontSize: "0.7rem" }}>
                Zero Mandatory Cost (Rp 0)
              </span>
            </div>
          </div>
        </div>

        {/* Card B: Execution Worker Status */}
        <div className="card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "16px" }}>
            <h3 style={{ fontSize: "1.05rem", fontWeight: 600 }}>Execution Worker</h3>
            <span className="badge badge-warning">
              {systemInfo?.worker_status === "idle_not_started" ? "Standby" : "Not Started"}
            </span>
          </div>

          <p style={{ color: "var(--text-secondary)", fontSize: "0.875rem", marginBottom: "16px", lineHeight: "1.5" }}>
            In accordance with Phase 3.5.1 conservative operational policy, background AI inference and multimedia workers
            are <strong>OFF by default</strong> and require manual operator activation.
          </p>

          <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", backgroundColor: "var(--bg-secondary)", padding: "10px 14px", borderRadius: "6px" }}>
            <strong>Operational Invariant:</strong> Maximum 1 heavy job at a time. Local LLM and FFmpeg rendering never run concurrently.
          </div>
        </div>
      </div>

      {/* Grid 2: Hardware Telemetry */}
      <h3 style={{ fontSize: "1.15rem", fontWeight: 600, marginBottom: "16px" }}>
        Workstation Resource Telemetry
      </h3>

      <div className="grid-4">
        {/* Metric 1: CPU */}
        <div className="card">
          <div style={{ fontSize: "0.8rem", color: "var(--text-secondary)", marginBottom: "4px" }}>
            CPU USAGE
          </div>
          <div style={{ fontSize: "1.5rem", fontWeight: 700, color: "var(--text-primary)" }}>
            {telemetry?.cpu.usage_percent !== null && telemetry?.cpu.usage_percent !== undefined
              ? `${telemetry.cpu.usage_percent}%`
              : isOnline
              ? "Loading..."
              : "—"}
          </div>
          <div className="gauge-bar-track">
            <div
              className="gauge-bar-fill"
              style={{
                width: `${Math.min(100, Math.max(0, telemetry?.cpu.usage_percent || 0))}%`,
                backgroundColor: (telemetry?.cpu.usage_percent || 0) > 85 ? "var(--danger)" : "var(--accent-primary)",
              }}
            />
          </div>
          <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "8px" }}>
            AMD Ryzen 7 ({telemetry?.cpu.physical_cores || 6} Cores / {telemetry?.cpu.logical_cores || 12} Threads)
          </div>
        </div>

        {/* Metric 2: RAM */}
        <div className="card">
          <div style={{ fontSize: "0.8rem", color: "var(--text-secondary)", marginBottom: "4px" }}>
            MEMORY (RAM)
          </div>
          <div style={{ fontSize: "1.5rem", fontWeight: 700, color: "var(--text-primary)" }}>
            {telemetry?.memory.usage_percent !== null && telemetry?.memory.usage_percent !== undefined
              ? `${telemetry.memory.usage_percent}%`
              : isOnline
              ? "Loading..."
              : "—"}
          </div>
          <div className="gauge-bar-track">
            <div
              className="gauge-bar-fill"
              style={{
                width: `${Math.min(100, Math.max(0, telemetry?.memory.usage_percent || 0))}%`,
                backgroundColor: (telemetry?.memory.usage_percent || 0) > 85 ? "var(--danger)" : "var(--accent-primary)",
              }}
            />
          </div>
          <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "8px" }}>
            {telemetry?.memory.used_gb || 0} GB used of {telemetry?.memory.total_gb || 16} GB total
          </div>
        </div>

        {/* Metric 3: GPU / VRAM */}
        <div className="card">
          <div style={{ fontSize: "0.8rem", color: "var(--text-secondary)", marginBottom: "4px" }}>
            GPU & VRAM
          </div>
          <div style={{ fontSize: "1.5rem", fontWeight: 700, color: "var(--text-primary)" }}>
            {telemetry?.gpu.available && telemetry.gpu.vram_used_mb !== null && telemetry.gpu.vram_total_mb
              ? `${Math.round((telemetry.gpu.vram_used_mb / telemetry.gpu.vram_total_mb) * 100)}%`
              : isOnline
              ? "Available"
              : "—"}
          </div>
          <div className="gauge-bar-track">
            <div
              className="gauge-bar-fill"
              style={{
                width:
                  telemetry?.gpu.available && telemetry.gpu.vram_used_mb && telemetry.gpu.vram_total_mb
                    ? `${Math.min(100, Math.round((telemetry.gpu.vram_used_mb / telemetry.gpu.vram_total_mb) * 100))}%`
                    : "0%",
                backgroundColor: "var(--accent-primary)",
              }}
            />
          </div>
          <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "8px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={telemetry?.gpu.name || "NVIDIA RTX 4050 Laptop"}>
            {telemetry?.gpu.name || "NVIDIA RTX 4050"} ({telemetry?.gpu.vram_used_mb || "—"}/{telemetry?.gpu.vram_total_mb || "6141"} MB)
          </div>
        </div>

        {/* Metric 4: Disk Storage */}
        <div className="card">
          <div style={{ fontSize: "0.8rem", color: "var(--text-secondary)", marginBottom: "4px" }}>
            STORAGE DISK ({telemetry?.disk.drive || "D:"})
          </div>
          <div style={{ fontSize: "1.5rem", fontWeight: 700, color: "var(--text-primary)" }}>
            {telemetry?.disk.free_gb !== null && telemetry?.disk.free_gb !== undefined
              ? `${telemetry.disk.free_gb} GB`
              : isOnline
              ? "Loading..."
              : "—"}
          </div>
          <div className="gauge-bar-track">
            <div
              className="gauge-bar-fill"
              style={{
                width: `${Math.min(100, Math.max(0, telemetry?.disk.usage_percent || 0))}%`,
                backgroundColor: "var(--success)",
              }}
            />
          </div>
          <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "8px" }}>
            Free space on repository drive ({telemetry?.disk.usage_percent || 0}% used)
          </div>
        </div>
      </div>

      {/* Grid 3: Quick Navigation to Functional & Placeholder Modules */}
      <h3 style={{ fontSize: "1.15rem", fontWeight: 600, marginBottom: "16px", marginTop: "8px" }}>
        Factory Navigation Modules
      </h3>

      <div className="grid-2">
        <div
          className="card"
          onClick={() => onNavigate("agent-office")}
          style={{ cursor: "pointer", display: "flex", gap: "16px", alignItems: "center" }}
        >
          <div style={{ fontSize: "2rem" }}>🏢</div>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <h4 style={{ fontSize: "1rem", fontWeight: 600 }}>Agent Office</h4>
              <span className="badge badge-accent" style={{ fontSize: "0.65rem" }}>Phase 3.5.3</span>
            </div>
            <p style={{ fontSize: "0.825rem", color: "var(--text-secondary)", marginTop: "4px" }}>
              Inspect 7 specialist agents, task statuses, and transcript execution histories.
            </p>
          </div>
        </div>

        <div
          className="card"
          onClick={() => onNavigate("human-approval")}
          style={{ cursor: "pointer", display: "flex", gap: "16px", alignItems: "center" }}
        >
          <div style={{ fontSize: "2rem" }}>🛡</div>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <h4 style={{ fontSize: "1rem", fontWeight: 600 }}>Human Approval Gate</h4>
              <span className="badge badge-warning" style={{ fontSize: "0.65rem" }}>Phase 3.5.4</span>
            </div>
            <p style={{ fontSize: "0.825rem", color: "var(--text-secondary)", marginTop: "4px" }}>
              Enforce non-negotiable review gate: verify claims, inspect compliance, approve or reject drafts.
            </p>
          </div>
        </div>

        <div
          className="card"
          onClick={() => onNavigate("workflow-monitor")}
          style={{ cursor: "pointer", display: "flex", gap: "16px", alignItems: "center" }}
        >
          <div style={{ fontSize: "2rem" }}>⚡</div>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <h4 style={{ fontSize: "1rem", fontWeight: 600 }}>Workflow Monitor</h4>
              <span className="badge badge-accent" style={{ fontSize: "0.65rem" }}>Phase 3.5.3</span>
            </div>
            <p style={{ fontSize: "0.825rem", color: "var(--text-secondary)", marginTop: "4px" }}>
              Sequential DAG step progress, Server-Sent Events stream, and recovery controls.
            </p>
          </div>
        </div>

        <div
          className="card"
          onClick={() => onNavigate("analytics")}
          style={{ cursor: "pointer", display: "flex", gap: "16px", alignItems: "center" }}
        >
          <div style={{ fontSize: "2rem" }}>📈</div>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <h4 style={{ fontSize: "1rem", fontWeight: 600 }}>Analytics & Angle Ranker</h4>
              <span className="badge badge-accent" style={{ fontSize: "0.65rem" }}>Phase 3.5.5</span>
            </div>
            <p style={{ fontSize: "0.825rem", color: "var(--text-secondary)", marginTop: "4px" }}>
              Deterministic conversion rates (CTR, CVR, AOV, RPC) and CopywritingAdvisor recommendations.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};
